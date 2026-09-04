"""
Tests for the execution trace.

The governing rule for this whole feature: every field is either measured or
null. These tests exist mostly to stop fabricated values creeping back in.
"""

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest

from app.agent.executor import StepResult
from app.agent.router import RuleBasedRouter
from app.agent.validator import ValidationResult
from app.models.registry import ModelRegistry
from app.output.trace import TraceBuilder


@pytest.fixture
def decision():
    return RuleBasedRouter().route(
        "Highlight the water body", {"num_images": 1, "modalities": ["optical"]}
    )


@pytest.fixture
def validation():
    return ValidationResult(
        is_valid=True,
        num_images=1,
        modalities=["optical"],
        is_temporal=False,
        is_cross_modal=False,
        format_info=[{
            "filename": "scene.png",
            "size": [640, 480],
            "bands": 3,
            "format": ".png",
            "file_size_mb": 0.25,
        }],
    )


@pytest.fixture
def registry():
    reg = ModelRegistry()
    reg.register("grounding_dino", lambda: object(), vram_gb=0.7)
    reg.register("sam", lambda: object(), vram_gb=0.35)
    return reg


@pytest.fixture
def step_results():
    return [
        StepResult(1, "grounding_dino", "detect_regions", {"boxes": [], "target": "water body"},
                   time_ms=12.5, success=True, load_time_ms=10.0,
                   inference_time_ms=2.5, model_was_cached=False, started_at_ms=0.0),
        StepResult(2, "sam", "segment_regions", {"answer": "ok", "confidence": None},
                   time_ms=3.0, success=True, load_time_ms=0.5,
                   inference_time_ms=2.5, model_was_cached=True, started_at_ms=12.5),
    ]


def _build(validation, decision, step_results, registry, **kwargs):
    return TraceBuilder().build(
        validation, decision, step_results, registry=registry,
        metadata={"modalities": ["optical"], "dates": []}, **kwargs
    )


def test_no_fabricated_model_version(validation, decision, step_results, registry):
    """The previous trace hardcoded {"version": "1.0"} for every model; the
    registry has no version field, so that number was invented."""
    trace = _build(validation, decision, step_results, registry)

    assert '"1.0"' not in json.dumps(trace, default=str)
    for model in trace["selected_models"]:
        assert model["version"] is None


def test_selected_models_carry_real_registry_state(validation, decision, step_results, registry):
    trace = _build(validation, decision, step_results, registry)
    by_name = {m["name"]: m for m in trace["selected_models"]}

    assert by_name["grounding_dino"]["vram_gb"] == 0.7
    assert by_name["sam"]["vram_gb"] == 0.35
    assert all(m["registered"] for m in trace["selected_models"])
    assert all(m["loaded"] is False for m in trace["selected_models"])


def test_unregistered_model_is_flagged(validation, decision, step_results):
    """The router hardcodes model-name literals, so a rename in main.py has
    to surface somewhere rather than as an unexplained step failure."""
    empty = ModelRegistry()
    trace = _build(validation, decision, step_results, empty)

    assert all(m["registered"] is False for m in trace["selected_models"])
    assert all(m["vram_gb"] is None for m in trace["selected_models"])


def test_selection_reason_quotes_the_router_not_invented_prose(validation, decision, step_results, registry):
    trace = _build(validation, decision, step_results, registry)

    for model in trace["selected_models"]:
        reason = model["selection_reason"]
        # Must be built from what the router actually said.
        assert decision.reasoning in reason
        assert decision.rule_id in reason
    # And must name the step this model was really assigned.
    by_name = {m["name"]: m for m in trace["selected_models"]}
    assert "detect_regions" in by_name["grounding_dino"]["selection_reason"]
    assert "segment_regions" in by_name["sam"]["selection_reason"]


def test_router_metadata_reports_real_rule_and_keywords(validation, decision, step_results, registry):
    trace = _build(validation, decision, step_results, registry,
                   stage_ms={"routing_ms": 0.4})
    meta = trace["router_metadata"]

    assert meta["router_type"] == "rule_based_keyword"
    assert meta["rule_id"] == "grounding_keywords"
    assert "highlight" in meta["matched_keywords"]
    assert meta["fallback_used"] is False
    assert meta["routing_time_ms"] == 0.4


def test_llm_planner_fields_are_null_never_placeholders(validation, decision, step_results, registry):
    """This repo's router has no language model. These fields exist so a
    future LLM planner can fill them without a breaking schema change — they
    must never carry stand-in values."""
    trace = _build(validation, decision, step_results, registry)
    meta = trace["router_metadata"]

    for field in ("planner_type", "planning_time_ms", "prompt_tokens",
                  "completion_tokens", "tokens_per_sec", "intent_decomposition",
                  "planner_raw_output"):
        assert meta[field] is None, f"{field} must be null, not fabricated"


def test_task_confidence_stays_null(validation, decision, step_results, registry):
    trace = _build(validation, decision, step_results, registry)
    assert trace["task_confidence"] is None


def test_fallback_route_is_flagged(validation, step_results, registry):
    decision = RuleBasedRouter().route(
        "How many buildings are there?", {"num_images": 1, "modalities": ["optical"]}
    )
    trace = _build(validation, decision, step_results, registry)

    assert trace["router_metadata"]["rule_id"] == "default_vqa"
    assert trace["router_metadata"]["fallback_used"] is True


def test_step_timing_split_is_exposed(validation, decision, step_results, registry):
    trace = _build(validation, decision, step_results, registry)
    step = trace["pipeline_steps"][0]

    assert step["load_time_ms"] == 10.0
    assert step["inference_time_ms"] == 2.5
    assert step["model_was_cached"] is False
    # No DAG exists, so this must not claim one.
    assert step["depends_on"] is None


