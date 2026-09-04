"""
Grounding Model Stubs — Placeholder for Grounding DINO + SAM.

Owner: M4 (ML Pipelines Lead)
Status: STUB — returns 'Model output not available'.

Replace with real Grounding DINO + SAM 2.1 implementation.
"""

import numpy as np
from loguru import logger

from app.models.base import BaseModelWrapper
from app.output.evidence import overlay_bboxes
from app.utils.synthesize import synthesize_answer


class GroundingModel(BaseModelWrapper):
    """
    Stub: Grounding DINO text-guided object detection.

    TODO (M4): Replace with actual Grounding DINO inference.
    """

    def run(self, action: str, context: dict) -> dict:
        image_path = context["images"][0]
        query = context["query"]
        target = self._extract_target(query)

        logger.info(f"[STUB] Grounding DINO detecting: '{target}'")

        # No model available — return empty detections
        boxes = []
        scores = []
        labels = []

        return {
            "type": "detections",
            "boxes": boxes,
            "scores": scores,
            "labels": labels,
            "target": target,
        }

    def _extract_target(self, query: str) -> str:
        """Extract the grounding target from the query."""
        for prefix in [
            "highlight the ", "show the ", "locate the ",
            "find the ", "where is the ", "identify the ",
            "show me the ", "point out the ", "detect the ",
        ]:
            if query.lower().startswith(prefix):
                return query[len(prefix):].rstrip("?. ")
        return query.rstrip("?. ")


class SegmentationModel(BaseModelWrapper):
    """
    Stub: SAM 2.1 segmentation model.

    TODO (M4): Replace with actual SAM 2.1 Hiera-Tiny inference.
    """

    def run(self, action: str, context: dict) -> dict:
        image_path = context["images"][0]
        detections = context["intermediate"]["step_1"]
        request_id = context.get("request_id", "demo")

        target = detections.get("target", "object")
        boxes = detections.get("boxes", [])
        scores = detections.get("scores", [])

        logger.info(f"[STUB] SAM segmenting {len(boxes)} regions")

        # Generate evidence overlay using bbox helper
        overlay_url = overlay_bboxes(
            image_path, boxes, [target] * len(boxes), scores, request_id
        )

        answer = synthesize_answer(context["query"], [image_path], "grounding", target=target)
        return {
            "answer": answer,
            "confidence": None,
            "evidence_images": [],
            "regions": [],
        }
