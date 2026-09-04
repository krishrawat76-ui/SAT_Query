"""
Tests for the executor's timing split and telemetry capture.

Timing assertions use lower bounds only — upper bounds are flaky under CI
load and prove nothing useful here.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.agent.executor import PipelineExecutor

LOAD_DELAY = 0.03
RUN_DELAY = 0.03
DELAY_MS_FLOOR = 25  # generous lower bound for a 30ms sleep


def _pipeline(*models):
    return [
        {"step": i + 1, "model": m, "action": f"action_{i + 1}"}
        for i, m in enumerate(models)
    ]


def test_load_and_inference_are_measured_separately(fake_model_factory, fake_registry_factory):
    """The whole point: a cold model load must not be reported as inference
    cost. With rs_vlm at 5.5 GB, loading dominates the first step entirely."""
    model = fake_model_factory(run_delay=RUN_DELAY)
    registry = fake_registry_factory({"m": model}, load_delay=LOAD_DELAY)

    results = PipelineExecutor(registry).execute(_pipeline("m"), [], "q")

    step = results[0]
    assert step.success
    assert step.load_time_ms >= DELAY_MS_FLOOR
    assert step.inference_time_ms >= DELAY_MS_FLOOR
    # time_ms keeps its original meaning: the whole step.
    assert step.time_ms == step.load_time_ms + step.inference_time_ms


def test_second_use_of_same_model_is_cached(fake_model_factory, fake_registry_factory):
    model = fake_model_factory()
    registry = fake_registry_factory({"m": model}, load_delay=LOAD_DELAY)

    results = PipelineExecutor(registry).execute(_pipeline("m", "m"), [], "q")

    assert results[0].model_was_cached is False
    assert results[1].model_was_cached is True
    # The cached step should not have paid the load cost.
    assert results[1].load_time_ms < DELAY_MS_FLOOR


def test_started_at_offsets_increase_across_steps(fake_model_factory, fake_registry_factory):
    model = fake_model_factory(run_delay=RUN_DELAY)
    registry = fake_registry_factory({"m": model})

    results = PipelineExecutor(registry).execute(_pipeline("m", "m"), [], "q")

    assert results[0].started_at_ms == 0.0 or results[0].started_at_ms < 5
    assert results[1].started_at_ms >= DELAY_MS_FLOOR


def test_failure_during_inference_is_distinguishable(fake_model_factory, fake_registry_factory):
    model = fake_model_factory(raises=RuntimeError("inference boom"))
    registry = fake_registry_factory({"m": model}, load_delay=LOAD_DELAY)

    results = PipelineExecutor(registry).execute(_pipeline("m"), [], "q")

    step = results[0]
    assert step.success is False
    assert "inference boom" in step.error
    # Load completed, inference did not.
    assert step.load_time_ms >= DELAY_MS_FLOOR
    assert step.inference_time_ms == 0.0


def test_failure_during_load_reports_no_inference_time(fake_model_factory, fake_registry_factory):
    """The point of the split on the error path: a step that died while
    loading must still report the load time it burned, so it's
    distinguishable from one that died instantly. Without `load_delay` the
    assertion below is vacuous — `inference_time_ms` is initialized to 0.0
    before the raise, so it would pass even if nothing were measured."""
    registry = fake_registry_factory(
        {"m": fake_model_factory()},
        load_delay=LOAD_DELAY,
        load_raises=RuntimeError("load boom"),
    )

    results = PipelineExecutor(registry).execute(_pipeline("m"), [], "q")

    step = results[0]
    assert step.success is False
    assert "load boom" in step.error
    assert step.load_time_ms >= DELAY_MS_FLOOR
    assert step.inference_time_ms == 0.0
    # The error path must keep the same invariant as the success path.
    assert step.time_ms == step.load_time_ms + step.inference_time_ms


def test_pipeline_stops_after_a_failure(fake_model_factory, fake_registry_factory):
    bad = fake_model_factory(raises=RuntimeError("boom"))
    good = fake_model_factory()
    registry = fake_registry_factory({"bad": bad, "good": good})

    results = PipelineExecutor(registry).execute(_pipeline("bad", "good"), [], "q")

    assert len(results) == 1
    assert good.calls == []


def test_model_telemetry_is_captured(fake_model_factory, fake_registry_factory):
    telemetry = {"prompt_tokens": 100, "completion_tokens": 20, "tokens_per_sec": 12.5}
    registry = fake_registry_factory({"m": fake_model_factory(telemetry=telemetry)})

    results = PipelineExecutor(registry).execute(_pipeline("m"), [], "q")

    assert results[0].telemetry == telemetry


def test_model_without_telemetry_reports_none(fake_model_factory, fake_registry_factory):
    registry = fake_registry_factory({"m": fake_model_factory()})

    results = PipelineExecutor(registry).execute(_pipeline("m"), [], "q")

    assert results[0].telemetry is None


def test_stale_telemetry_is_not_inherited_by_a_later_step(fake_model_factory, fake_registry_factory):
    """Regression guard: the executor clears last_telemetry before each run,
    so a step whose model reports nothing cannot silently display the
    previous step's numbers as its own."""
    class ReportsOnce(fake_model_factory):
        def __init__(self):
            super().__init__()
            self._reported = False

        def run(self, action, context):
            out = super().run(action, context)
            if not self._reported:
                self.last_telemetry = {"prompt_tokens": 42}
                self._reported = True
            return out

    model = ReportsOnce()
    registry = fake_registry_factory({"m": model})

    results = PipelineExecutor(registry).execute(_pipeline("m", "m"), [], "q")

    assert results[0].telemetry == {"prompt_tokens": 42}
    assert results[1].telemetry is None


def test_intermediate_outputs_still_flow_between_steps(fake_model_factory, fake_registry_factory):
    """Telemetry changes must not disturb the existing context hand-off."""
    seen = {}

    class Recorder(fake_model_factory):
        def run(self, action, context):
            seen[action] = dict(context["intermediate"])
            return super().run(action, context)

    registry = fake_registry_factory({"m": Recorder()})
    PipelineExecutor(registry).execute(_pipeline("m", "m"), [], "q")

    assert seen["action_1"] == {}
    assert "step_1" in seen["action_2"]
