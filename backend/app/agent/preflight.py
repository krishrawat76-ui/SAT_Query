"""
Pipeline preconditions, checked before any model is loaded.

The router picks a pipeline from query text; nothing downstream verified that
the request could actually feed it. ShivenRouterAdapter (the default router)
maps a planner task name straight through `_TASK_PIPELINE` and never reads
`input_info["num_images"]`, so a change-detection plan built from
"what changed between the two images?" with one image attached reached
ChangeDetectionModel.run and died on `context["images"][1]` — an IndexError that
PipelineExecutor swallowed into an HTTP 200 response.

The in-repo RuleBasedRouter *is* arity-safe (it gates on n == 0 / n == 2), but
it only runs when USE_SHIVEN_ROUTER=false. This module closes that asymmetry for
whichever router produced the plan.
"""

import math
from typing import Any, Optional

from loguru import logger

from app.agent.exceptions import (
    ArityMismatchError,
    ModalityMismatchError,
    RasterCompatibilityError,
    SpatialMismatchError,
)
from app.output.raster_stub import extract_bbox
from app.utils.raster_io import check_nodata, guard_decoded_size, probe_raster

# What each pipeline model actually indexes out of context, read off the
# wrappers themselves: change_detection reads images[0] AND images[1];
# grounding_dino/sam read images[0]; optical_sar_fusion reads both.
MIN_IMAGES: dict[str, int] = {
    "change_detection": 2,
    "change_vqa": 2,
    "optical_sar_fusion": 2,
    "grounding_dino": 1,
    "sam": 1,
}

# rs_vlm's requirement depends on the action, not the model: answer_question is
# the text-only conversational path and tolerates zero images.
ACTION_MIN_IMAGES: dict[str, int] = {
    "answer_question": 0,
    "generate_caption": 1,
    "detect_regions": 1,
    "segment_regions": 1,
    "generate_change_map": 2,
    "describe_changes": 2,
    "analyze_fused": 2,
    "answer_change_question": 2,
    "fuse_modalities": 2,
}

# Models that are meaningless unless the pair genuinely spans both modalities.
REQUIRES_CROSS_MODAL = {"optical_sar_fusion"}

# Below this IoU, two georeferenced rasters describe different ground.
MIN_BBOX_IOU = 0.05
# Partial overlap above MIN_BBOX_IOU but below this is allowed with a warning.
PARTIAL_OVERLAP_IOU = 0.5
# A 4x ground-sample-distance gap makes a pixel-wise comparison meaningless.
MAX_RESOLUTION_RATIO = 4.0
# Aspect ratios further apart than this cannot be aligned pixel-wise.
MAX_ASPECT_RATIO_SKEW = 1.5


# The conversational plan, used when no imagery was attached at all. Mirrors
# RuleBasedRouter's own `text_only` rule.
TEXT_ONLY_PIPELINE = [{"step": 1, "model": "rs_vlm", "action": "answer_question"}]


def coerce_text_only(pipeline: list[dict]) -> tuple[list[dict], list[str]]:
    """Rewrite an image plan to the conversational one when nothing was attached.

    A zero-image request is unambiguously a chat message, not a malformed image
    request — this codebase already treats it that way in RuleBasedRouter's
    `text_only` rule and in synthesize_answer's no-images branch. The Shiven
    planner routes on query text alone, so "describe the image" with nothing
    attached produced a CAPTIONING plan; 422-ing that would break the
    conversational path for a user who is simply talking.

    Rejecting is still correct when SOME images arrived but too few — that is a
    real mismatch the caller can act on. This only covers the empty case.
    """
    needs_images = any(
        max(
            MIN_IMAGES.get(s.get("model", ""), 0),
            ACTION_MIN_IMAGES.get(s.get("action", ""), 0),
        )
        > 0
        for s in pipeline
    )
    if not needs_images:
        return pipeline, []

    return (
        list(TEXT_ONLY_PIPELINE),
        [
            "No imagery was attached, so the planned image pipeline was replaced "
            "with a conversational reply."
        ],
    )


