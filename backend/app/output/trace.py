"""
TraceBuilder — Builds the execution trace JSON for every response.

Owner: M3 (Agent/Router Lead)

The execution trace makes the agent's decision-making transparent:
  - What input was received (count, format, modality)
  - What task was detected and why
  - Which models were selected, and their real registry state
  - Each pipeline step's timing (load vs. inference), status, and payload

Everything here is measured or read from real state. Where a value genuinely
does not exist — a confidence score from a rule-based router, a token count
from a model that never ran, a source CRS the backend never parses — the
field is None rather than a plausible-looking placeholder.
"""

import time
from typing import Optional

from app.agent.router import ROUTER_VERSION, RoutingDecision
from app.agent.validator import ValidationResult
from app.agent.executor import StepResult
from app.output.sanitize import sanitize_payload


def _selection_reason(model_name: str, decision: RoutingDecision) -> str:
    """Compose a selection reason purely from data the router produced.

    Deliberately mechanical: the router's own `reasoning` string plus the
    concrete actions this model was assigned. No hand-written per-model
    justification prose — the rule-based router never made those claims, and
    inventing them here is exactly the kind of fabrication this trace exists
    to avoid.
    """
    steps = [s for s in decision.pipeline if s.get("model") == model_name]
    if steps:
        actions = ", ".join(f"step {s['step']}: {s['action']}" for s in steps)
        assigned = f"to run {actions}"
    else:
        assigned = "but was assigned no pipeline step"
    return (
        f"Selected for task '{decision.task_type.value}' {assigned}. "
        f"Router rule [{decision.rule_id}]: {decision.reasoning}"
    )


