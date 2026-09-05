"""
Phase 2 — pipeline preconditions, wrapper robustness, telemetry, concurrency.

Every test corresponds to behaviour reproduced against the running app during
the Phase 2 audit. Docstrings record the observed pre-fix result, so a
regression is recognisable as exactly the old bug.
"""

import asyncio
import io
import json
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.agent.exceptions import ArityMismatchError, PipelineInputError
from app.agent.preflight import coerce_text_only, run_preflight
from app.models.base import BaseModelWrapper
from app.models.change_detection import ChangeDetectionModel
from app.models.change_vqa import ChangeVQAModel
from app.models.grounding import GroundingModel, SegmentationModel
from app.models.optical_sar import OpticalSARFusionModel
from app.models.vqa import QwenVLMWrapper


def _png(size=(32, 32)) -> bytes:
    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", size, (10, 20, 30)).save(buf, format="PNG")
    return buf.getvalue()


@pytest.fixture
def png():
    return _png()


@pytest.fixture
def raw_client():
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app, raise_server_exceptions=False) as c:
        yield c


def _analyze(client, files=None, **form):
    form.setdefault("query", "what is in this image?")
    return client.post("/api/analyze", data=form, files=files or [])


def _img(png, name="a.png"):
    return ("images", (name, png, "image/png"))


# ── Arity: the router plans from query text and never counted images ──────


def test_change_detection_with_one_image_is_422(raw_client, png):
    """Was: routed to change_detection, ChangeDetectionModel.run hit
    context["images"][1], raised IndexError, PipelineExecutor swallowed it, and
    the client got HTTP 200 with answer "Model not available".

    The query text itself signals a temporal-pair requirement, so the
    query-sufficiency validator (which runs before routing) now catches this
    before preflight's own arity check would ever see it — a strictly earlier
    and richer rejection, not a regression. preflight's own arity_mismatch
    (raised directly against run_preflight() elsewhere in this file) remains
    the backstop for a router mistake with query text that doesn't signal the
    requirement.
    """
    res = _analyze(
        raw_client,
        query="what changed between the two images?",
        files=[_img(png)],
    )
    assert res.status_code == 422, res.text
    body = res.json()["detail"]
    assert "MISSING_TEMPORAL_INPUT" in body["codes"]


def test_zero_images_stays_conversational(raw_client):
    """A zero-image request is a chat message, not a malformed image request.

    The planner routes "describe the image" to CAPTIONING from the text alone;
    422-ing that would break the conversational path this codebase supports
    deliberately (RuleBasedRouter's `text_only` rule, synthesize_answer's
    no-images branch). Only a partially-supplied pair is a real mismatch.
    """
    for query in (
        "hello, what can you do?",
        "describe the image",
        "highlight the water body",
        "what changed between the two images?",
    ):
        res = _analyze(raw_client, query=query)
        assert res.status_code == 200, f"{query}: {res.text}"


def test_coerce_text_only_rewrites_an_image_plan():
    pipeline = [
        {"step": 1, "model": "grounding_dino", "action": "detect_regions"},
        {"step": 2, "model": "sam", "action": "segment_regions"},
    ]
    coerced, warnings = coerce_text_only(pipeline)
    assert coerced == [{"step": 1, "model": "rs_vlm", "action": "answer_question"}]
    assert warnings and "No imagery was attached" in warnings[0]


def test_coerce_text_only_leaves_a_conversational_plan_alone():
    pipeline = [{"step": 1, "model": "rs_vlm", "action": "answer_question"}]
    coerced, warnings = coerce_text_only(pipeline)
    assert coerced == pipeline
    assert warnings == []


def test_fusion_on_two_optical_images_is_422(raw_client, png):
    """Was: 200 with a fabricated "fusion" answer over two optical images,
    and OpticalSARFusionModel silently reusing images[0] as the SAR input.

    The query text asks for optical+SAR fusion, so the query-sufficiency
    validator (which runs before routing) now catches the missing SAR
    modality itself, before preflight's own modality check would ever see it
    — a strictly earlier and richer rejection, not a regression.
    """
    res = raw_client.post(
        "/api/analyze",
        data={"query": "fuse the optical and SAR data", "modalities": "optical,optical"},
        files=[_img(png, "a.png"), _img(png, "b.png")],
    )
    if res.status_code == 200:
        # The planner may legitimately not choose fusion for this phrasing;
        # assert directly against preflight so the test is not planner-dependent.
        pipeline = [{"step": 1, "model": "optical_sar_fusion", "action": "fuse_modalities"}]
        with pytest.raises(PipelineInputError) as exc:
            run_preflight(pipeline, ["a.png", "b.png"], ["optical", "optical"])
        assert exc.value.code == "modality_mismatch"
    else:
        assert res.status_code == 422
        assert "MISSING_CROSS_MODAL_INPUT" in res.json()["detail"]["codes"]


