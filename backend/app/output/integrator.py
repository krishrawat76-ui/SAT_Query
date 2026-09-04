"""
OutputIntegrator — Combines outputs from multi-step pipelines into a single response.

Owner: M3 (Agent/Router Lead)

Takes step results from PipelineExecutor and produces a unified response with:
  - answer (str): Natural language answer
  - confidence (float): Aggregated confidence score
  - evidence (dict): Evidence images and bounding regions
"""

import math

from loguru import logger

from app.agent.executor import StepResult


class OutputIntegrator:
    """
    Combines outputs from multiple pipeline steps into a single API response.

    Strategy:
      - Last step with an "answer" key wins (later steps refine earlier ones)
      - Confidence is averaged across steps that report it
      - Evidence images and regions are accumulated from all steps
    """

    def integrate(
        self,
        step_results: list[StepResult],
        task_type,
        query: str,
        request_id: str = "",
    ) -> dict:
        """
        Integrate pipeline step outputs into a final response.

        Args:
            step_results: List of StepResult from PipelineExecutor.
            task_type: TaskType enum value.
            query: Original user query.
            request_id: Request identifier.

        Returns:
            Dict with keys: answer, confidence, evidence.
        """
        answer = "No answer generated."
        confidence_values: list[float] = []
        evidence = {"images": [], "regions": []}

        for r in step_results:
            if not r.success or not r.output:
                continue

            out = r.output

            # A wrapper is free to return anything from run(); this runs
            # OUTSIDE the executor's try/except, so a non-dict here used to
            # 500 the whole request. For a str, `"answer" in out` is a
            # substring test that can pass and then raise on indexing; for a
            # list, `.get` raises AttributeError. Skip instead — the step
            # already succeeded, it just produced nothing integrable.
            if not isinstance(out, dict):
                logger.warning(
                    f"Step {r.step_num} ({r.model_name}) returned "
                    f"{type(out).__name__}, expected dict — skipping integration."
                )
                continue

            # Answer — later steps override earlier ones
            if "answer" in out:
                answer = out["answer"]

            # Confidence — collect only real, finite scores. A NaN/inf here
            # would serialize as a bare NaN literal, which is invalid JSON and
            # throws in the browser's JSON.parse.
            raw_confidence = out.get("confidence")
            if isinstance(raw_confidence, (int, float)) and not isinstance(raw_confidence, bool):
                if math.isfinite(raw_confidence):
                    confidence_values.append(float(raw_confidence))
                else:
                    logger.warning(
                        f"Step {r.step_num} ({r.model_name}) reported a non-finite "
                        f"confidence ({raw_confidence}) — ignoring."
                    )

            # Evidence images — accumulate
            if isinstance(out.get("evidence_images"), list):
                evidence["images"].extend(out["evidence_images"])

            # Bounding regions — accumulate
            if isinstance(out.get("regions"), list):
                evidence["regions"].extend(out["regions"])

        # Aggregate confidence — None (not a fabricated default) when no
        # step reported a real score, which today is every step, since no
        # real model is loaded.
        confidence = round(sum(confidence_values) / len(confidence_values), 3) if confidence_values else None

        # If pipeline failed entirely, provide a meaningful error answer
        if all(not r.success for r in step_results):
            answer = (
                "Sorry, the analysis pipeline encountered an error. "
                "Please try again or use a different image/query."
            )
            confidence = None

        return {
            "answer": answer,
            "confidence": confidence,
            "evidence": evidence,
        }
