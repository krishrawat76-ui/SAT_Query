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
        # Was context["images"][0]: a grounding plan built from query text alone
        # ("highlight the water body") reached here with zero images attached
        # and raised IndexError.
        self.require_images(context, 1, model="grounding_dino", action=action)
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
        images = self.require_images(context, 1, model="sam", action=action)
        image_path = images[0]
        # Was context["intermediate"]["step_1"] followed by .get(): KeyError when
        # step 1 never ran, AttributeError when it returned a str instead of a
        # dict. prior_step() degrades to {} for both.
        detections = self.prior_step(context, 1)
        request_id = context.get("request_id", "demo")

        target = detections.get("target", "object")
        boxes = detections.get("boxes") or []
        scores = detections.get("scores") or []

        logger.info(f"[STUB] SAM segmenting {len(boxes)} regions")

        # The return value used to be assigned and then dropped, so an overlay
        # that failed to render vanished twice over — silently inside
        # overlay_bboxes, then again here. Now it is reported as real evidence,
        # or its absence is recorded.
        # Only when there is something to draw. With zero detections the
        # overlay is a byte-for-byte copy of the input, and offering that as
        # "detected regions" is fabricated evidence — the stub detector returns
        # no boxes, so this is the normal path today.
        evidence_images = []
        if boxes:
            overlay_url = overlay_bboxes(
                image_path, boxes, [target] * len(boxes), scores, request_id
            )
            if overlay_url:
                evidence_images.append({
                    "type": "grounding_overlay",
                    "url": overlay_url,
                    "caption": f"Detected regions for '{target}'",
                })
            else:
                logger.warning(
                    f"SAM had {len(boxes)} boxes but the overlay could not be "
                    "rendered; reporting no evidence rather than a blank URL."
                )

        answer = synthesize_answer(
            context["query"], [image_path], "grounding", target=target
        )
        return {
            "answer": answer,
            "confidence": None,
            "evidence_images": evidence_images,
            "regions": [],
        }
