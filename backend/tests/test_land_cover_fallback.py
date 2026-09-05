"""
Fast land-cover pre-check: parallel dispatch, threshold gating, and fallback.

Covers the orchestration rules in app/agent/land_cover_check.py and their
wiring into app/api/routes.py:
  1. Land-cover check and query routing run CONCURRENTLY, not sequentially.
  2. land_pct >= threshold: proceeds to the VLM exactly as before.
  3. land_pct < threshold: the VLM is never dispatched at all — the fast
     land-cover breakdown is returned instead.
  4. A stub with no real model (land_pct=None) never blocks a real request —
     behaves exactly as if the check had not run.
"""

import io
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.agent.hybrid_executor import HybridPipelineExecutor


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


def _img(png, name="a.png"):
    return ("images", (name, png, "image/png"))


class _FakeLandCoverModel:
    """Test double standing in for LandCoverModel — same run() contract."""

    def __init__(self, land_pct, breakdown=None, delay_s: float = 0.0):
        self.land_pct = land_pct
        self.breakdown = breakdown or {
            "water": 0.0, "forest": land_pct or 0.0, "vegetation": 0.0,
            "barren": 0.0, "urban": 100.0 - (land_pct or 0.0),
        }
        self.delay_s = delay_s

    def run(self, action, context):
        if self.delay_s:
            time.sleep(self.delay_s)
        return {"type": "land_cover", "breakdown": self.breakdown, "land_pct": self.land_pct}


def _patch_land_cover(monkeypatch, registry, model):
    real_get = registry.get

    def fake_get(name):
        if name == "land_cover":
            return model
        return real_get(name)

    monkeypatch.setattr(registry, "get", fake_get)


def test_stub_land_cover_never_blocks_a_request(raw_client, png, rule_router):
    """The real (unmodified) stub reports land_pct=None — the default,
    no-injection case. This must behave exactly as it did before this
    feature existed: full dispatch attempted, no fallback branch taken."""
    res = raw_client.post(
        "/api/analyze",
        data={"query": "what objects are present?", "modalities": "optical"},
        files=[_img(png)],
    )
    assert res.status_code == 200, res.text
    trace = res.json()["execution_trace"]
    lc = trace["land_cover_check"]
    assert lc is not None
    assert lc["available"] is False
    assert lc["land_pct"] is None
    assert lc["passed"] is None
    assert trace["fallback_strategy"]["triggered"] is False


def test_below_threshold_skips_dispatch_entirely(raw_client, png, rule_router, monkeypatch):
    """land_pct below threshold: HybridPipelineExecutor.execute must never
    be called at all — this is the "cancel/abort before it starts" path."""
    registry = raw_client.app.state.model_registry
    _patch_land_cover(monkeypatch, registry, _FakeLandCoverModel(land_pct=20.0))

    called = []

    def must_not_be_called(self, *a, **k):
        called.append(1)
        raise AssertionError("HybridPipelineExecutor.execute must not be called")

    monkeypatch.setattr(HybridPipelineExecutor, "execute", must_not_be_called)

    res = raw_client.post(
        "/api/analyze",
        data={"query": "what objects are present?", "modalities": "optical"},
        files=[_img(png)],
    )
    assert res.status_code == 200, res.text
    assert not called, "the remote VLM was dispatched despite failing the land-cover threshold"

    body = res.json()
    assert "20.0" in body["answer"] or "20" in body["answer"]
    trace = body["execution_trace"]
    assert trace["land_cover_check"]["land_pct"] == 20.0
    assert trace["land_cover_check"]["passed"] is False
    assert trace["fallback_strategy"] == {
        "triggered": True,
        "reason": "land_cover_below_threshold",
        "action": (
            "Displayed the fast land-cover breakdown instead of "
            "dispatching to the remote VLM."
        ),
    }
    assert trace["remote_dispatch"] == {"dispatched": False, "node_id": None, "task": None}
    # Skipped entirely — never even ran preflight/execution/integration.
    assert trace["timings"]["execution_ms"] == 0.0
    assert trace["pipeline_steps"] == []


def test_above_threshold_proceeds_to_normal_dispatch(raw_client, png, rule_router, monkeypatch):
    """land_pct at/above threshold: the model path runs exactly as before —
    this feature must not change accepted-request behavior at all."""
    registry = raw_client.app.state.model_registry
    _patch_land_cover(monkeypatch, registry, _FakeLandCoverModel(land_pct=85.0))

    called = []
    real_execute = HybridPipelineExecutor.execute

    def spy_execute(self, *a, **k):
        called.append(1)
        return real_execute(self, *a, **k)

    monkeypatch.setattr(HybridPipelineExecutor, "execute", spy_execute)

    res = raw_client.post(
        "/api/analyze",
        data={"query": "what objects are present?", "modalities": "optical"},
        files=[_img(png)],
    )
    assert res.status_code == 200, res.text
    assert called, "the VLM dispatch was skipped despite passing the land-cover threshold"

    trace = res.json()["execution_trace"]
    assert trace["land_cover_check"]["land_pct"] == 85.0
    assert trace["land_cover_check"]["passed"] is True
    assert trace["fallback_strategy"]["triggered"] is False


