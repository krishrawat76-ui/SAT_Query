"""
RuleBasedRouter — Keyword + input analysis based task classifier.

Owner: M3 (Agent/Router Lead)

Uses TWO signals to classify the task:
  1. Input analysis — How many images? What modality?
  2. Query keywords — What words suggest which task?

Task Classification Matrix:
  | Images | Modalities    | Keywords                              | → Task            |
  |--------|---------------|---------------------------------------|--------------------|
  | 1      | Any           | "highlight", "show", "locate", ...    | GROUNDING          |
  | 1      | Any           | "describe", "caption", "summarize"    | CAPTION            |
  | 1      | Any           | Any other question                    | VQA                |
  | 2      | Same          | Specific question ("has X increased?")| CHANGE_VQA         |
  | 2      | Same          | General ("what changed?")             | CHANGE_DETECTION   |
  | 2      | optical+sar   | Any                                   | OPTICAL_SAR        |
"""

from enum import Enum
from dataclasses import dataclass, field


class TaskType(Enum):
    """All supported task types for the agentic pipeline."""
    VQA = "vqa"
    CAPTION = "caption"
    GROUNDING = "grounding"
    CHANGE_DETECTION = "change_detection"
    CHANGE_VQA = "change_vqa"
    OPTICAL_SAR = "optical_sar"


@dataclass
class RoutingDecision:
    """Output of the router — what task, which models, pipeline steps.

    No `confidence` field: this is a deterministic keyword/rule-based
    classifier, not a learned model — it has no real notion of "how sure"
    it is about a match, so it doesn't fabricate one. `reasoning` carries
    the actual justification for the decision instead.
    """
    task_type: TaskType
    models: list[str]
    pipeline: list[dict]
    reasoning: str


class RuleBasedRouter:
    """
    Rule-based router for SatQuery AI.

    Deterministic task classifier using keyword matching + input structure.
    Zero VRAM — runs on CPU. Perfect for POC demo.
    """

    # --- Keyword dictionaries ---

    GROUNDING_KW = [
        "highlight", "show me", "locate", "find", "where is",
        "mark", "segment", "outline", "box", "identify region",
        "point out", "detect", "show the", "circle", "indicate",
    ]

    CAPTION_KW = [
        "describe", "caption", "summarize", "overview",
        "tell me about", "what does this show", "explain this",
        "what is in this", "give me a description", "summary",
    ]

    CHANGE_KW = [
        "change", "differ", "before", "after", "increase",
        "decrease", "grew", "expand", "transform", "evolve",
        "develop", "built", "construct", "demolish", "deforest",
        "urban", "sprawl", "flood", "recede",
    ]

    SPECIFIC_QUESTION_PREFIXES = [
        "has ", "is ", "did ", "does ", "how many", "how much",
        "was ", "were ", "are ", "have ", "can you tell",
    ]

    def route(self, query: str, input_info: dict) -> RoutingDecision:
        """
        Classify a user query + input into a task type.

        Args:
            query: Natural language question from the user.
            input_info: Dict with keys:
                - num_images (int)
                - modalities (list[str]): e.g. ["optical"], ["optical", "sar"]
                - is_temporal (bool, optional)
                - is_cross_modal (bool, optional)

        Returns:
            RoutingDecision with task_type, models, pipeline, reasoning.
        """
        q = query.lower().strip()
        n = input_info["num_images"]
        mods = input_info.get("modalities", ["optical"])
        is_cross = input_info.get("is_cross_modal", False)

        # ── Text-only (no images) → conversational response, no image pipeline ──
        if n == 0:
            return RoutingDecision(
                task_type=TaskType.VQA,
                models=["rs_vlm"],
                pipeline=[
                    {"step": 1, "model": "rs_vlm", "action": "answer_question"},
                ],
                reasoning="No images attached → conversational response, no image pipeline run.",
            )

        # ── Cross-modal → always Optical-SAR ──
        if is_cross or (n == 2 and set(mods) == {"optical", "sar"}):
            return RoutingDecision(
                task_type=TaskType.OPTICAL_SAR,
                models=["optical_sar_fusion", "rs_vlm"],
                pipeline=[
                    {"step": 1, "model": "optical_sar_fusion", "action": "fuse_modalities"},
                    {"step": 2, "model": "rs_vlm", "action": "analyze_fused"},
                ],
                reasoning="Cross-modal input detected (optical + SAR) → Optical-SAR fusion pipeline",
            )

        # ── Bi-temporal (2 images, same modality) ──
        if n == 2:
            is_specific = any(q.startswith(w) for w in self.SPECIFIC_QUESTION_PREFIXES)
            if (is_specific or "?" in q) and q.strip("?") != "what changed" and self._has_kw(q, self.CHANGE_KW):
                return RoutingDecision(
                    task_type=TaskType.CHANGE_VQA,
                    models=["change_detection", "change_vqa"],
                    pipeline=[
                        {"step": 1, "model": "change_detection", "action": "generate_change_map"},
                        {"step": 2, "model": "change_vqa", "action": "answer_change_question"},
                    ],
                    reasoning="Bi-temporal input + specific change question → Change VQA pipeline",
                )
            return RoutingDecision(
                task_type=TaskType.CHANGE_DETECTION,
                models=["change_detection", "rs_vlm"],
                pipeline=[
                    {"step": 1, "model": "change_detection", "action": "generate_change_map"},
                    {"step": 2, "model": "rs_vlm", "action": "describe_changes"},
                ],
                reasoning="Bi-temporal input + general query → Change Detection pipeline",
            )

        # ── Single image: Grounding ──
        if self._has_kw(q, self.GROUNDING_KW):
            return RoutingDecision(
                task_type=TaskType.GROUNDING,
                models=["grounding_dino", "sam"],
                pipeline=[
                    {"step": 1, "model": "grounding_dino", "action": "detect_regions"},
                    {"step": 2, "model": "sam", "action": "segment_regions"},
                ],
                reasoning="Grounding keywords detected in query → Grounding pipeline (DINO + SAM)",
            )

        # ── Single image: Caption ──
        if self._has_kw(q, self.CAPTION_KW):
            return RoutingDecision(
                task_type=TaskType.CAPTION,
                models=["rs_vlm"],
                pipeline=[
                    {"step": 1, "model": "rs_vlm", "action": "generate_caption"},
                ],
                reasoning="Caption/description keywords detected → Caption mode via VLM",
            )

        # ── Default: VQA ──
        return RoutingDecision(
            task_type=TaskType.VQA,
            models=["rs_vlm"],
            pipeline=[
                {"step": 1, "model": "rs_vlm", "action": "answer_question"},
            ],
            reasoning="General question → Visual Question Answering via VLM",
        )

    def _has_kw(self, query: str, keywords: list[str]) -> bool:
        """Check if any keyword appears in the query."""
        return any(kw in query for kw in keywords)
