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
        optical_path = context["images"][0]
        sar_path = context["images"][1] if len(context["images"]) > 1 else optical_path
        request_id = context.get("request_id", "demo")

        logger.info("[STUB] Optical-SAR fusion running")

        # No model available
        return {
            "type": "fusion_result",
            "classes": {},
            "evidence_images": [],
            "answer": synthesize_answer(context["query"], context["images"], "fusion"),
            "confidence": None,
        }
