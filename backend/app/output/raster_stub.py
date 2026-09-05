"""
Phase 3 raster stub — coordinate extraction and synthetic analysis-layer
generation for /api/process-raster.

Reads real GeoTIFF georeferencing tags (ModelPixelScale/ModelTiepoint) via
Pillow when present; otherwise synthesizes a plausible 4-corner bbox from the
image's own aspect ratio. No rasterio/GDAL dependency.
"""

import hashlib
import math
from pathlib import Path
from typing import Optional

from PIL import Image
from loguru import logger

from app.output.evidence import ensure_results_dir
from app.utils.raster_io import load_rgb

try:
    from pyproj import Transformer
    _HAS_PYPROJ = True
except ImportError:
    _HAS_PYPROJ = False

KM_PER_DEG_LAT = 111.32

# Returned when a bbox is unusable (missing, non-numeric, or non-finite) rather
# than guessing from it. Mid-range, so the map frames *something* sensible.
DEFAULT_ZOOM = 12.0

ANCHORS = [
    (72.8777, 19.076),    # Mumbai
    (-77.0369, 38.8951),  # Washington DC
    (-0.1276, 51.5074),   # London
]

GEOTIFF_PIXEL_SCALE_TAG = 33550
GEOTIFF_TIEPOINT_TAG = 33922
GEOTIFF_GEOKEY_DIRECTORY_TAG = 34735


def _stable_hash(key: str) -> int:
    return int(hashlib.sha256(key.encode("utf-8")).hexdigest(), 16)


