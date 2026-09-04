"""
End-to-end contract tests for POST /api/analyze.

The routes deliberately carry no `response_model=` (it would silently drop
unknown keys and turn a schema slip into a mid-demo 500), so validating the
real response against the Pydantic schema here is what actually enforces the
contract.
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.api.schemas import AnalysisResponse


def _post(client, tiny_png, query="What objects are present?", params=None, files=None):
    if files is None:
        with open(tiny_png, "rb") as fh:
            files = [("images", ("tiny.png", fh.read(), "image/png"))]
    return client.post(
        "/api/analyze",
        data={"query": query, "modalities": "optical"},
        files=files,
        params=params or {},
    )


def test_response_matches_the_schema(client, tiny_png):
    res = _post(client, tiny_png)

    assert res.status_code == 200, res.text
    AnalysisResponse.model_validate(res.json())


def test_response_is_strictly_valid_json(client, tiny_png):
    """Guards the NaN class of bug: FastAPI emits bare NaN, which is invalid
    JSON and throws in JSON.parse on the client."""
    res = _post(client, tiny_png)
    json.loads(res.text, parse_constant=_reject_constant)


def _reject_constant(name):
    raise AssertionError(f"non-finite constant {name!r} leaked into the response")


def test_trace_carries_real_router_telemetry(client, tiny_png):
    res = _post(client, tiny_png, query="Highlight the water body")
    trace = res.json()["execution_trace"]
    meta = trace["router_metadata"]

    assert meta["rule_id"] == "grounding_keywords"
    assert "highlight" in meta["matched_keywords"]
    assert meta["router_type"] == "rule_based_keyword"
    assert meta["routing_time_ms"] >= 0
    assert trace["request_id"]


def test_llm_planner_fields_are_null_over_the_wire(client, tiny_png):
    res = _post(client, tiny_png)
    meta = res.json()["execution_trace"]["router_metadata"]

    for field in ("planner_type", "planning_time_ms", "prompt_tokens",
                  "completion_tokens", "tokens_per_sec", "intent_decomposition"):
        assert meta[field] is None


def test_no_fabricated_model_version_over_the_wire(client, tiny_png):
    res = _post(client, tiny_png)
    for model in res.json()["execution_trace"]["selected_models"]:
        assert model["version"] is None
        assert model["selection_reason"]


def test_snapshots_are_off_by_default(client, tiny_png):
    res = _post(client, tiny_png)
    trace = res.json()["execution_trace"]

    assert trace["debug"] is False
    for step in trace["pipeline_steps"]:
        # Explicitly null rather than absent, so the response shape is stable.
        assert step["payload_snapshot"] is None


def test_debug_param_enables_snapshots(client, tiny_png):
    res = _post(client, tiny_png, params={"debug": "true"})
    trace = res.json()["execution_trace"]

    assert trace["debug"] is True
    assert any(s["payload_snapshot"] is not None for s in trace["pipeline_steps"])


def test_timings_are_populated_and_consistent(client, tiny_png):
    trace = _post(client, tiny_png).json()["execution_trace"]
    timings = trace["timings"]

    assert timings["upload_ms"] >= 0
    assert timings["validation_ms"] >= 0
    assert timings["other_ms"] >= 0
    # The old (wrong) total is preserved separately; the headline number is
    # now real handler wall clock and must be at least as large.
    assert trace["total_time_ms"] >= timings["pipeline_steps_ms"]


def test_input_composition_reflects_the_upload(client, tiny_png):
    comp = _post(client, tiny_png).json()["execution_trace"]["input_composition"]

    assert comp["images"][0]["width"] == 32
    assert comp["images"][0]["height"] == 32
    assert comp["total_pixels"] == 32 * 32
    assert comp["images"][0]["modality"] == "optical"


def test_text_only_query_is_accepted(client):
    res = client.post(
        "/api/analyze",
        data={"query": "What can you do?", "modalities": "optical"},
    )

    assert res.status_code == 200, res.text
    trace = res.json()["execution_trace"]
    assert trace["router_metadata"]["rule_id"] == "text_only"
    assert trace["input_composition"]["images"] == []


def test_three_images_are_rejected(client, tiny_png):
    with open(tiny_png, "rb") as fh:
        blob = fh.read()
    files = [("images", (f"i{i}.png", blob, "image/png")) for i in range(3)]

    res = _post(client, tiny_png, files=files)
    assert res.status_code == 422


def test_confidence_stays_null_without_real_models(client, tiny_png):
    """No weights are loaded in this environment, so nothing can report a
    genuine score — and nothing may invent one."""
    body = _post(client, tiny_png).json()

    assert body["confidence"] is None
    assert body["execution_trace"]["task_confidence"] is None
