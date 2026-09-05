"""
Optical-SAR Fusion Model Stub — Placeholder for cross-modal fusion network.

Owner: M4 (ML Pipelines Lead)
Status: STUB — returns 'Model output not available'.

Replace with custom EfficientNet-B0 dual encoder + cross-attention fusion.
"""

import numpy as np
from PIL import Image
from loguru import logger

from app.models.base import BaseModelWrapper
from app.output.evidence import generate_land_cover_map
from app.utils.synthesize import synthesize_answer


class OpticalSARFusionModel(BaseModelWrapper):
    """
    Stub: Optical-SAR fusion network.

    Generates a land cover classification from optical + SAR image pair.
    TODO (M4/M5): Replace with actual EfficientNet-B0 fusion network trained on BigEarthNet-MM.
    """

    CLASS_NAMES = ["Built-up", "Water", "Vegetation", "Bare soil", "Agriculture"]
    CLASS_COLORS = [
        (255, 60, 60),     # Red — Built-up
        (60, 60, 255),     # Blue — Water
        (60, 200, 60),     # Green — Vegetation
        (180, 130, 70),    # Brown — Bare soil
        (255, 255, 80),    # Yellow — Agriculture
    ]

    def run(self, action: str, context: dict) -> dict:
        # Was context["images"][0] with a silent fall back to reusing the
        # optical image as the SAR one — fusion of an image with itself,
        # reported as a real cross-modal result. Preflight rejects a
        # non-cross-modal pair; this refuses to invent the second input.
        # Called for the arity check, not the paths: this stub returns empty
        # literals, and a real fusion network would read images[0] (optical)
        # and images[1] (SAR).
        self.require_images(context, 2, model="optical_sar_fusion", action=action)

        logger.info("[STUB] Optical-SAR fusion running")

        # No model available
        return {
            "type": "fusion_result",
            "classes": {},
            "evidence_images": [],
            "answer": synthesize_answer(context["query"], context["images"], "fusion"),
            "confidence": None,
        }