def _synthetic_bbox(image_path: str, width: int, height: int) -> dict:
    """Deterministic-per-file bbox anchored near a rotating demo location,
    sized from the image's own aspect ratio at a fixed ~6km ground scale."""
    key = f"{Path(image_path).name}:{width}x{height}"
    h = _stable_hash(key)

    anchor_lng, anchor_lat = ANCHORS[h % len(ANCHORS)]
    jitter_lng = ((h // 3) % 1000 / 1000 - 0.5) * 0.2
    jitter_lat = ((h // 7) % 1000 / 1000 - 0.5) * 0.2
    center_lng = anchor_lng + jitter_lng
    center_lat = anchor_lat + jitter_lat

    # Sized like a real satellite chip (sub-km to low-km) rather than an
    # entire neighborhood, so it frames comfortably at zoom 14-16 (see
    # zoom_for_bbox) instead of overflowing the whole viewport.
    ground_span_km = 1.2
    aspect = width / height if height else 1.0
    if aspect >= 1:
        half_h_km = ground_span_km / 2 / aspect
        half_w_km = ground_span_km / 2
    else:
        half_w_km = ground_span_km / 2 * aspect
        half_h_km = ground_span_km / 2

    lat_deg_per_km = 1 / KM_PER_DEG_LAT
    lng_deg_per_km = 1 / (KM_PER_DEG_LAT * max(math.cos(math.radians(center_lat)), 0.1))

    half_lat = half_h_km * lat_deg_per_km
    half_lng = half_w_km * lng_deg_per_km

    return {
        "bbox": {
            "north": center_lat + half_lat,
            "south": center_lat - half_lat,
            "east": center_lng + half_lng,
            "west": center_lng - half_lng,
        },
        "center": [center_lng, center_lat],
        "source": "synthetic",
    }


def _epsg_from_geokey_directory(directory) -> Optional[int]:
    """Parse the raw GeoKeyDirectoryTag (34735) for GeographicTypeGeoKey (2048)
    or ProjectedCSTypeGeoKey (3072) — both store their value directly in the
    4th field when TIFFTagLocation is 0, per the GeoTIFF spec. This is the
    EPSG code identifying the file's real CRS (e.g. 326xx/327xx for UTM,
    which is what Sentinel-2 L2A products ship in)."""
    if not directory or len(directory) < 4:
        return None
    try:
        num_keys = int(directory[3])
        for i in range(num_keys):
            offset = 4 + i * 4
            if offset + 4 > len(directory):
                break
            key_id, tag_location, _count, value = directory[offset:offset + 4]
            if int(tag_location) == 0 and int(key_id) in (2048, 3072):
                return int(value)
    except (IndexError, TypeError, ValueError):
        return None
    return None


def _reproject_to_wgs84(west: float, south: float, east: float, north: float, epsg: int) -> Optional[dict]:
    """Reprojects a native-CRS bbox to WGS84 lon/lat via pyproj — handles any
    EPSG code PROJ knows about, not just UTM, so this isn't Sentinel-specific."""
    if not _HAS_PYPROJ:
        return None
    try:
        transformer = Transformer.from_crs(f"EPSG:{epsg}", "EPSG:4326", always_xy=True)
        lon1, lat1 = transformer.transform(west, south)
        lon2, lat2 = transformer.transform(east, north)
        lons, lats = [lon1, lon2], [lat1, lat2]
        return {
            "west": min(lons), "east": max(lons),
            "south": min(lats), "north": max(lats),
        }
    except Exception as e:
        logger.warning(f"Reprojection from EPSG:{epsg} to WGS84 failed: {e}")
        return None


def _geotiff_bbox(img: Image.Image, width: int, height: int) -> Optional[dict]:
    """Real bbox from GeoTIFF ModelPixelScale/ModelTiepoint tags, when present.
    Reprojects to WGS84 via pyproj when the file's CRS (read from its
    GeoKeyDirectory) is a projected CRS like UTM — real satellite products
    (Sentinel-2 L2A included) are almost always shipped in UTM, not raw
    lat/lon, so skipping this step would silently mis-scale every
    georeferenced upload of that kind into meters mistaken for degrees."""
    tags = getattr(img, "tag_v2", None)
    if tags is None:
        return None
    if GEOTIFF_PIXEL_SCALE_TAG not in tags or GEOTIFF_TIEPOINT_TAG not in tags:
        return None

    try:
        scale = tags[GEOTIFF_PIXEL_SCALE_TAG]
        tiepoint = tags[GEOTIFF_TIEPOINT_TAG]
        scale_x, scale_y = float(scale[0]), float(scale[1])
        # Tiepoint layout: (pixel_x, pixel_y, pixel_z, world_x, world_y, world_z, ...)
        origin_x, origin_y = float(tiepoint[3]), float(tiepoint[4])

        # A NaN/inf tag value propagates through the arithmetic below and out
        # into the response, where it fails Starlette's allow_nan=False render
        # as a 500. Fall back to synthetic instead.
        if not all(
            math.isfinite(v) for v in (scale_x, scale_y, origin_x, origin_y)
        ):
            logger.warning("GeoTIFF tags carry non-finite values — using synthetic bbox.")
            return None

        west = origin_x
        north = origin_y
        east = origin_x + scale_x * width
        south = origin_y - scale_y * height

        epsg = None
        if GEOTIFF_GEOKEY_DIRECTORY_TAG in tags:
            epsg = _epsg_from_geokey_directory(tags[GEOTIFF_GEOKEY_DIRECTORY_TAG])

        if epsg and epsg != 4326:
            reprojected = _reproject_to_wgs84(west, south, east, north, epsg)
            if not reprojected:
                # A projected CRS we can't resolve (no pyproj, or an EPSG
                # code PROJ doesn't recognize) — don't trust raw meters as
                # degrees, fall back to synthetic instead.
                return None
            west, east = reprojected["west"], reprojected["east"]
            south, north = reprojected["south"], reprojected["north"]
            logger.info(f"Reprojected GeoTIFF bounds from EPSG:{epsg} to WGS84.")
        elif not (-180 <= west <= 180 and -180 <= east <= 180 and -90 <= north <= 90 and -90 <= south <= 90):
            # No usable CRS key and the raw values aren't plausible lat/lon
            # either — almost certainly meters in an unidentified CRS.
            return None

        return {
            "bbox": {"north": north, "south": south, "east": east, "west": west},
            "center": [(east + west) / 2, (north + south) / 2],
            "source": "geotiff-tags",
        }
    except (IndexError, TypeError, ValueError) as e:
        logger.warning(f"Failed to parse GeoTIFF tags, falling back to synthetic bbox: {e}")
        return None


def extract_bbox(image_path: str) -> dict:
    """Real GeoTIFF georeferencing when present, else a synthesized bbox."""
    width, height = 512, 512
    try:
        with Image.open(image_path) as img:
            width, height = img.size
            if img.format == "TIFF":
                real = _geotiff_bbox(img, width, height)
                if real:
                    return real
    except Exception as e:
        logger.warning(f"Could not open {image_path} to inspect dimensions/tags: {e}")

    return _synthetic_bbox(image_path, width, height)


def zoom_for_bbox(bbox: dict) -> float:
    """Zoom that renders the bbox at roughly 1/2.5 (~150% padding) of an
    assumed ~900px map viewport width. MapLibre GL's zoom-to-pixel scale is
    defined relative to 512px base tiles (not the classic 256px XYZ
    raster-tile convention) — using 256 here renders everything exactly one
    zoom level too tight (2x too big on screen), confirmed empirically
    against a live map. [2, 18] are outer safety bounds only, not a target
    range — a small synthetic chip naturally lands around 14-16, while a
    real satellite tile (tens to ~100km across) correctly lands much lower
    (zoomed further out) so the whole extent still fits the viewport.

    Non-finite spans reach here from _reproject_to_wgs84: pyproj returns inf
    for coordinates outside a projected CRS's valid domain, which a malformed
    GeoTIFF tiepoint produces routinely. An inf span drove log2(0) →
    ValueError → 500, and a NaN span slipped through min/max to return 2.0 —
    a plausible-looking wrong answer, which is worse than an honest default."""
    try:
        span = abs(float(bbox["east"]) - float(bbox["west"]))
    except (KeyError, TypeError, ValueError):
        return DEFAULT_ZOOM
    if not math.isfinite(span):
        return DEFAULT_ZOOM

    lng_span = min(max(span, 1e-6), 360.0)
    assumed_viewport_px = 900.0
    padding_factor = 2.5
    target_px = assumed_viewport_px / padding_factor
    raw_zoom = math.log2((360.0 * target_px) / (lng_span * 512.0))
    if not math.isfinite(raw_zoom):
        return DEFAULT_ZOOM
    return float(min(18.0, max(2.0, raw_zoom)))


def generate_layers(image_path: str, request_id: str) -> dict[str, Optional[str]]:
    """Save the real uploaded image as the map's base raster layer.

    `structural_changes`/`spectral_bands` are explicitly `None` — this used
    to fabricate them (a fixed two-blob red overlay and a fixed channel
    remap, drawn identically on any image regardless of content), with no
    real change-detection or spectral model behind either one. There is no
    such model in this repo (TinyCD and a spectral pipeline were never
    implemented), so faking the images was pure fabrication, not a
    placeholder for something that would soon be real.

    They stay in the returned dict as `None` rather than being dropped, so
    the response shape matches `RasterLayers` exactly and a future real
    model (TinyCD for `structural_changes`, say) only has to change this
    function's return value — nothing downstream needs updating, since the
    frontend already renders a tab for a layer only when its value here is
    a real URL.
    """
    out_dir = ensure_results_dir(request_id)

    try:
        # load_rgb, not .convert("RGB"): a 16-bit or float32 GeoTIFF — the
        # normal case for real satellite products — was clipped to a handful of
        # surviving levels, so the map's base layer showed a near-black or
        # near-white tile with no indication anything had been lost.
        img, _report = load_rgb(image_path, label="Raster base layer")
    except Exception as e:
        logger.error(f"Failed to open {image_path} for layer generation: {e}")
        img = Image.new("RGB", (512, 512), (40, 40, 40))

    base_path = out_dir / "raster_base.png"
    img.save(str(base_path))

    return {
        "base": f"/results/{request_id}/raster_base.png",
        "structural_changes": None,
        "spectral_bands": None,
    }
