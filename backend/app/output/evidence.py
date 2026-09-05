"""
Evidence generation helpers — Overlay bounding boxes, colorize change maps, save to results/.

Owner: M3 (Agent/Router Lead)

Provides utility functions for generating visual evidence:
  - Bounding box overlays on satellite images
  - Change map colorization
  - Segmentation mask overlays
  - Legend generation
"""

import math
import os
from pathlib import Path
from typing import Optional

import numpy as np
from PIL import Image, ImageDraw, ImageFont
from loguru import logger

from app.utils.config import settings
from app.utils.raster_io import load_rgb

# Was a CWD-relative Path("results"), while main.py mounts the absolute
# settings.RESULTS_DIR at /results. Launched from the repo root rather than
# backend/, evidence images were written where nothing serves them — 404 URLs
# inside an otherwise-successful 200 response.
RESULTS_DIR = settings.RESULTS_DIR


def ensure_results_dir(request_id: str = "") -> Path:
    """Ensure the results directory exists and return path for request."""
    out_dir = RESULTS_DIR / request_id if request_id else RESULTS_DIR
    out_dir.mkdir(parents=True, exist_ok=True)
    return out_dir


def sanitize_boxes(
    boxes: list,
    labels: list,
    scores: list,
    width: int,
    height: int,
) -> list[tuple[tuple[float, float, float, float], str, float]]:
    """Drop boxes that cannot be drawn; clamp the rest to the image.

    Detector post-processing produces all of these in practice, and every one
    was mishandled: out-of-bounds and zero-area boxes rendered as meaningless
    overlays, while inverted, NaN/inf and wrong-arity boxes raised inside the
    draw loop and cost the entire overlay — one bad box discarded every good
    one alongside it.
    """
    out = []
    for box, label, score in zip(boxes, labels, scores):
        if not isinstance(box, (list, tuple)) or len(box) != 4:
            logger.warning(f"Dropping malformed bbox (expected 4 values): {box!r}")
            continue
        try:
            coords = [float(c) for c in box]
        except (TypeError, ValueError):
            logger.warning(f"Dropping non-numeric bbox: {box!r}")
            continue
        if not all(math.isfinite(c) for c in coords):
            logger.warning(f"Dropping non-finite bbox: {box!r}")
            continue

        x1, x2 = sorted((coords[0], coords[2]))
        y1, y2 = sorted((coords[1], coords[3]))
        # Clamp into the image before the area test, so a box that is entirely
        # outside the frame collapses and is dropped rather than drawn at the edge.
        x1, x2 = max(0.0, min(x1, width)), max(0.0, min(x2, width))
        y1, y2 = max(0.0, min(y1, height)), max(0.0, min(y2, height))
        if x2 - x1 < 1 or y2 - y1 < 1:
            logger.warning(f"Dropping zero-area or off-image bbox: {box!r}")
            continue

        try:
            numeric_score = float(score)
            if not math.isfinite(numeric_score):
                numeric_score = 0.0
        except (TypeError, ValueError):
            numeric_score = 0.0

        out.append(((x1, y1, x2, y2), str(label), numeric_score))
    return out


def overlay_bboxes(
    image_path: str,
    boxes: list[list[float]],
    labels: list[str],
    scores: list[float],
    request_id: str = "demo",
    color: tuple = (0, 120, 255),
    line_width: int = 3,
) -> Optional[str]:
    """
    Draw bounding boxes on an image and save as evidence.

    Args:
        image_path: Path to the original image.
        boxes: List of [x1, y1, x2, y2] bounding boxes.
        labels: List of label strings.
        scores: List of confidence scores.
        request_id: For file naming.
        color: RGB tuple for box color.
        line_width: Box border width.

    Returns:
        URL path to the saved evidence image, or None if it could not be
        generated. `None`, not `""` — an empty string reads as a valid-but-blank
        URL to a caller, and callers were silently accepting it as evidence.
    """
    try:
        # load_rgb, not .convert("RGB"): rejects a decompression bomb and
        # stretches high-bit-depth rasters instead of clipping them to 20
        # surviving levels.
        img, _report = load_rgb(image_path, label="Evidence image")
        draw = ImageDraw.Draw(img)

        drawable = sanitize_boxes(boxes, labels, scores, img.width, img.height)

        for (x1, y1, x2, y2), label, score in drawable:
            draw.rectangle([x1, y1, x2, y2], outline=color, width=line_width)

            text = f"{label} ({score:.2f})"
            text_bbox = draw.textbbox((x1, y1), text)
            text_h = text_bbox[3] - text_bbox[1]
            text_w = text_bbox[2] - text_bbox[0]
            # Keep the label inside the frame when the box hugs the top edge.
            label_y = y1 if y1 - text_h - 6 >= 0 else y2 + text_h + 6
            draw.rectangle(
                [x1, label_y - text_h - 6, x1 + text_w + 6, label_y],
                fill=color,
            )
            draw.text((x1 + 3, label_y - text_h - 3), text, fill="white")

        out_dir = ensure_results_dir(request_id)
        out_path = out_dir / "grounding_overlay.png"
        img.save(str(out_path))

        return f"/results/{request_id}/grounding_overlay.png"

    except Exception:
        logger.error(
            f"Failed to generate bbox overlay for request {request_id}",
            exc_info=True,
        )
        return None