class TraceBuilder:
    """
    Assembles an execution trace dict from validation, routing, and execution results.

    The trace is included in every API response so the user (and judges) can see
    exactly how the agent reasoned about their query.
    """

    def build(
        self,
        validation: ValidationResult,
        decision: RoutingDecision,
        step_results: list[StepResult],
        *,
        registry=None,
        metadata: Optional[dict] = None,
        request_id: Optional[str] = None,
        stage_ms: Optional[dict] = None,
        request_t0: Optional[float] = None,
        debug: bool = False,
    ) -> dict:
        """
        Build the complete execution trace.

        Args:
            validation: Result from InputValidator.
            decision: Result from RuleBasedRouter.
            step_results: Results from PipelineExecutor.
            registry: ModelRegistry, for real per-model state. Optional so
                existing callers and tests keep working without one.
            metadata: The parsed request metadata (modalities, dates).
            request_id: Correlates this trace with the server logs.
            stage_ms: Measured per-stage durations from the route handler.
            request_t0: perf_counter() taken at the top of the handler, used
                for true wall-clock latency.
            debug: When True, include sanitized payload snapshots per step.

        Returns:
            Dict matching the ExecutionTrace API schema.
        """
        stage_ms = stage_ms or {}
        metadata = metadata or {}

        pipeline_steps_ms = round(sum(r.time_ms for r in step_results), 1)
        # Real handler wall clock when the route provided a start marker;
        # otherwise fall back to the step sum so this stays usable standalone.
        if request_t0 is not None:
            total_time_ms = round((time.perf_counter() - request_t0) * 1000, 1)
        else:
            total_time_ms = pipeline_steps_ms

        measured = sum(
            stage_ms.get(k, 0.0)
            for k in ("upload_ms", "validation_ms", "routing_ms", "execution_ms", "integration_ms")
        )

        return {
            "request_id": request_id,
            "debug": debug,
            "input_validation": {
                "image_count": validation.num_images,
                "format": [
                    f.get("format", "unknown") for f in validation.format_info
                ],
                "modality": validation.modalities,
                "temporal": validation.is_temporal,
                "cross_modal": validation.is_cross_modal,
                "compatible": validation.is_valid,
                "warnings": validation.warnings,
            },
            "input_composition": self._input_composition(validation, metadata),
            "detected_task": decision.task_type.value,
            # RuleBasedRouter is deterministic keyword matching, not a
            # learned model — it has no real confidence score to report.
            "task_confidence": None,
            "reasoning": decision.reasoning,
            "router_metadata": {
                "router_type": "rule_based_keyword",
                "router_version": ROUTER_VERSION,
                "rule_id": decision.rule_id,
                "matched_rule": decision.reasoning,
                "matched_keywords": decision.matched_keywords,
                "fallback_used": decision.rule_id == "default_vqa",
                "routing_time_ms": round(stage_ms.get("routing_ms", 0.0), 2),
                # Null by construction: this router has no language model.
                # Present so an LLM planner can fill them in without a
                # breaking schema change.
                "planner_type": None,
                "planning_time_ms": None,
                "prompt_tokens": None,
                "completion_tokens": None,
                "tokens_per_sec": None,
                "intent_decomposition": None,
                "planner_raw_output": None,
            },
            "selected_models": self._selected_models(decision, registry),
            "pipeline_steps": [
                self._step(r, debug=debug) for r in step_results
            ],
            "timings": {
                "upload_ms": round(stage_ms.get("upload_ms", 0.0), 1),
                "validation_ms": round(stage_ms.get("validation_ms", 0.0), 1),
                "routing_ms": round(stage_ms.get("routing_ms", 0.0), 1),
                "execution_ms": round(stage_ms.get("execution_ms", 0.0), 1),
                "integration_ms": round(stage_ms.get("integration_ms", 0.0), 1),
                "pipeline_steps_ms": pipeline_steps_ms,
                # Clamped: stages are measured sequentially and cannot
                # legitimately exceed the total, but float noise shouldn't
                # surface as -0.0001.
                "other_ms": round(max(0.0, total_time_ms - measured), 1),
            },
            "total_time_ms": total_time_ms,
        }

    def _selected_models(self, decision: RoutingDecision, registry) -> list[dict]:
        """Per-model entries carrying real registry state.

        Replaces the previous hardcoded {"version": "1.0"} — the registry has
        no version field, so that number was fabricated for every model.
        """
        models = []
        for name in decision.models:
            steps = [s for s in decision.pipeline if s.get("model") == name]
            info = registry.describe(name) if registry is not None else {}
            models.append({
                "name": name,
                "actions": [s["action"] for s in steps],
                "steps": [s["step"] for s in steps],
                "registered": info.get("registered", True),
                "loaded": info.get("loaded", False),
                "vram_gb": info.get("vram_gb"),
                "version": info.get("version"),
                "selection_reason": _selection_reason(name, decision),
            })
        return models

    def _step(self, r: StepResult, *, debug: bool) -> dict:
        """One pipeline step, with its timing split and optional snapshot."""
        snapshot = None
        payload_bytes = None
        if debug:
            snap = sanitize_payload(r.output)
            snapshot = snap["value"]
            payload_bytes = snap["bytes"]

        return {
            "step": r.step_num,
            "model": r.model_name,
            "action": r.action,
            "status": "success" if r.success else "error",
            "time_ms": round(r.time_ms, 1),
            "error": r.error,
            "load_time_ms": round(r.load_time_ms, 1),
            "inference_time_ms": round(r.inference_time_ms, 1),
            "model_was_cached": r.model_was_cached,
            "started_at_ms": round(r.started_at_ms, 1),
            "telemetry": r.telemetry,
            "payload_snapshot": snapshot,
            "payload_bytes": payload_bytes,
            # The executor is a strictly linear loop; synthesizing [n-1]
            # would imply a dependency graph that does not exist.
            "depends_on": None,
        }

    def _input_composition(self, validation: ValidationResult, metadata: dict) -> dict:
        """Per-image detail, entirely from data the validator already collected."""
        dates = metadata.get("dates", []) or []
        images = []
        total_pixels = 0
        total_size_mb = 0.0

        for i, f in enumerate(validation.format_info):
            size = f.get("size") or [0, 0]
            width, height = (int(size[0]), int(size[1])) if len(size) >= 2 else (0, 0)
            total_pixels += width * height
            file_size_mb = float(f.get("file_size_mb", 0.0) or 0.0)
            total_size_mb += file_size_mb

            images.append({
                "filename": f.get("filename", ""),
                "width": width,
                "height": height,
                "bands": int(f.get("bands", 0) or 0),
                "format": f.get("format", "unknown"),
                "file_size_mb": round(file_size_mb, 3),
                # Positional zip, length-guarded: format_info can be shorter
                # than modalities if an image failed a per-image check.
                "modality": (
                    validation.modalities[i] if i < len(validation.modalities) else None
                ),
                "date": dates[i] if i < len(dates) else None,
            })

        return {
            "images": images,
            "total_pixels": total_pixels,
            "total_size_mb": round(total_size_mb, 3),
            "is_temporal": validation.is_temporal,
            "is_cross_modal": validation.is_cross_modal,
            # EPSG is parsed then discarded client-side (geotiffClient.ts);
            # the backend never reads it, so claiming one would be a guess.
            "crs": None,
        }
