"""
PipelineExecutor — Runs pipeline steps from a RoutingDecision.

Walks through each step in the pipeline, loads the appropriate model via
ModelRegistry, calls model.run(action, context), and collects results.

Intermediate outputs from earlier steps are passed forward via context["intermediate"].
"""

import time
from dataclasses import dataclass, field
from typing import Any, Optional

from loguru import logger


@dataclass
class StepResult:
    """Result of a single pipeline step."""
    step_num: int
    model_name: str
    action: str
    output: Optional[Any]
    # Total wall clock for the step (load + inference), unchanged in meaning
    # so existing consumers keep reading the same number.
    time_ms: float
    success: bool
    error: Optional[str] = None

    # ── Telemetry (Phase 4) ──
    # Time inside ModelRegistry.get() — cold weight loading. Previously this
    # was folded into time_ms and misreported as inference cost, which for a
    # 5.5 GB model dominates the step entirely on first use.
    load_time_ms: float = 0.0
    # Time inside model.run() only.
    inference_time_ms: float = 0.0
    # Whether the registry already held the instance. Explains load spikes.
    model_was_cached: bool = True
    # Offset from pipeline start, so a waterfall can show real gaps between
    # steps rather than assuming they are contiguous.
    started_at_ms: float = 0.0
    # Whatever the wrapper reported via `last_telemetry`, or None.
    telemetry: Optional[dict] = None


class PipelineExecutor:
    """
    Executes a multi-step model pipeline.

    Each step:
      1. Load model from registry (auto VRAM management)
      2. Call model.run(action, context)
      3. Store output in context["intermediate"] for next step
      4. Record timing and success/failure

    On failure: logs the error, records it in StepResult, and stops the pipeline.
    """

    def __init__(self, registry):
        """
        Args:
            registry: ModelRegistry instance for loading/unloading models.
        """
        self.registry = registry

    def execute(
        self,
        pipeline: list[dict],
        image_paths: list[str],
        query: str,
        request_id: str = "demo",
    ) -> list[StepResult]:
        """
        Execute the full pipeline.

        Args:
            pipeline: List of step dicts from RoutingDecision.pipeline.
                      Each dict has: step (int), model (str), action (str).
            image_paths: List of uploaded image file paths.
            query: User's natural language query.
            request_id: Unique request identifier for evidence file naming.

        Returns:
            List of StepResult objects.
        """
        results: list[StepResult] = []
        context = {
            "images": image_paths,
            "query": query,
            "request_id": request_id,
            "intermediate": {},
        }

        # perf_counter, not time(): monotonic, so an NTP adjustment mid-request
        # can't produce a negative duration.
        pipeline_t0 = time.perf_counter()

        for step in pipeline:
            step_num = step["step"]
            model_name = step["model"]
            action = step["action"]

            logger.info(
                f"[{request_id}] Step {step_num}: {model_name}.{action}"
            )

            started_at_ms = (time.perf_counter() - pipeline_t0) * 1000
            # Read BEFORE get() — this is what makes load_time_ms
            # interpretable as "cold load" vs "already resident".
            was_cached = model_name in self.registry.list_loaded()

            load_ms = 0.0
            infer_ms = 0.0
            try:
                load_start = time.perf_counter()
                try:
                    model = self.registry.get(model_name)
                finally:
                    # In a `finally` so a load that RAISES still records the
                    # time it burned. Assigning only on the success path meant
                    # a failed 30s model load reported load_time_ms: 0.0 —
                    # indistinguishable from an instant failure, despite the
                    # comment below promising exactly that distinction.
                    load_ms = (time.perf_counter() - load_start) * 1000

                # Clear any telemetry left from a previous run before calling
                # this one, so a wrapper that fails to report can't silently
                # inherit another step's numbers.
                if hasattr(model, "last_telemetry"):
                    model.last_telemetry = None

                infer_start = time.perf_counter()
                output = model.run(action=action, context=context)
                infer_ms = (time.perf_counter() - infer_start) * 1000

                # Store output for downstream steps
                context["intermediate"][f"step_{step_num}"] = output

                results.append(StepResult(
                    step_num=step_num,
                    model_name=model_name,
                    action=action,
                    output=output,
                    time_ms=load_ms + infer_ms,
                    success=True,
                    load_time_ms=load_ms,
                    inference_time_ms=infer_ms,
                    model_was_cached=was_cached,
                    started_at_ms=started_at_ms,
                    telemetry=getattr(model, "last_telemetry", None),
                ))

                logger.info(
                    f"[{request_id}] Step {step_num} complete "
                    f"({load_ms + infer_ms:.0f}ms — load {load_ms:.0f}ms, infer {infer_ms:.0f}ms)"
                )

            except Exception as e:
                error_msg = str(e)

                logger.error(
                    f"[{request_id}] Step {step_num} FAILED: {error_msg}"
                )

                # load_ms/infer_ms carry however far we got, so a step that
                # died during loading (inference_time_ms == 0) is
                # distinguishable from one that died during inference.
                results.append(StepResult(
                    step_num=step_num,
                    model_name=model_name,
                    action=action,
                    output=None,
                    time_ms=load_ms + infer_ms,
                    success=False,
                    error=error_msg,
                    load_time_ms=load_ms,
                    inference_time_ms=infer_ms,
                    model_was_cached=was_cached,
                    started_at_ms=started_at_ms,
                ))

                # Stop pipeline on failure
                break

        return results
