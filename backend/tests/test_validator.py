"""
Tests for InputValidator — format, count, modality, and edge case validation.
"""

import sys
import os
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from PIL import Image

from app.agent.validator import InputValidator


def _create_test_image(suffix=".png", size=(256, 256)):
    """Helper: create a temporary test image."""
    tmp = tempfile.NamedTemporaryFile(suffix=suffix, delete=False)
    img = Image.new("RGB", size, color=(100, 150, 200))
    img.save(tmp.name)
    return tmp.name


def test_single_valid_image():
    """Accept a single valid PNG image."""
    validator = InputValidator()
    path = _create_test_image(".png")
    result = validator.validate([path])
    assert result.is_valid
    assert result.num_images == 1
    assert result.modalities == ["optical"]
    assert not result.is_temporal
    assert not result.is_cross_modal
    os.unlink(path)


def test_two_valid_images_temporal():
    """Accept two valid images as temporal pair."""
    validator = InputValidator()
    p1 = _create_test_image(".png")
    p2 = _create_test_image(".jpg")
    result = validator.validate([p1, p2], {"modalities": ["optical", "optical"]})
    assert result.is_valid
    assert result.num_images == 2
    assert result.is_temporal
    assert not result.is_cross_modal
    os.unlink(p1)
    os.unlink(p2)


def test_two_images_cross_modal():
    """Detect cross-modal when modalities are optical + sar."""
    validator = InputValidator()
    p1 = _create_test_image(".png")
    p2 = _create_test_image(".tif")
    result = validator.validate([p1, p2], {"modalities": ["optical", "sar"]})
    assert result.is_valid
    assert result.is_cross_modal
    assert not result.is_temporal
    os.unlink(p1)
    os.unlink(p2)


def test_allow_no_images():
    """0 images is valid — a text-only conversational query, routed to the
    VQA task's no-image path instead of an image pipeline (see RuleBasedRouter)."""
    validator = InputValidator()
    result = validator.validate([])
    assert result.is_valid
    assert result.num_images == 0
    assert result.errors == []


def test_reject_three_images():
    """Reject more than 2 images."""
    validator = InputValidator()
    paths = [_create_test_image() for _ in range(3)]
    result = validator.validate(paths)
    assert not result.is_valid
    assert any("Maximum 2" in e for e in result.errors)
    for p in paths:
        os.unlink(p)


def test_reject_unsupported_format():
    """Reject files with unsupported extensions."""
    validator = InputValidator()
    tmp = tempfile.NamedTemporaryFile(suffix=".docx", delete=False)
    tmp.write(b"not an image")
    tmp.close()
    result = validator.validate([tmp.name])
    assert not result.is_valid
    assert any("Unsupported format" in e for e in result.errors)
    os.unlink(tmp.name)


def test_accept_tiff():
    """Accept TIFF format."""
    validator = InputValidator()
    path = _create_test_image(".tiff")
    result = validator.validate([path])
    assert result.is_valid
    os.unlink(path)


def test_accept_jpeg():
    """Accept JPEG format."""
    validator = InputValidator()
    path = _create_test_image(".jpeg")
    result = validator.validate([path])
    assert result.is_valid
    os.unlink(path)


def test_default_modality_optical():
    """Default modality is optical when none specified."""
    validator = InputValidator()
    path = _create_test_image()
    result = validator.validate([path])
    assert result.modalities == ["optical"]
    os.unlink(path)


def test_format_info_populated():
    """format_info includes size and band info."""
    validator = InputValidator()
    path = _create_test_image(".png", size=(512, 512))
    result = validator.validate([path])
    assert len(result.format_info) == 1
    assert result.format_info[0]["size"] == [512, 512]
    assert result.format_info[0]["bands"] == 3
    os.unlink(path)


def test_validate_empty_query():
    """Reject empty query."""
    validator = InputValidator()
    valid, error = validator.validate_query("")
    assert not valid
    assert "empty" in error.lower()


def test_validate_short_query():
    """Reject very short query."""
    validator = InputValidator()
    valid, error = validator.validate_query("hi")
    assert not valid


def test_validate_valid_query():
    """Accept normal query."""
    validator = InputValidator()
    valid, error = validator.validate_query("What objects are present in this image?")
    assert valid
    assert error == ""


def test_temporal_warning_no_dates():
    """Warn when bi-temporal but no dates provided."""
    validator = InputValidator()
    p1 = _create_test_image()
    p2 = _create_test_image()
    result = validator.validate([p1, p2], {"modalities": ["optical", "optical"]})
    assert result.is_valid
    assert any("dates" in w.lower() for w in result.warnings)
    os.unlink(p1)
    os.unlink(p2)