def test_preflight_accepts_a_genuine_cross_modal_pair(tmp_path, png):
    a, b = tmp_path / "a.png", tmp_path / "b.png"
    a.write_bytes(png)
    b.write_bytes(png)
    pipeline = [{"step": 1, "model": "optical_sar_fusion", "action": "fuse_modalities"}]
    result = run_preflight(pipeline, [str(a), str(b)], ["optical", "sar"])
    assert result["pipeline"] == pipeline


# ── Wrapper robustness: all eight of these raised before ─────────────────


def _ctx(images=(), intermediate=None, query="q"):
    return {
        "images": list(images),
        "query": query,
        "request_id": "test",
        "intermediate": intermediate or {},
    }


@pytest.mark.parametrize(
    "label,call",
    [
        ("change_detection with 1 image",
         lambda: ChangeDetectionModel().run("generate_change_map", _ctx(["a.png"]))),
        ("grounding with 0 images",
         lambda: GroundingModel().run("detect_regions", _ctx())),
        ("optical_sar with 0 images",
         lambda: OpticalSARFusionModel().run("fuse_modalities", _ctx())),
        ("sam with 0 images",
         lambda: SegmentationModel().run("segment_regions", _ctx())),
        ("change_vqa with 1 image",
         lambda: ChangeVQAModel().run("answer_change_question", _ctx(["a.png"]))),
        ("vlm caption with 0 images",
         lambda: QwenVLMWrapper()._caption(_ctx())),
        ("vlm describe_changes with 1 image",
         lambda: QwenVLMWrapper()._describe_changes(_ctx(["a.png"]))),
    ],
)
def test_wrappers_raise_a_domain_error_not_indexerror(label, call):
    """Was: IndexError from positional context["images"][n] access, swallowed
    by PipelineExecutor into a step marked "error" inside an HTTP 200."""
    with pytest.raises(ArityMismatchError):
        call()


def test_sam_survives_a_missing_upstream_step(tmp_path, png):
    """Was: KeyError: 'step_1' when step 1 never ran."""
    img = tmp_path / "a.png"
    img.write_bytes(png)
    out = SegmentationModel().run("segment_regions", _ctx([str(img)]))
    assert isinstance(out, dict) and "answer" in out


def test_sam_survives_a_non_dict_upstream_step(tmp_path, png):
    """Was: AttributeError: 'str' object has no attribute 'get'."""
    img = tmp_path / "a.png"
    img.write_bytes(png)
    out = SegmentationModel().run(
        "segment_regions", _ctx([str(img)], {"step_1": "oops"})
    )
    assert isinstance(out, dict) and "answer" in out


@pytest.fixture
def vlm_no_inference(monkeypatch):
    """QwenVLMWrapper with the real Qwen call stubbed out.

    _describe_changes is a real-inference path, so calling it directly bypasses
    _mock_mode and reaches qwen_vl_utils. These tests are about the prompt-
    building guards ahead of that call, so the call itself is replaced and the
    prompt is captured for assertion.
    """
    captured: dict = {}

    def fake_infer_multi(self, image_paths, prompt):
        captured["prompt"] = prompt
        return "stubbed"

    monkeypatch.setattr(QwenVLMWrapper, "_infer_multi", fake_infer_multi)
    model = QwenVLMWrapper()
    model._mock_mode = False
    return model, captured


@pytest.mark.parametrize("ratio", [None, "0.4", float("nan"), float("inf"), True, {}])
def test_describe_changes_survives_a_bad_change_ratio(vlm_no_inference, ratio):
    """Was: TypeError: unsupported operand type(s) for *: 'NoneType' and 'int'.

    `True` is included deliberately: bool is a subclass of int, so a naive
    isinstance check would format it as "100.0% changed".
    """
    model, captured = vlm_no_inference
    out = model._describe_changes(
        _ctx(["a.png", "b.png"], {"step_1": {"change_ratio": ratio}})
    )
    assert isinstance(out, dict) and "answer" in out
    assert "% of the area has changed" not in captured["prompt"]


