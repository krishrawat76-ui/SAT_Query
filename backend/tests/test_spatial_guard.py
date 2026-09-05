"""
Phase 2 — geospatial guards and raster hygiene.

Covers the two things the audit found completely absent: any spatial
intersection check between multi-image inputs, and any defence against
`Image.convert("RGB")` silently destroying high-bit-depth or nodata rasters.
"""

import struct
import sys
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.agent.exceptions import (
    RasterCompatibilityError,
    RasterTooLargeError,
    SpatialMismatchError,
)
from app.agent.preflight import (
    MIN_BBOX_IOU,
    _bbox_iou,
    check_raster_compatibility,
    check_spatial_overlap,
    run_preflight,
)
from app.utils.raster_io import MAX_DECODED_PIXELS, load_rgb, probe_raster

# ModelPixelScale / ModelTiepoint / GeoKeyDirectory, per raster_stub.py
PIXEL_SCALE_TAG = 33550
TIEPOINT_TAG = 33922
GEOKEY_TAG = 34735


def _geotiff(path: Path, west: float, north: float, *, size=(64, 64), scale=0.001):
    """A TIFF carrying real WGS84 georeferencing tags.

    Written with EPSG:4326 in the GeoKeyDirectory so raster_stub reads the
    bounds directly rather than trying to reproject them.
    """
    img = Image.new("RGB", size, (10, 20, 30))
    geokey = (1, 1, 0, 1, 2048, 0, 1, 4326)  # GeographicTypeGeoKey = 4326
    img.save(
        str(path),
        tiffinfo={
            PIXEL_SCALE_TAG: (scale, scale, 0.0),
            TIEPOINT_TAG: (0.0, 0.0, 0.0, west, north, 0.0),
            GEOKEY_TAG: geokey,
        },
    )
    return str(path)


# ── The bboxes must actually be read as real georeferencing ──────────────


def test_geotiff_fixture_is_recognised_as_georeferenced(tmp_path):
    """Guards the rest of this file: if raster_stub stops reading these tags,
    every enforcement test below would silently degrade to the advisory path
    and pass for the wrong reason."""
    from app.output.raster_stub import extract_bbox

    path = _geotiff(tmp_path / "a.tif", west=72.80, north=19.10)
    result = extract_bbox(path)
    assert result["source"] == "geotiff-tags", result
    assert result["bbox"]["west"] == pytest.approx(72.80)


# ── Zero overlap ─────────────────────────────────────────────────────────


def test_disjoint_georeferenced_rasters_are_rejected(tmp_path):
    """Mumbai vs London. Was: accepted silently, compared as if co-located."""
    a = _geotiff(tmp_path / "mumbai.tif", west=72.80, north=19.10)
    b = _geotiff(tmp_path / "london.tif", west=-0.20, north=51.52)

    with pytest.raises(SpatialMismatchError) as exc:
        check_spatial_overlap([a, b])
    assert exc.value.code == "spatial_mismatch"
    assert exc.value.details["enforced"] is True
    assert exc.value.details["bbox_iou"] == 0.0


def test_overlapping_georeferenced_rasters_are_accepted(tmp_path):
    a = _geotiff(tmp_path / "t1.tif", west=72.800, north=19.100)
    b = _geotiff(tmp_path / "t2.tif", west=72.800, north=19.100)

    warnings, info = check_spatial_overlap([a, b])
    assert info["enforced"] is True
    assert info["bbox_iou"] == pytest.approx(1.0)
    assert warnings == []


def test_partial_overlap_warns_but_is_allowed(tmp_path):
    # Offset by half a tile: overlaps, but only partially.
    a = _geotiff(tmp_path / "t1.tif", west=72.800, north=19.100)
    b = _geotiff(tmp_path / "t2.tif", west=72.832, north=19.100)

    warnings, info = check_spatial_overlap([a, b])
    assert MIN_BBOX_IOU < info["bbox_iou"] < 1.0
    assert any("partially overlap" in w for w in warnings)


# ── The synthetic-bbox trap ──────────────────────────────────────────────


