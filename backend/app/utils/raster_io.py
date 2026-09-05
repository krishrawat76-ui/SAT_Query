"""
Raster loading that refuses to silently corrupt data.

`Image.open(p).convert("RGB")` — used verbatim in evidence.py, raster_stub.py
and the model wrappers — destroys real remote-sensing data without raising.
Measured on synthetic rasters:

  - a 16-bit uint TIFF with values up to 3.7M keeps only ~20 of its levels
  - an all-NaN float32 nodata tile becomes solid black (min=0, max=0)
  - a float32 tile holding 1e30 becomes solid white (min=255, max=255)

None of those raise, and InputValidator marks all three `valid=True` with zero
warnings, so a model would "analyze" a black square and report a confident
answer about it. This module applies a percentile stretch over the real finite
range instead, and reports what it had to do so the execution trace can state
that the pixels the model saw are a rescaled view rather than native values.

Supersedes app/utils/image_utils.py, which had no callers.
"""

import math
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image

from app.agent.exceptions import RasterCompatibilityError, RasterTooLargeError

# 8192*8192*3 bytes ~= 200 MB decoded per image. InputValidator.MAX_DIMENSION
# only *warned* at 8192px; a 136 KB PNG expanding to 12000x12000 (144 MP) was
# measured passing validation and loading in full.
MAX_DECODED_PIXELS = 8192 * 8192

# 2/98 is the standard remote-sensing display stretch. It keeps outliers — 1e30
# nodata sentinels, hot pixels — from flattening the whole image to one value,
# which is exactly what a naive min/max rescale does.
STRETCH_PERCENTILES = (2.0, 98.0)

INTEGER_MODES = {"I", "I;16", "I;16B", "I;16L", "I;16S", "I;32"}
FLOAT_MODES = {"F"}


def probe_raster(path: str) -> dict[str, Any]:
    """Header-only facts about a raster. Does not decode pixel data."""
    with Image.open(path) as img:
        width, height = img.size
        return {
            "filename": Path(path).name,
            "width": width,
            "height": height,
            "pixels": width * height,
            "mode": img.mode,
            "bands": len(img.getbands()),
            "format": img.format,
            "high_bit_depth": img.mode in INTEGER_MODES or img.mode in FLOAT_MODES,
        }


def guard_decoded_size(info: dict[str, Any], label: str = "Image") -> None:
    """Reject a decompression bomb before any pixel is materialized."""
    if info["pixels"] > MAX_DECODED_PIXELS:
        raise RasterTooLargeError(
            f"{label}: {info['width']}x{info['height']} "
            f"({info['pixels'] / 1e6:.1f} megapixels) exceeds the "
            f"{MAX_DECODED_PIXELS / 1e6:.0f} megapixel decode limit.",
            details={
                "width": info["width"],
                "height": info["height"],
                "megapixels": round(info["pixels"] / 1e6, 1),
            },
        )


def check_nodata(path: str, info: dict[str, Any], label: str = "Image") -> float:
    """Nodata fraction for a high-bit-depth raster; raises if there is no data.

    Separate from load_rgb so preflight can reject an all-nodata tile without
    building the stretched RGB image it would then throw away. Returns 0.0 for
    8-bit rasters, which cannot carry NaN.
    """
    if not info["high_bit_depth"]:
        return 0.0

    with Image.open(path) as img:
        img.load()
        arr = np.asarray(img, dtype=np.float64)

    if arr.size == 0:
        raise RasterCompatibilityError(
            f"{label}: contains no pixels.", details={"mode": info["mode"]}
        )

    finite = np.isfinite(arr)
    if not finite.any():
        raise RasterCompatibilityError(
            f"{label}: contains no valid pixels — every value is NaN or "
            "infinite (an all-nodata tile).",
            details={"mode": info["mode"], "nodata_fraction": 1.0},
        )
    return round(float(1.0 - finite.mean()), 4)


def load_rgb(path: str, *, label: str = "Image") -> tuple[Image.Image, dict[str, Any]]:
    """Load any raster as 8-bit RGB, stretching rather than clipping.

    Returns ``(image, report)``. The report carries the nodata fraction and the
    stretch bounds actually applied, so the trace can say the model saw a
    rescaled view. An 8-bit input passes through untouched with
    ``stretched: False``.

    Raises RasterTooLargeError for a decompression bomb and
    RasterCompatibilityError for a tile with no valid pixels at all.
    """
    info = probe_raster(path)
    guard_decoded_size(info, label)

    report: dict[str, Any] = {
        "source_mode": info["mode"],
        "stretched": False,
        "nodata_fraction": 0.0,
        "stretch_range": None,
    }

    with Image.open(path) as img:
        img.load()

        if img.mode not in INTEGER_MODES and img.mode not in FLOAT_MODES:
            return img.convert("RGB"), report

        arr = np.asarray(img, dtype=np.float64)
        finite = np.isfinite(arr)
        report["nodata_fraction"] = round(
            float(1.0 - finite.mean()) if arr.size else 1.0, 4
        )

        if not finite.any():
            # Every pixel is NaN or infinite. This previously became a solid
            # black image and was analyzed as though it were real ground.
            raise RasterCompatibilityError(
                f"{label}: contains no valid pixels — every value is NaN or "
                "infinite (an all-nodata tile).",
                details={"mode": info["mode"], "nodata_fraction": 1.0},
            )

        valid = arr[finite]
        lo, hi = (float(v) for v in np.percentile(valid, STRETCH_PERCENTILES))
        if not math.isfinite(lo) or not math.isfinite(hi) or hi <= lo:
            # Percentiles collapse on a constant or near-constant tile.
            lo, hi = float(valid.min()), float(valid.max())
        if hi <= lo:
            hi = lo + 1.0

        scaled = np.clip((arr - lo) / (hi - lo), 0.0, 1.0)
        # Nodata renders as black, but only after being counted above — the
        # difference from the old behaviour is that we now know and report it.
        scaled[~finite] = 0.0

        out = Image.fromarray((scaled * 255).astype(np.uint8), mode="L").convert("RGB")
        report["stretched"] = True
        report["stretch_range"] = [lo, hi]
        return out, report
