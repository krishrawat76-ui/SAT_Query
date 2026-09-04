"""
TraceBuilder — Builds the execution trace JSON for every response.

Owner: M3 (Agent/Router Lead)

The execution trace makes the agent's decision-making transparent:
  - What input was received (count, format, modality)
  - What task was detected and why
  - Which models were selected
  - Each pipeline step's timing and status
"""

from app.agent.validator import ValidationResult
from app.agent.router import RoutingDecision
from app.agent.executor import StepResult


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
    ) -> dict:
        """
        Build the complete execution trace.

        Args:
            validation: Result from InputValidator.
            decision: Result from RuleBasedRouter.
            step_results: Results from PipelineExecutor.

        Returns:
            Dict matching the ExecutionTrace API schema.
        """
        return {
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
            "detected_task": decision.task_type.value,
            # RuleBasedRouter is deterministic keyword matching, not a
            # learned model — it has no real confidence score to report.
            "task_confidence": None,
            "reasoning": decision.reasoning,
            "selected_models": [
                {"name": model_name, "version": "1.0"}
                for model_name in decision.models
            ],
            "pipeline_steps": [
                {
                    "step": r.step_num,
                    "model": r.model_name,
                    "action": r.action,
                    "status": "success" if r.success else "error",
                    "time_ms": round(r.time_ms, 1),
                    "error": r.error,
                }
                for r in step_results
            ],
            "total_time_ms": round(
                sum(r.time_ms for r in step_results), 1
            ),
        }