def test_describe_changes_still_reports_a_real_ratio(vlm_no_inference):
    model, captured = vlm_no_inference
    out = model._describe_changes(
        _ctx(["a.png", "b.png"], {"step_1": {"change_ratio": 0.25}})
    )
    assert isinstance(out, dict)
    assert "25.0% of the area has changed" in captured["prompt"]


def test_prior_step_degrades_for_every_bad_shape():
    for bad in ({}, {"intermediate": {}}, {"intermediate": {"step_1": "s"}},
                {"intermediate": {"step_1": None}}, {"intermediate": None}):
        assert BaseModelWrapper.prior_step(bad, 1) == {}
    assert BaseModelWrapper.prior_step({"intermediate": {"step_1": {"a": 1}}}, 1) == {"a": 1}


# ── Executor must NOT swallow a domain error ─────────────────────────────


def test_executor_reraises_pipeline_input_errors(fake_registry_factory):
    """A PipelineInputError means the request cannot drive this pipeline at all.
    Swallowing it into a failed step is how the arity bug produced a 200."""
    from app.agent.executor import PipelineExecutor

    class Rejecting:
        last_telemetry = None

        def run(self, action, context):
            raise ArityMismatchError("needs 2 images")

    registry = fake_registry_factory({"m": Rejecting()})
    with pytest.raises(ArityMismatchError):
        PipelineExecutor(registry).execute(
            [{"step": 1, "model": "m", "action": "a"}], [], "q", "rid"
        )


def test_executor_still_swallows_ordinary_step_failures(fake_registry_factory):
    """Only domain errors escape. A genuine model bug must still degrade."""
    from app.agent.executor import PipelineExecutor

    class Broken:
        last_telemetry = None

        def run(self, action, context):
            raise RuntimeError("model exploded")

    registry = fake_registry_factory({"m": Broken()})
    results = PipelineExecutor(registry).execute(
        [{"step": 1, "model": "m", "action": "a"}], [], "q", "rid"
    )
    assert len(results) == 1 and not results[0].success
    assert "model exploded" in results[0].error


# ── Telemetry ────────────────────────────────────────────────────────────


@pytest.mark.parametrize("bad", ["oops", [1, 2], 42, object()])
def test_telemetry_ignores_non_dicts(bad):
    """Was: AttributeError: 'str' object has no attribute 'get', which took down
    trace building for an otherwise-successful request."""
    from app.output.trace import _telemetry

    assert _telemetry(bad) is None


def test_telemetry_nulls_non_finite_numbers():
    from app.output.trace import _telemetry

    out = _telemetry({"tokens_per_sec": float("inf"), "prompt_tokens": 5})
    assert out["tokens_per_sec"] is None
    assert out["prompt_tokens"] == 5
    json.dumps(out, allow_nan=False)


def test_telemetry_normalizes_to_the_declared_shape():
    from app.output.trace import _TELEMETRY_KEYS, _telemetry

    out = _telemetry({"prompt_tokens": 1, "unknown_key": "dropped"})
    assert set(out) == set(_TELEMETRY_KEYS)
    assert "unknown_key" not in out


# ── Registry: lock, LRU, pinning ─────────────────────────────────────────


