"""
OutputIntegrator — Combines outputs from multi-step pipelines into a single response.

Owner: M3 (Agent/Router Lead)

Takes step results from PipelineExecutor and produces a unified response with:
  - answer (str): Natural language answer
  - confidence (float): Aggregated confidence score
  - evidence (dict): Evidence images and bounding regions
"""

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

            # Answer — later steps override earlier ones
            if "answer" in out:
                answer = out["answer"]

            # Confidence — collect only real (non-None) scores for averaging.
            if out.get("confidence") is not None:
                confidence_values.append(out["confidence"])

            # Evidence images — accumulate
            if "evidence_images" in out:
                evidence["images"].extend(out["evidence_images"])

            # Bounding regions — accumulate
            if "regions" in out:
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