def colorize_change_map(
    change_mask: np.ndarray,
    request_id: str = "demo",
    change_color: tuple = (255, 60, 60),
    no_change_color: tuple = (200, 200, 200),
) -> Optional[str]:
    """
    Convert a binary change mask to a colored PNG.

    Args:
        change_mask: 2D numpy array (1=changed, 0=unchanged).
        request_id: For file naming.
        change_color: RGB for changed pixels.
        no_change_color: RGB for unchanged pixels.

    Returns:
        URL path to the saved change map image.
    """
    try:
        h, w = change_mask.shape[:2]
        colored = np.zeros((h, w, 3), dtype=np.uint8)
        colored[change_mask > 0] = change_color
        colored[change_mask == 0] = no_change_color

        out_dir = ensure_results_dir(request_id)
        out_path = out_dir / "change_map.png"
        Image.fromarray(colored).save(str(out_path))

        return f"/results/{request_id}/change_map.png"

    except Exception:
        logger.error(
            f"Failed to generate change map for request {request_id}", exc_info=True
        )
        return None


def overlay_segmentation_mask(
    image_path: str,
    mask: np.ndarray,
    request_id: str = "demo",
    color: tuple = (0, 120, 255),
    alpha: float = 0.4,
) -> Optional[str]:
    """
    Overlay a segmentation mask on the original image.

    Args:
        image_path: Path to the original image.
        mask: 2D numpy array (1=foreground, 0=background).
        request_id: For file naming.
        color: RGB tuple for mask overlay color.
        alpha: Transparency (0=invisible, 1=opaque).

    Returns:
        URL path to the saved overlay image.
    """
    try:
        rgb, _report = load_rgb(image_path, label="Segmentation base image")
        img = np.array(rgb)

        overlay = img.copy()
        overlay[mask > 0] = color
        blended = (img * (1 - alpha) + overlay * alpha).astype(np.uint8)

        out_dir = ensure_results_dir(request_id)
        out_path = out_dir / "segmentation_overlay.png"
        Image.fromarray(blended).save(str(out_path))

        return f"/results/{request_id}/segmentation_overlay.png"

    except Exception:
        logger.error(
            f"Failed to generate segmentation overlay for request {request_id}", exc_info=True
        )
        return None


def generate_land_cover_map(
    class_map: np.ndarray,
    class_names: list[str],
    class_colors: list[tuple],
    request_id: str = "demo",
) -> Optional[str]:
    """
    Convert a class map to a colored land cover visualization.

    Args:
        class_map: 2D numpy array of class indices.
        class_names: List of class name strings.
        class_colors: List of RGB tuples per class.
        request_id: For file naming.

    Returns:
        URL path to the saved land cover map.
    """
    try:
        h, w = class_map.shape[:2]
        colored = np.zeros((h, w, 3), dtype=np.uint8)
        for i, color in enumerate(class_colors):
            colored[class_map == i] = color

        out_dir = ensure_results_dir(request_id)
        out_path = out_dir / "landcover_map.png"
        Image.fromarray(colored).save(str(out_path))

        return f"/results/{request_id}/landcover_map.png"

    except Exception:
        logger.error(
            f"Failed to generate land cover map for request {request_id}", exc_info=True
        )
        return None