def test_skipped_for_sar_modality(raw_client, png, rule_router, monkeypatch):
    """Spec: the check is for an optical PNG. A SAR-only upload should never
    even attempt it — land_cover_check is None, not an unavailable result."""
    registry = raw_client.app.state.model_registry
    real_get = registry.get
    requested_names = []

    def recording_get(name):
        requested_names.append(name)
        return real_get(name)

    monkeypatch.setattr(registry, "get", recording_get)

    res = raw_client.post(
        "/api/analyze",
        data={"query": "what objects are present?", "modalities": "sar"},
        files=[_img(png)],
    )
    assert res.status_code == 200, res.text
    assert res.json()["execution_trace"]["land_cover_check"] is None
    assert "land_cover" not in requested_names


def test_skipped_for_zero_images(raw_client, rule_router):
    """A text-only turn has nothing to segment."""
    res = raw_client.post(
        "/api/analyze",
        data={"query": "hello, what can you do?"},
        files=[],
    )
    assert res.status_code == 200, res.text
    assert res.json()["execution_trace"]["land_cover_check"] is None


def test_land_cover_and_routing_run_concurrently(raw_client, png, rule_router, monkeypatch):
    """The defining requirement: land-cover and routing run IN PARALLEL, not
    one after the other. Both artificially delayed by the same amount; if
    they ran sequentially the request would take roughly 2x that delay."""
    from app.agent import router as router_module

    delay_s = 0.2
    registry = raw_client.app.state.model_registry
    _patch_land_cover(
        monkeypatch, registry, _FakeLandCoverModel(land_pct=90.0, delay_s=delay_s)
    )

    real_route = router_module.RuleBasedRouter.route

    def slow_route(self, *a, **k):
        time.sleep(delay_s)
        return real_route(self, *a, **k)

    monkeypatch.setattr(router_module.RuleBasedRouter, "route", slow_route)

    t0 = time.perf_counter()
    res = raw_client.post(
        "/api/analyze",
        data={"query": "what objects are present?", "modalities": "optical"},
        files=[_img(png)],
    )
    elapsed_s = time.perf_counter() - t0

    assert res.status_code == 200, res.text
    # Sequential would take >= 2 * delay_s (~0.4s); concurrent stays close to
    # one delay_s (~0.2s). 1.5x gives generous headroom for CI scheduling
    # noise while still failing hard on a truly sequential implementation.
    assert elapsed_s < delay_s * 1.5, (
        f"land-cover check and routing did not run concurrently: "
        f"took {elapsed_s:.3f}s for two {delay_s}s operations"
    )


def test_genuine_remote_failure_falls_back_to_land_cover(raw_client, png, rule_router, monkeypatch):
    """A real remote_error (paired host reachable but the call itself
    failed) is the spec's *other* fallback trigger — distinct from "no
    weights loaded, no host paired" (this app's normal honest-stub state,
    which must NOT be treated as a failure to fall back from; see
    test_above_threshold_proceeds_to_normal_dispatch)."""
    from app.agent import hybrid_executor as hybrid_executor_module
    from app.node.schemas import InferenceResponse

    registry = raw_client.app.state.model_registry
    _patch_land_cover(monkeypatch, registry, _FakeLandCoverModel(land_pct=90.0))

    class _FakeNode:
        node_id = "fake-node"

    class _FakeNodeRegistry:
        def list_nodes(self):
            return [_FakeNode()]  # non-empty: has_remote must be True

    monkeypatch.setattr(
        hybrid_executor_module, "get_registry", lambda reload=False: _FakeNodeRegistry()
    )
    monkeypatch.setattr(
        hybrid_executor_module,
        "try_remote_vlm",
        lambda **kwargs: InferenceResponse(
            request_id="fake",
            status="error",
            node_id="fake-node",
            error_code="REMOTE_TIMEOUT",
            error="timed out",
        ),
    )

    res = raw_client.post(
        "/api/analyze",
        data={"query": "what objects are present?", "modalities": "optical"},
        files=[_img(png)],
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert "90.0" in body["answer"] or "90" in body["answer"]

    trace = body["execution_trace"]
    assert trace["fallback_strategy"] == {
        "triggered": True,
        "reason": "remote_vlm_failed",
        "action": "Displayed the fast land-cover breakdown after the model path failed.",
    }
    # This one DID attempt dispatch (unlike the pre-dispatch threshold gate,
    # which never even tries) — the remote step ran and reported REMOTE
    # execution, it just failed.
    assert trace["remote_dispatch"]["dispatched"] is True
    assert trace["remote_dispatch"]["node_id"] == "fake-node"
