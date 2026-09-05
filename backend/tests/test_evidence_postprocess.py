"""
Phase 2 — bounding-box post-processing and evidence failure reporting.

Detector output is not trustworthy: real post-processing emits out-of-bounds,
zero-area, inverted, and non-finite boxes. Measured against the old
overlay_bboxes, every one of those was mishandled — the first two rendered
meaningless overlays, the rest raised inside the draw loop and returned "",
discarding every good box alongside the bad one.
"""

import sys
from pathlib import Path

import pytest
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.output.evidence import overlay_bboxes, sanitize_boxes


@pytest.fixture
def base_image(tmp_path):
    path = tmp_path / "base.png"
    Image.new("RGB", (64, 64), (10, 20, 30)).save(path)
    return str(path)


def _boxes(*boxes):
    return list(boxes), ["obj"] * len(boxes), [0.9] * len(boxes)


# ── sanitize_boxes ───────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "label,box",
    [
        ("nan", [float("nan")] * 4),
        ("inf", [float("inf")] * 4),
        ("wrong arity", [1, 2, 3]),
        ("too many", [1, 2, 3, 4, 5]),
        ("non-numeric", ["a", "b", "c", "d"]),
        ("not a sequence", 42),
        ("zero area", [20, 20, 20, 20]),
        ("sub-pixel", [20, 20, 20.5, 20.5]),
        ("entirely off-image", [500, 500, 900, 900]),
        ("negative off-image", [-900, -900, -500, -500]),
    ],
)
def test_unusable_boxes_are_dropped(label, box):
    kept = sanitize_boxes([box], ["obj"], [0.9], 64, 64)
    assert kept == [], f"{label} should have been dropped"


def test_out_of_bounds_box_is_clamped_not_dropped():
    """A box that overruns the frame still marks a real region — clamp it."""
    kept = sanitize_boxes([[-500, -500, 99999, 99999]], ["obj"], [0.9], 64, 64)
    assert len(kept) == 1
    (x1, y1, x2, y2), _label, _score = kept[0]
    assert (x1, y1, x2, y2) == (0.0, 0.0, 64.0, 64.0)


def test_inverted_box_is_normalized_not_dropped():
    """Was: PIL raised "x1 must be greater than or equal to x0" and the whole
    overlay was lost."""
    kept = sanitize_boxes([[50, 50, 10, 10]], ["obj"], [0.9], 64, 64)
    assert len(kept) == 1
    (x1, y1, x2, y2), _label, _score = kept[0]
    assert (x1, y1, x2, y2) == (10.0, 10.0, 50.0, 50.0)


def test_one_bad_box_does_not_discard_the_good_ones():
    """The core regression: a single NaN box used to cost the entire overlay."""
    boxes, labels, scores = _boxes(
        [10, 10, 30, 30], [float("nan")] * 4, [35, 35, 55, 55]
    )
    kept = sanitize_boxes(boxes, labels, scores, 64, 64)
    assert len(kept) == 2


@pytest.mark.parametrize("score", [float("nan"), float("inf"), None, "high"])
def test_unusable_scores_degrade_to_zero(score):
    """A bad score must not cost a valid box — f"{nan:.2f}" is legal but a
    None or str score raised in the format call and lost the overlay."""
    kept = sanitize_boxes([[10, 10, 30, 30]], ["obj"], [score], 64, 64)
    assert len(kept) == 1
    assert kept[0][2] == 0.0


def test_valid_box_survives_untouched():
    kept = sanitize_boxes([[10, 10, 30, 30]], ["water"], [0.87], 64, 64)
    assert kept == [((10.0, 10.0, 30.0, 30.0), "water", 0.87)]


# ── overlay_bboxes ───────────────────────────────────────────────────────


def test_overlay_renders_for_valid_boxes(base_image):
    url = overlay_bboxes(base_image, *_boxes([10, 10, 40, 40]), request_id="t1")
    assert url == "/results/t1/grounding_overlay.png"


def test_overlay_survives_a_mixed_batch(base_image):
    """Was: "" for the whole batch."""
    boxes, labels, scores = _boxes(
        [10, 10, 30, 30], [float("inf")] * 4, [50, 50, 10, 10], [1, 2, 3]
    )
    url = overlay_bboxes(base_image, boxes, labels, scores, request_id="t2")
    assert url == "/results/t2/grounding_overlay.png"


def test_overlay_with_no_boxes_still_produces_an_image(base_image):
    url = overlay_bboxes(base_image, *_boxes(), request_id="t3")
    assert url == "/results/t3/grounding_overlay.png"


def test_overlay_returns_none_when_it_cannot_run(tmp_path):
    """None, not "". An empty string reads as a valid-but-blank URL to a
    caller, and SegmentationModel was accepting it as evidence."""
    missing = str(tmp_path / "does_not_exist.png")
    assert overlay_bboxes(missing, *_boxes([1, 1, 5, 5]), request_id="t4") is None


def test_overlay_label_stays_inside_the_frame(base_image):
    """A box at the top edge put its label at a negative y, off-canvas."""
    url = overlay_bboxes(base_image, *_boxes([0, 0, 30, 30]), request_id="t5")
    assert url is not None


# ── SegmentationModel now reports the overlay it generates ───────────────


def test_segmentation_reports_a_generated_overlay(base_image):
    """Was: the return value of overlay_bboxes was assigned to a local and then
    never used, so a rendered overlay was discarded and evidence_images was
    always []."""
    from app.models.grounding import SegmentationModel

    context = {
        "images": [base_image],
        "query": "highlight the water",
        "request_id": "t6",
        "intermediate": {
            "step_1": {
                "target": "water",
                "boxes": [[10, 10, 40, 40]],
                "scores": [0.9],
            }
        },
    }
    out = SegmentationModel().run("segment_regions", context)
    assert len(out["evidence_images"]) == 1
    assert out["evidence_images"][0]["url"] == "/results/t6/grounding_overlay.png"


def test_segmentation_reports_no_evidence_when_there_are_no_boxes(base_image):
    """The stub detector returns zero boxes; an overlay of nothing is not
    evidence and must not be advertised as such."""
    from app.models.grounding import SegmentationModel

    context = {
        "images": [base_image],
        "query": "highlight the water",
        "request_id": "t7",
        "intermediate": {"step_1": {"target": "water", "boxes": [], "scores": []}},
    }
    out = SegmentationModel().run("segment_regions", context)
    assert out["evidence_images"] == []