def test_payload_snapshot_is_gated_on_debug(validation, decision, step_results, registry):
    off = _build(validation, decision, step_results, registry, debug=False)
    on = _build(validation, decision, step_results, registry, debug=True)

    assert off["debug"] is False
    # Explicitly null rather than absent, so the shape stays stable.
    assert off["pipeline_steps"][0]["payload_snapshot"] is None
    assert off["pipeline_steps"][0]["payload_bytes"] is None

    assert on["debug"] is True
    assert on["pipeline_steps"][0]["payload_snapshot"] == {"boxes": [], "target": "water body"}
    assert on["pipeline_steps"][0]["payload_bytes"] > 0


def test_total_time_is_wall_clock_not_step_sum(validation, decision, step_results, registry):
    """total_time_ms used to be sum(step.time_ms), which excluded upload,
    validation, routing and integration — so it was never request latency."""
    t0 = time.perf_counter() - 0.25  # pretend the request began 250ms ago
    trace = _build(validation, decision, step_results, registry, request_t0=t0,
                   stage_ms={"upload_ms": 5.0, "validation_ms": 3.0, "routing_ms": 0.2,
                             "execution_ms": 15.5, "integration_ms": 0.4})

    assert trace["total_time_ms"] >= 240
    assert trace["timings"]["pipeline_steps_ms"] == 15.5
    assert trace["total_time_ms"] > trace["timings"]["pipeline_steps_ms"]
    assert trace["timings"]["other_ms"] >= 0


def test_other_ms_never_goes_negative(validation, decision, step_results, registry):
    trace = _build(validation, decision, step_results, registry,
                   stage_ms={"upload_ms": 999.0})
    assert trace["timings"]["other_ms"] >= 0


def test_input_composition_is_derived_from_real_validation(validation, decision, step_results, registry):
    trace = _build(validation, decision, step_results, registry)
    comp = trace["input_composition"]

    assert comp["total_pixels"] == 640 * 480
    assert comp["total_size_mb"] == 0.25
    assert comp["images"][0]["filename"] == "scene.png"
    assert comp["images"][0]["modality"] == "optical"
    # The backend never parses CRS — claiming one would be a guess.
    assert comp["crs"] is None


def test_trace_is_json_serializable(validation, decision, step_results, registry):
    trace = _build(validation, decision, step_results, registry, debug=True)
    json.dumps(trace, allow_nan=False)


def test_trace_validates_against_the_pydantic_schema(validation, decision, step_results, registry):
    """The routes deliberately have no response_model=, so this is where the
    contract actually gets enforced."""
    from app.api.schemas import ExecutionTrace

    trace = _build(validation, decision, step_results, registry, debug=True,
                   request_id="abc123", request_t0=time.perf_counter())
    ExecutionTrace.model_validate(trace)


def test_schema_validates_the_risky_shapes(validation, decision, registry):
    """The happy-path fixture has telemetry=None, error=None, success=True and
    no snapshots — so the three shapes most likely to drift were never
    validated. This covers all of them at once."""
    from app.api.schemas import ExecutionTrace

    steps = [
        # Populated telemetry, deliberately PARTIAL — a wrapper sets
        # last_telemetry freely, and the frontend type declares all six keys
        # as always-present.
        StepResult(1, "rs_vlm", "answer_question", {"answer": "x"},
                   time_ms=12.0, success=True, load_time_ms=1.0,
                   inference_time_ms=11.0, model_was_cached=True,
                   telemetry={"prompt_tokens": 100, "completion_tokens": 20}),
        # A failed step, which never went through model_validate before.
        StepResult(2, "sam", "segment_regions", None, time_ms=3.0,
                   success=False, error="boom", load_time_ms=3.0,
                   inference_time_ms=0.0, model_was_cached=False,
                   started_at_ms=12.0),
    ]

    trace = _build(validation, decision, steps, registry, debug=True)
    ExecutionTrace.model_validate(trace)

    telemetry = trace["pipeline_steps"][0]["telemetry"]
    # Normalized to the full declared shape: absent counters are explicitly
    # null, not missing keys the TS type promised would be there.
    assert set(telemetry) == {
        "prompt_tokens", "completion_tokens", "generation_time_ms",
        "tokens_per_sec", "max_new_tokens", "device",
    }
    assert telemetry["prompt_tokens"] == 100
    assert telemetry["device"] is None

    failed = trace["pipeline_steps"][1]
    assert failed["status"] == "error"
    assert failed["error"] == "boom"


def test_no_registry_reports_unknown_rather_than_registered(validation, decision, step_results):
    """Without a registry there is nothing to observe, so registered/loaded
    must be null — not an optimistic 'registered: true'."""
    trace = TraceBuilder().build(validation, decision, step_results)

    for model in trace["selected_models"]:
        assert model["registered"] is None
        assert model["loaded"] is None
        assert model["vram_gb"] is None


def test_sub_millisecond_timings_survive_rounding(validation, decision, registry):
    """Stub models finish in tens of microseconds; rounding to 0.1ms reported
    every one of them as a flat 0.0 and made the timeline useless."""
    steps = [StepResult(1, "rs_vlm", "answer_question", {"answer": "x"},
                        time_ms=0.042, success=True, load_time_ms=0.0,
                        inference_time_ms=0.042, model_was_cached=True)]

    trace = _build(validation, decision, steps, registry)

    assert trace["pipeline_steps"][0]["time_ms"] == 0.042
    assert trace["timings"]["pipeline_steps_ms"] == 0.042