def check_arity(pipeline: list[dict], num_images: int) -> None:
    """Reject a plan that needs more images than the request carried."""
    for step in pipeline:
        model = step.get("model", "")
        action = step.get("action", "")
        need = max(MIN_IMAGES.get(model, 0), ACTION_MIN_IMAGES.get(action, 0))
        if num_images < need:
            plural = "s" if need != 1 else ""
            were = "were" if num_images != 1 else "was"
            raise ArityMismatchError(
                f"This request was planned as '{model}.{action}', which needs "
                f"{need} image{plural}, but {num_images} {were} provided.",
                details={
                    "model": model,
                    "action": action,
                    "required_images": need,
                    "received_images": num_images,
                },
            )


def check_modality(pipeline: list[dict], modalities: list[str]) -> None:
    """Reject fusion planned over a pair that is not actually cross-modal."""
    planned = {s.get("model") for s in pipeline}
    present = {str(m).lower() for m in modalities}
    for model in sorted(planned & REQUIRES_CROSS_MODAL):
        if present != {"optical", "sar"}:
            raise ModalityMismatchError(
                f"'{model}' fuses one optical and one SAR image, but this "
                f"request provided modalities {list(modalities)}.",
                details={"model": model, "modalities": list(modalities)},
            )


def _bbox_iou(a: dict, b: dict) -> Optional[float]:
    """Intersection-over-union of two WGS84 bboxes. None when either is unusable.

    Both bboxes arrive already reprojected to WGS84 by raster_stub, so this is a
    valid comparison regardless of the files' native CRSs.
    """
    try:
        corners = (
            a["west"], a["east"], a["south"], a["north"],
            b["west"], b["east"], b["south"], b["north"],
        )
        if not all(math.isfinite(float(v)) for v in corners):
            return None
    except (KeyError, TypeError, ValueError):
        return None

    ix1, iy1 = max(a["west"], b["west"]), max(a["south"], b["south"])
    ix2, iy2 = min(a["east"], b["east"]), min(a["north"], b["north"])
    inter = max(0.0, ix2 - ix1) * max(0.0, iy2 - iy1)

    area_a = max(0.0, a["east"] - a["west"]) * max(0.0, a["north"] - a["south"])
    area_b = max(0.0, b["east"] - b["west"]) * max(0.0, b["north"] - b["south"])
    union = area_a + area_b - inter
    return float(inter / union) if union > 0 else None


def check_rasters(image_paths: list[str]) -> list[str]:
    """Per-image raster guards. Runs for EVERY request, one image included.

    The pair-wise checks below only fire for 2+ images, which left a single
    upload completely uninspected: a 136 KB PNG expanding to 144 megapixels and
    an all-NaN nodata tile both reached the pipeline and returned 200. The
    decode-size guard is header-only and free; the nodata check decodes, so it
    only runs for high-bit-depth modes, which are the only ones that can carry
    NaN at all.
    """
    warnings: list[str] = []
    for i, path in enumerate(image_paths):
        label = f"Image {i + 1}"
        info = probe_raster(path)
        guard_decoded_size(info, label)

        nodata = check_nodata(path, info, label)
        if nodata > 0.5:
            warnings.append(
                f"{label}: {nodata:.0%} of pixels are nodata (NaN or infinite); "
                "results over that area are not meaningful."
            )
        if info["high_bit_depth"]:
            warnings.append(
                f"{label}: {info['mode']} raster will be percentile-stretched to "
                "8-bit for inference; reported values are a rescaled view."
            )
    return warnings


def check_raster_compatibility(image_paths: list[str]) -> list[str]:
    """Band-count and shape checks for a pair. Returns trace warnings."""
    if len(image_paths) < 2:
        return []

    warnings: list[str] = []
    a = probe_raster(image_paths[0])
    b = probe_raster(image_paths[1])

    if a["bands"] != b["bands"]:
        warnings.append(
            f"Band count differs between the two images ({a['bands']} vs "
            f"{b['bands']}); both will be compared as 3-band RGB."
        )

    aspect_a = a["width"] / a["height"] if a["height"] else 0.0
    aspect_b = b["width"] / b["height"] if b["height"] else 0.0
    if aspect_a and aspect_b:
        skew = max(aspect_a / aspect_b, aspect_b / aspect_a)
        if skew > MAX_ASPECT_RATIO_SKEW:
            raise RasterCompatibilityError(
                f"The two images have incompatible shapes "
                f"({a['width']}x{a['height']} vs {b['width']}x{b['height']}). "
                "A pixel-wise comparison would align unrelated ground.",
                details={
                    "image_1": [a["width"], a["height"]],
                    "image_2": [b["width"], b["height"]],
                    "aspect_skew": round(skew, 3),
                },
            )

    return warnings


