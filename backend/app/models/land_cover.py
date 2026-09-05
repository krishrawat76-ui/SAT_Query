"""
Land Cover Model Stub — Placeholder for a lightweight land-cover segmentation
model (MobileNetV4 UNet in the real deployment).

Status: STUB — no weights loaded, so this never fabricates a percentage
breakdown. Runs BEFORE the heavy VLM dispatch decision, concurrently with
query routing (see app/agent/land_cover_check.py and app/api/routes.py), so
a request that carries no meaningful high-level feature signal (open ocean,
unbroken forest) can be answered from segmentation alone without paying the
remote VLM round trip.

TODO: replace with real MobileNetV4 UNet inference.
"""

from app.models.base import BaseModelWrapper

# Categories the acceptance threshold sums over (see land_cover_check.py).
# Water and Urban are deliberately excluded from "land" — an open-ocean or
# built-up scene is exactly where the VLM's reasoning over what
# infrastructure/water body is present still adds information beyond a bare
# percentage split.
LAND_CATEGORIES = ("forest", "vegetation", "barren")
ALL_CATEGORIES = ("water", "forest", "vegetation", "barren", "urban")


class LandCoverModel(BaseModelWrapper):
    """
    Stub: lightweight land-cover segmentation.

    No model available — reports every category as unknown rather than
    inventing a plausible-looking split. `land_pct: None` is the load-bearing
    field: every caller treats None as "cannot decide from this," never as
    "decided against" (see evaluate_threshold in land_cover_check.py). The
    same discipline every other stub in this codebase already follows
    (GroundingModel returns zero boxes rather than fabricated detections).
    """

    def run(self, action: str, context: dict) -> dict:
        images = self.require_images(context, 1, model="land_cover", action=action)
        return {
            "type": "land_cover",
            "breakdown": {cat: None for cat in ALL_CATEGORIES},
            "land_pct": None,
            "image": images[0],
        }
