"""
Records planned pipeline steps without loading model weights.

Used when specialist CV/VLM weights are not available so the API still
returns an honest answer ("Model not available") and a full execution
trace for the Debug panel (which model was selected, what query/images
would have been passed, status: model not loaded).
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any, Optional

from loguru import logger

from app.agent.executor import StepResult


class UnavailableModelExecutor:
    """Emit one StepResult per planned step without calling ModelRegistry.get()."""

    def execute(
        self,
        pipeline: list[dict],
        image_paths: list[str],
        query: str,
        request_id: str = "demo",
        intent_decomposition: Optional[list[dict]] = None,
    ) -> list[StepResult]:
        results: list[StepResult] = []
        image_names = [Path(p).name for p in image_paths]
        intents = intent_decomposition or []
        pipeline_t0 = time.perf_counter()

        for step in pipeline:
            step_num = step["step"]
            model_name = step["model"]
            action = step["action"]
            task_id = step.get("task_id")
            shiven_task = step.get("shiven_task")

            intent = next(
                (i for i in intents if i.get("task_id") == task_id),
                None,
            )
            query_for_model = (
                (intent.get("query") if intent else None) or query
            )

            started_at_ms = (time.perf_counter() - pipeline_t0) * 1000
            logger.info(
                f"[{request_id}] Step {step_num}: {model_name}.{action} "
                f"— skipped (model not loaded)"
            )

            output: dict[str, Any] = {
                "answer": "Model not available",
                "confidence": None,
                "status": "model_not_loaded",
                "model": model_name,
                "action": action,
                "query": query_for_model,
                # Basenames only. `image_paths` used to ride along here and,
                # under ?debug=true, TraceBuilder snapshotted it into
                # payload_snapshot — putting the absolute upload path
                # (/var/folders/.../satquery_xxxx/a.png) in the response body.
                "images": image_names,
                "task_id": task_id,
                "shiven_task": shiven_task,
                "message": (
                    f"Model '{model_name}' is registered in the pipeline plan "
                    "but weights are not loaded. Inference was not run."
                ),
            }
            if intent:
                output["intent"] = {
                    "task_id": intent.get("task_id"),
                    "task": intent.get("task"),
                    "target": intent.get("target"),
                    "depends_on": intent.get("depends_on"),
                }

            results.append(
                StepResult(
                    step_num=step_num,
                    model_name=model_name,
                    action=action,
                    output=output,
                    time_ms=0.0,
                    success=False,
                    error="Model not loaded",
                    load_time_ms=0.0,
                    inference_time_ms=0.0,
                    model_was_cached=False,
                    started_at_ms=started_at_ms,
                    telemetry=None,
                )
            )

        return results