def test_non_georeferenced_pair_is_never_rejected(tmp_path):
    """The single most important test here.

    extract_bbox synthesizes a bbox from a filename hash when GeoTIFF tags are
    absent — measured, `before.png` lands on Mumbai and `after.png` on London.
    Enforcing overlap on that would 422 every ordinary PNG demo upload, so an
    unreferenced pair must warn and pass, never reject.
    """
    a, b = tmp_path / "before.png", tmp_path / "after.png"
    for p in (a, b):
        Image.new("RGB", (64, 64), (10, 20, 30)).save(p)

    warnings, info = check_spatial_overlap([str(a), str(b)])
    assert info["enforced"] is False
    assert info["image_1_source"] == "synthetic"
    assert any("not verified" in w for w in warnings)


def test_one_georeferenced_one_not_is_not_enforced(tmp_path):
    """A mixed pair cannot be compared either — half the footprint is invented."""
    a = _geotiff(tmp_path / "real.tif", west=72.80, north=19.10)
    b = tmp_path / "plain.png"
    Image.new("RGB", (64, 64), (10, 20, 30)).save(b)

    warnings, info = check_spatial_overlap([a, str(b)])
    assert info["enforced"] is False
    assert any("not verified" in w for w in warnings)


def test_single_image_has_nothing_to_overlap(tmp_path):
    p = tmp_path / "a.png"
    Image.new("RGB", (64, 64), (1, 2, 3)).save(p)
    assert check_spatial_overlap([str(p)]) == ([], {})


# ── IoU maths ────────────────────────────────────────────────────────────


def test_bbox_iou_values():
    box = {"west": 0.0, "east": 2.0, "south": 0.0, "north": 2.0}
    assert _bbox_iou(box, box) == pytest.approx(1.0)
    # Half-overlapping: intersection 2, union 6.
    other = {"west": 1.0, "east": 3.0, "south": 0.0, "north": 2.0}
    assert _bbox_iou(box, other) == pytest.approx(2 / 6)
    # Disjoint.
    away = {"west": 10.0, "east": 12.0, "south": 10.0, "north": 12.0}
    assert _bbox_iou(box, away) == 0.0


@pytest.mark.parametrize(
    "bad",
    [
        {},
        {"west": float("nan"), "east": 1.0, "south": 0.0, "north": 1.0},
        {"west": float("inf"), "east": 1.0, "south": 0.0, "north": 1.0},
        {"west": "x", "east": 1.0, "south": 0.0, "north": 1.0},
    ],
)
def test_bbox_iou_returns_none_for_unusable_input(bad):
    """None, not 0.0 — an unknown overlap must not read as a proven mismatch."""
    good = {"west": 0.0, "east": 1.0, "south": 0.0, "north": 1.0}
    assert _bbox_iou(good, bad) is None


# ── Resolution and shape compatibility ───────────────────────────────────


def test_wildly_different_ground_resolution_is_rejected(tmp_path):
    """The same 0.064-degree footprint captured at 640px and at 64px — a 10x
    ground-sample-distance gap, which is the real-world case (Sentinel-2 10m
    against a 1m commercial tile of the same area).

    Sized so the footprints match exactly: with a shared origin and differing
    pixel scale the footprints themselves diverge, and the overlap check would
    reject the pair before resolution was ever considered.
    """
    a = _geotiff(tmp_path / "fine.tif", west=72.80, north=19.10,
                 size=(640, 640), scale=0.0001)
    b = _geotiff(tmp_path / "coarse.tif", west=72.80, north=19.10,
                 size=(64, 64), scale=0.001)

    with pytest.raises(RasterCompatibilityError) as exc:
        check_spatial_overlap([a, b])
    assert exc.value.code == "raster_incompatible"
    assert exc.value.details["gsd_ratio"] == pytest.approx(10.0, rel=0.01)


def test_similar_ground_resolution_is_accepted(tmp_path):
    """Same footprint, only a 2x resolution gap — under the 4x limit."""
    a = _geotiff(tmp_path / "a.tif", west=72.80, north=19.10,
                 size=(128, 128), scale=0.0005)
    b = _geotiff(tmp_path / "b.tif", west=72.80, north=19.10,
                 size=(64, 64), scale=0.001)

    warnings, info = check_spatial_overlap([a, b])
    assert info["gsd_ratio"] == pytest.approx(2.0, rel=0.01)
    assert warnings == []


