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
from typing import Any, Optional

from loguru import logger

from app.agent.router import ROUTER_VERSION, RoutingDecision
from app.agent.validator import ValidationResult
from app.agent.executor import StepResult
from app.output.sanitize import json_safe, sanitize_payload


# Every key `ModelTelemetry` (schemas.py) and the TS mirror declare. A wrapper
# sets `last_telemetry` freely, so without normalizing here a partial dict
# would ship keys the frontend type promises are always present — the one
# place the TS contract could actually lie about shape rather than value.
_TELEMETRY_KEYS = (
    "prompt_tokens",
    "completion_tokens",
    "generation_time_ms",
    "tokens_per_sec",
    "max_new_tokens",
    "device",
    # Multi-device (optional; null when local / unavailable)
    "execution",
    "node_id",
    "runtime",
    "model",
    "request_id",
    "error_code",
    "latency_sec",
)


def _telemetry(raw: Optional[dict]) -> Optional[dict]:
    """Normalize a wrapper-supplied telemetry dict to the declared shape.

    Missing keys become None (absent means unmeasured, which is null, not a
    missing field). Unknown keys are dropped rather than passed through, so a
    wrapper cannot silently extend the wire contract.

    `last_telemetry` is a plain attribute any wrapper may assign anything to.
    A non-dict used to raise AttributeError here and take down trace building
    for an otherwise-successful request; values are also passed through
    json_safe so a non-finite tokens_per_sec cannot reach the renderer.
    """
    if not raw:
        return None
    if not isinstance(raw, dict):
        logger.warning(
            f"Ignoring non-dict telemetry from a wrapper: {type(raw).__name__}"
        )
        return None
    return {key: json_safe(raw.get(key)) for key in _TELEMETRY_KEYS}


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
        spatial: Optional[dict] = None,
        land_cover_check: Optional[dict] = None,
        remote_dispatch: Optional[dict] = None,
        fallback_strategy: Optional[dict] = None,
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
            spatial: Ground-overlap facts from preflight (bbox IoU, whether the
                check was enforced, per-image bbox source). Empty for a
                single-image request, which has nothing to overlap.
            land_cover_check: Fast land-cover pre-check outcome (threshold,
                breakdown, land_pct, whether it passed) — None when no
                optical image was present to check. See
                app/agent/land_cover_check.py.
            remote_dispatch: Whether the remote VLM was actually dispatched,
                and to which paired node — None only when the caller has
                nothing to report (mirrors spatial/land_cover_check).
            fallback_strategy: Whether a fallback response was used instead
                of the model path, and why.

        Returns:
            Dict matching the ExecutionTrace API schema.
        """
        stage_ms = stage_ms or {}
        metadata = metadata or {}

        # Microsecond resolution. perf_counter measures far finer than 0.1ms,
        # and stub models routinely complete in tens of microseconds — rounding
        # to 1 decimal collapsed all of them to a flat 0.0 and made the debug
        # timeline useless for exactly the steps it was meant to explain.
        pipeline_steps_ms = round(sum(r.time_ms for r in step_results), 3)

        measured = sum(
            stage_ms.get(k, 0.0)
            for k in ("upload_ms", "validation_ms", "routing_ms", "execution_ms", "integration_ms")
        )

        # Built before the total is taken, deliberately: under ?debug=true the
        # per-step payload sanitizing here is the most expensive non-inference
        # work in the request. Computing total_time_ms at the top of this
        # method (as it used to be) excluded that cost entirely, so `other_ms`
        # could never account for trace building even though the schema says
        # it does.
        pipeline_steps = [self._step(r, debug=debug) for r in step_results]
        selected_models = self._selected_models(decision, registry)
        input_composition = self._input_composition(validation, metadata, spatial)

        # Real handler wall clock when the route provided a start marker;
        # otherwise fall back to the step sum so this stays usable standalone.
        if request_t0 is not None:
            total_time_ms = round((time.perf_counter() - request_t0) * 1000, 3)
        else:
            total_time_ms = pipeline_steps_ms

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
                # Optional hardening fields — ignored by older frontend consumers.
                "status": getattr(
                    getattr(validation, "status", None), "value", None
                ),
                "error_codes": list(getattr(validation, "error_codes", []) or []),
                "footprint_check": getattr(validation, "footprint_check", None),
                "requirements": getattr(validation, "requirements", None),
            },
            "input_composition": input_composition,
            "detected_task": decision.task_type.value,
            # RuleBasedRouter is deterministic keyword matching, not a
            # learned model — it has no real confidence score to report.
            # Shiven LLM task confidences live on intent_decomposition entries.
            "task_confidence": None,
            "reasoning": decision.reasoning,
            "router_metadata": {
                "router_type": getattr(
                    decision, "router_type", None
                ) or "rule_based_keyword",
                "router_version": getattr(
                    decision, "router_version", None
                ) or ROUTER_VERSION,
                "rule_id": decision.rule_id,
                "matched_rule": decision.reasoning,
                "matched_keywords": decision.matched_keywords,
                # Shiven adapter sets fallback_used explicitly. Legacy
                # RuleBasedRouter leaves it None → keep default_vqa heuristic.
                "fallback_used": (
                    decision.fallback_used
                    if getattr(decision, "fallback_used", None) is not None
                    else decision.rule_id == "default_vqa"
                ),
                "routing_time_ms": round(stage_ms.get("routing_ms", 0.0), 2),
                "planner_type": getattr(decision, "planner_type", None),
                "planning_time_ms": getattr(decision, "planning_time_ms", None),
                "prompt_tokens": None,
                "completion_tokens": None,
                "tokens_per_sec": None,
                "intent_decomposition": getattr(
                    decision, "intent_decomposition", None
                ),
                "planner_raw_output": getattr(
                    decision, "planner_raw_output", None
                ),
            },
            "selected_models": selected_models,
            "pipeline_steps": pipeline_steps,
            "timings": {
                # 3 decimals throughout — see the pipeline_steps_ms note above.
                "upload_ms": round(stage_ms.get("upload_ms", 0.0), 3),
                "validation_ms": round(stage_ms.get("validation_ms", 0.0), 3),
                "routing_ms": round(stage_ms.get("routing_ms", 0.0), 3),
                "preflight_ms": round(stage_ms.get("preflight_ms", 0.0), 3),
                "execution_ms": round(stage_ms.get("execution_ms", 0.0), 3),
                "integration_ms": round(stage_ms.get("integration_ms", 0.0), 3),
                "pipeline_steps_ms": pipeline_steps_ms,
                # Clamped: stages are measured sequentially and cannot
                # legitimately exceed the total, but float noise shouldn't
                # surface as -0.0001.
                "other_ms": round(max(0.0, total_time_ms - measured), 3),
                "land_cover_ms": round(stage_ms.get("land_cover_ms", 0.0), 3),
            },
            "total_time_ms": total_time_ms,
            # None on every request with no optical image to check (nothing
            # for this endpoint to report) — never a fabricated all-zero
            # breakdown or a pass/fail guess.
            "land_cover_check": land_cover_check,
            "remote_dispatch": remote_dispatch,
            "fallback_strategy": fallback_strategy,
        }

    def _selected_models(self, decision: RoutingDecision, registry) -> list[dict]:
        """Per-model entries carrying real registry state.

        Replaces the previous hardcoded {"version": "1.0"} — the registry has
        no version field, so that number was fabricated for every model.
        """
        models = []
        for name in decision.models:
            steps = [s for s in decision.pipeline if s.get("model") == name]
            # With no registry there is nothing to observe, so every field
            # stays None rather than defaulting to an optimistic
            # "registered: true, loaded: false" — asserting a model IS
            # registered without checking is the same fabrication this whole
            # trace exists to avoid.
            info = registry.describe(name) if registry is not None else {}
            models.append({
                "name": name,
                "actions": [s["action"] for s in steps],
                "steps": [s["step"] for s in steps],
                "registered": info.get("registered"),
                "loaded": info.get("loaded"),
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
            # 3 decimals: sub-millisecond steps are the norm for stub models,
            # and rounding to 0.1ms reported all of them as a flat 0.0.
            "time_ms": round(r.time_ms, 3),
            "error": r.error,
            "load_time_ms": round(r.load_time_ms, 3),
            "inference_time_ms": round(r.inference_time_ms, 3),
            "model_was_cached": r.model_was_cached,
            "started_at_ms": round(r.started_at_ms, 3),
            "telemetry": _telemetry(r.telemetry),
            "payload_snapshot": snapshot,
            "payload_bytes": payload_bytes,
            # The executor is a strictly linear loop; synthesizing [n-1]
            # would imply a dependency graph that does not exist.
            "depends_on": None,
        }

    def _input_composition(
        self,
        validation: ValidationResult,
        metadata: dict,
        spatial: Optional[dict] = None,
    ) -> dict:
        """Per-image detail, entirely from data the validator already collected."""
        dates = metadata.get("dates", []) or []
        images = []
        total_pixels = 0
        total_size_mb = 0.0

        for position, f in enumerate(validation.format_info):
            # Index into the original upload list, not into format_info —
            # entries are skipped for images that failed a per-image check, so
            # a positional zip would label a surviving image with a skipped
            # one's modality/date. Falls back to position for callers whose
            # format_info predates the index field.
            i = f.get("index", position)
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
            # Ground-overlap facts from preflight. `enforced: false` means the
            # rasters carry no real georeferencing, so extract_bbox synthesized
            # their footprints from a filename hash and no overlap claim can be
            # made — `bbox_iou` there describes invented boxes, not ground.
            "spatial": json_safe(spatial) if spatial else None,
        }