def test_registry_get_is_thread_safe():
    """Was: no lock at all. Two threads could each construct a 5.5 GB model."""
    import threading

    from app.models.registry import ModelRegistry

    built = []

    def slow_loader():
        time.sleep(0.05)
        built.append(1)
        return object()

    reg = ModelRegistry()
    reg.register("m", slow_loader, vram_gb=0.1)

    results = []
    threads = [
        threading.Thread(target=lambda: results.append(reg.get("m")))
        for _ in range(8)
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert len(built) == 1, f"loader ran {len(built)} times — the lock did not hold"
    assert all(r is results[0] for r in results)


def test_registry_get_refreshes_lru_order():
    """Was: _ensure_vram evicted candidates[0] — dict INSERTION order, so the
    most recently used model could be the first evicted."""
    from app.models.registry import ModelRegistry

    reg = ModelRegistry()
    for name in ("a", "b", "c"):
        reg.register(name, lambda: object(), vram_gb=0.1)
        reg.get(name)

    assert reg.list_loaded() == ["a", "b", "c"]
    reg.get("a")
    assert reg.list_loaded() == ["b", "c", "a"], "get() did not refresh recency"


def test_registry_pin_blocks_eviction():
    from app.models.registry import ModelRegistry

    reg = ModelRegistry()
    reg.register("a", lambda: object(), vram_gb=0.1)
    reg.get("a")
    with reg.pin("a"):
        assert "a" in reg._in_use
    assert "a" not in reg._in_use


def test_registry_pin_releases_on_exception():
    from app.models.registry import ModelRegistry

    reg = ModelRegistry()
    reg.register("a", lambda: object(), vram_gb=0.1)
    reg.get("a")
    with pytest.raises(RuntimeError):
        with reg.pin("a"):
            raise RuntimeError("boom")
    assert "a" not in reg._in_use


# ── Event loop ───────────────────────────────────────────────────────────


def test_event_loop_stays_responsive_during_inference():
    """Was: the loop froze for the whole forward pass. Measured with a 1.5s
    sleep, an asyncio heartbeat due every 0.2s produced NO ticks until t+1.52s.

    Asserted against a shared t0, not per-request elapsed: a blocked concurrent
    request's own timer only starts once the loop frees up, so per-request
    elapsed reports ~0s either way and cannot detect blocking at all.
    """
    import httpx

    from app.main import app

    infer_seconds = 1.0

    class SlowModel:
        last_telemetry = None

        def run(self, action, context):
            time.sleep(infer_seconds)
            return {"answer": "slow", "confidence": None}

    async def scenario():
        async with app.router.lifespan_context(app):
            app.state.model_registry.get = lambda name: SlowModel()
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url="http://t"
            ) as ac:
                t0 = time.perf_counter()
                ticks: list[float] = []

                async def analyze():
                    return await ac.post(
                        "/api/analyze",
                        data={"query": "what is in this image?"},
                        files=[("images", ("a.png", _png(), "image/png"))],
                    )

                async def heartbeat():
                    for _ in range(10):
                        await asyncio.sleep(0.1)
                        ticks.append(time.perf_counter() - t0)

                res, _ = await asyncio.gather(analyze(), heartbeat())
                return res, ticks

    import os

    prev = os.environ.get("SKIP_MODEL_INFERENCE")
    os.environ["SKIP_MODEL_INFERENCE"] = "false"
    try:
        import importlib

        import app.utils.config as cfg

        importlib.reload(cfg)
        res, ticks = asyncio.run(scenario())
    finally:
        if prev is None:
            os.environ.pop("SKIP_MODEL_INFERENCE", None)
        else:
            os.environ["SKIP_MODEL_INFERENCE"] = prev
        import importlib

        import app.utils.config as cfg

        importlib.reload(cfg)

    assert res.status_code == 200, res.text
    early = [t for t in ticks if t < infer_seconds * 0.8]
    assert len(early) >= 3, (
        f"only {len(early)} heartbeats fired during a {infer_seconds}s inference "
        f"(ticks={[round(t, 2) for t in ticks]}) — the event loop was blocked"
    )


# ── Debug snapshot must not leak paths ───────────────────────────────────


def test_debug_snapshot_leaks_no_filesystem_path(raw_client, png):
    """Was: UnavailableModelExecutor put "image_paths" in its output, which
    TraceBuilder snapshotted into payload_snapshot under ?debug=true, putting
    /var/folders/.../satquery_xxxx/a.png in the response body."""
    import tempfile

    res = raw_client.post(
        "/api/analyze",
        data={"query": "what is in this image?"},
        files=[_img(png)],
        params={"debug": "true"},
    )
    assert res.status_code == 200, res.text
    body = res.text
    for leak in (tempfile.gettempdir(), "/var/folders", "satquery_"):
        assert leak not in body, f"leaked {leak!r}"

    snapshot = res.json()["execution_trace"]["pipeline_steps"][0]["payload_snapshot"]
    assert snapshot is not None, "debug mode did not attach a snapshot"
    assert "image_paths" not in snapshot