def test_incompatible_aspect_ratios_are_rejected(tmp_path):
    a, b = tmp_path / "a.png", tmp_path / "b.png"
    Image.new("RGB", (64, 64), (1, 2, 3)).save(a)
    Image.new("RGB", (2000, 100), (1, 2, 3)).save(b)

    with pytest.raises(RasterCompatibilityError):
        check_raster_compatibility([str(a), str(b)])


def test_band_count_mismatch_warns_but_is_allowed(tmp_path):
    a, b = tmp_path / "rgb.png", tmp_path / "gray.png"
    Image.new("RGB", (64, 64), (1, 2, 3)).save(a)
    Image.new("L", (64, 64), 128).save(b)

    warnings = check_raster_compatibility([str(a), str(b)])
    assert any("Band count differs" in w for w in warnings)


# ── Raster hygiene: high bit depth and nodata ────────────────────────────


def test_16bit_raster_keeps_its_dynamic_range(tmp_path):
    """Was: .convert("RGB") clipped a 16-bit TIFF to 0-255, leaving only ~20
    distinct values out of 4096 pixels."""
    path = tmp_path / "u16.tif"
    data = (np.arange(64 * 64).reshape(64, 64) * 900).astype(np.uint16)
    Image.fromarray(data).save(path)

    naive = np.asarray(Image.open(path).convert("RGB"))
    stretched, report = load_rgb(str(path))
    levels = len(np.unique(np.asarray(stretched)))

    assert report["stretched"] is True
    assert len(np.unique(naive)) < 30, "baseline changed; naive clipping expected"
    assert levels > 100, f"stretch preserved only {levels} levels"


def test_all_nodata_raster_is_rejected_not_blackened(tmp_path):
    """Was: an all-NaN float32 tile became solid black (min=0, max=0) and was
    analyzed as though it were real ground."""
    path = tmp_path / "nan.tif"
    Image.fromarray(np.full((32, 32), np.nan, dtype=np.float32), mode="F").save(path)

    with pytest.raises(RasterCompatibilityError) as exc:
        load_rgb(str(path))
    assert "no valid pixels" in exc.value.message


def test_partial_nodata_is_reported_not_hidden(tmp_path):
    path = tmp_path / "partial.tif"
    arr = np.ones((32, 32), dtype=np.float32)
    arr[:8, :] = np.nan          # 25% nodata
    Image.fromarray(arr, mode="F").save(path)

    _img, report = load_rgb(str(path))
    assert report["nodata_fraction"] == pytest.approx(0.25, abs=0.01)


def test_extreme_float_values_do_not_saturate(tmp_path):
    """Was: a float32 tile holding 1e30 became solid white (min=255, max=255).

    The percentile stretch is what saves this: a naive min/max rescale would
    still be flattened by the single 1e30 outlier.
    """
    path = tmp_path / "big.tif"
    arr = np.random.default_rng(0).random((32, 32)).astype(np.float32)
    arr[0, 0] = 1e30
    Image.fromarray(arr, mode="F").save(path)

    naive = np.asarray(Image.open(path).convert("RGB"))
    stretched, report = load_rgb(str(path))

    assert len(np.unique(naive)) <= 2, "baseline changed; naive saturation expected"
    assert report["stretched"] is True
    assert len(np.unique(np.asarray(stretched))) > 50


def test_8bit_raster_passes_through_untouched(tmp_path):
    path = tmp_path / "plain.png"
    Image.new("RGB", (32, 32), (10, 20, 30)).save(path)

    img, report = load_rgb(str(path))
    assert report["stretched"] is False
    assert report["nodata_fraction"] == 0.0
    assert img.mode == "RGB"


def test_single_pixel_raster_is_handled(tmp_path):
    path = tmp_path / "one.png"
    Image.new("RGB", (1, 1), (5, 5, 5)).save(path)
    img, _report = load_rgb(str(path))
    assert img.size == (1, 1)


# ── Decompression bomb ───────────────────────────────────────────────────


def test_decompression_bomb_is_rejected(tmp_path):
    """Was: a 136 KB PNG expanding to 12000x12000 (144 MP, ~432 MB of RGB)
    passed validation with only a warning and loaded in full. PIL's own
    MAX_IMAGE_PIXELS merely warns below 2x its limit."""
    path = tmp_path / "bomb.png"
    Image.new("L", (12000, 12000), 0).save(path)
    assert path.stat().st_size < 1_000_000, "fixture should be a small file"

    info = probe_raster(str(path))
    assert info["pixels"] > MAX_DECODED_PIXELS

    with pytest.raises(RasterTooLargeError) as exc:
        load_rgb(str(path))
    assert exc.value.status_code == 413