def check_spatial_overlap(
    image_paths: list[str],
) -> tuple[list[str], dict[str, Any]]:
    """Ground-overlap guard for a georeferenced pair.

    Enforced ONLY when BOTH rasters carry real GeoTIFF georeferencing.
    `extract_bbox` falls back to a bbox synthesized from the filename hash when
    tags are absent — measured, two ordinary PNGs land on different continents
    (before.png -> Mumbai, after.png -> London). Rejecting on that would 422
    every non-georeferenced demo upload, so an unreferenced pair produces a
    warning and is allowed through rather than a fabricated mismatch.
    """
    if len(image_paths) < 2:
        return [], {}

    a = extract_bbox(image_paths[0])
    b = extract_bbox(image_paths[1])
    both_real = (
        a.get("source") == "geotiff-tags" and b.get("source") == "geotiff-tags"
    )
    iou = _bbox_iou(a.get("bbox", {}), b.get("bbox", {}))

    info: dict[str, Any] = {
        "image_1_source": a.get("source"),
        "image_2_source": b.get("source"),
        "bbox_iou": round(iou, 4) if iou is not None else None,
        "enforced": both_real,
    }

    if not both_real:
        return (
            [
                "Ground overlap was not verified: one or both images carry no "
                "GeoTIFF georeferencing, so their real footprints are unknown."
            ],
            info,
        )

    if iou is None:
        return (
            ["Ground overlap could not be computed from the GeoTIFF bounds."],
            info,
        )

    if iou < MIN_BBOX_IOU:
        raise SpatialMismatchError(
            f"The two georeferenced images do not cover the same ground "
            f"(bounding-box IoU {iou:.3f}, minimum {MIN_BBOX_IOU}). A change or "
            "fusion comparison between them would be meaningless.",
            details=info,
        )

    warnings: list[str] = []
    if iou < PARTIAL_OVERLAP_IOU:
        warnings.append(
            f"The two images only partially overlap (IoU {iou:.2f}); results "
            "outside the shared footprint are not meaningful."
        )

    ratio = _gsd_ratio(a, b, image_paths)
    if ratio is not None:
        info["gsd_ratio"] = round(ratio, 3)
        if ratio > MAX_RESOLUTION_RATIO:
            raise RasterCompatibilityError(
                f"The two images differ in ground resolution by {ratio:.1f}x, "
                "which is too large for a pixel-wise comparison.",
                details=info,
            )

    return warnings, info


def _gsd_ratio(a: dict, b: dict, image_paths: list[str]) -> Optional[float]:
    """Approximate ground-sample-distance ratio, from footprint span / width."""
    try:
        pa = probe_raster(image_paths[0])
        pb = probe_raster(image_paths[1])
        gsd_a = (a["bbox"]["east"] - a["bbox"]["west"]) / max(pa["width"], 1)
        gsd_b = (b["bbox"]["east"] - b["bbox"]["west"]) / max(pb["width"], 1)
    except (KeyError, TypeError, ValueError, OSError):
        return None

    if not (gsd_a > 0 and gsd_b > 0):
        return None
    if not (math.isfinite(gsd_a) and math.isfinite(gsd_b)):
        return None
    return max(gsd_a / gsd_b, gsd_b / gsd_a)


def run_preflight(
    pipeline: list[dict],
    image_paths: list[str],
    modalities: list[str],
) -> dict[str, Any]:
    """Run every precondition.

    Raises a PipelineInputError subclass for anything that makes the planned
    pipeline impossible or meaningless. Otherwise returns the pipeline to
    actually execute (rewritten to the conversational plan when no imagery was
    attached), plus warnings and spatial facts for the trace.
    """
    coerced_warnings: list[str] = []
    if not image_paths:
        pipeline, coerced_warnings = coerce_text_only(pipeline)

    check_arity(pipeline, len(image_paths))
    check_modality(pipeline, modalities)
    raster_warnings = check_rasters(image_paths)
    pair_warnings = check_raster_compatibility(image_paths)
    spatial_warnings, spatial = check_spatial_overlap(image_paths)

    all_warnings = (
        coerced_warnings + raster_warnings + pair_warnings + spatial_warnings
    )
    if all_warnings:
        logger.info(f"Preflight warnings: {all_warnings}")

    return {"pipeline": pipeline, "warnings": all_warnings, "spatial": spatial}