def test_large_but_acceptable_raster_still_loads(tmp_path):
    path = tmp_path / "big.png"
    Image.new("RGB", (2048, 2048), (1, 2, 3)).save(path)
    img, _report = load_rgb(str(path))
    assert img.size == (2048, 2048)


# ── Per-image guards must fire for a SINGLE image too ────────────────────


def test_single_image_bomb_is_rejected_by_preflight(tmp_path):
    """The pair-wise checks only run for 2+ images, which left a lone upload
    completely uninspected — a 144 MP bomb and an all-nodata tile both reached
    the pipeline and returned 200 end-to-end."""
    path = tmp_path / "bomb.png"
    Image.new("L", (12000, 12000), 0).save(path)
    pipeline = [{"step": 1, "model": "rs_vlm", "action": "answer_question"}]

    with pytest.raises(RasterTooLargeError):
        run_preflight(pipeline, [str(path)], ["optical"])


def test_single_all_nodata_image_is_rejected_by_preflight(tmp_path):
    path = tmp_path / "nan.tif"
    Image.fromarray(np.full((32, 32), np.nan, dtype=np.float32), mode="F").save(path)
    pipeline = [{"step": 1, "model": "rs_vlm", "action": "answer_question"}]

    with pytest.raises(RasterCompatibilityError):
        run_preflight(pipeline, [str(path)], ["optical"])


def test_partial_nodata_single_image_warns_but_passes(tmp_path):
    path = tmp_path / "partial.tif"
    arr = np.ones((32, 32), dtype=np.float32)
    arr[:24, :] = np.nan          # 75% nodata
    Image.fromarray(arr, mode="F").save(path)
    pipeline = [{"step": 1, "model": "rs_vlm", "action": "answer_question"}]

    result = run_preflight(pipeline, [str(path)], ["optical"])
    assert any("nodata" in w for w in result["warnings"])


def test_high_bit_depth_single_image_is_flagged_as_rescaled(tmp_path):
    """The trace must say the model saw a rescaled view, not native values."""
    path = tmp_path / "u16.tif"
    Image.fromarray((np.arange(64 * 64).reshape(64, 64) * 900).astype(np.uint16)).save(path)
    pipeline = [{"step": 1, "model": "rs_vlm", "action": "answer_question"}]

    result = run_preflight(pipeline, [str(path)], ["optical"])
    assert any("percentile-stretched" in w for w in result["warnings"])


def test_ordinary_8bit_single_image_produces_no_warnings(tmp_path):
    """The demo path must stay quiet — warnings that always fire are ignored."""
    path = tmp_path / "plain.png"
    Image.new("RGB", (64, 64), (10, 20, 30)).save(path)
    pipeline = [{"step": 1, "model": "rs_vlm", "action": "answer_question"}]

    result = run_preflight(pipeline, [str(path)], ["optical"])
    assert result["warnings"] == []


# ── End to end through run_preflight ─────────────────────────────────────


def test_run_preflight_rejects_a_disjoint_change_detection_pair(tmp_path):
    a = _geotiff(tmp_path / "mumbai.tif", west=72.80, north=19.10)
    b = _geotiff(tmp_path / "london.tif", west=-0.20, north=51.52)
    pipeline = [
        {"step": 1, "model": "change_detection", "action": "generate_change_map"}
    ]

    with pytest.raises(SpatialMismatchError):
        run_preflight(pipeline, [a, b], ["optical", "optical"])


def test_run_preflight_passes_a_valid_pair_and_reports_iou(tmp_path):
    a = _geotiff(tmp_path / "t1.tif", west=72.800, north=19.100)
    b = _geotiff(tmp_path / "t2.tif", west=72.800, north=19.100)
    pipeline = [
        {"step": 1, "model": "change_detection", "action": "generate_change_map"}
    ]

    result = run_preflight(pipeline, [a, b], ["optical", "optical"])
    assert result["spatial"]["enforced"] is True
    assert result["spatial"]["bbox_iou"] == pytest.approx(1.0)
    assert result["pipeline"] == pipeline
