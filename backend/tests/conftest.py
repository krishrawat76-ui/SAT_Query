"""
Shared pytest fixtures.

Puts `backend/` on sys.path once for every test module (the pre-existing test
files do their own sys.path insert; that stays harmless and idempotent).
"""

import sys
from pathlib import Path

import pytest

BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))


@pytest.fixture
def tiny_png(tmp_path):
    """A real 32x32 PNG on disk — enough for InputValidator to open it."""
    from PIL import Image

    path = tmp_path / "tiny.png"
    Image.new("RGB", (32, 32), (10, 20, 30)).save(path)
    return path


class FakeModel:
    """Model wrapper stand-in with controllable timing and telemetry."""

    def __init__(self, *, run_delay=0.0, telemetry=None, raises=None):
        self.run_delay = run_delay
        self.telemetry = telemetry
        self.raises = raises
        self.last_telemetry = None
        self.calls = []

    def run(self, action, context):
        import time

        self.calls.append(action)
        if self.run_delay:
            time.sleep(self.run_delay)
        if self.raises:
            raise self.raises
        # Only "capable" models report telemetry; the rest leave it None.
        if self.telemetry is not None:
            self.last_telemetry = self.telemetry
        return {"answer": f"ran {action}", "confidence": None}


class FakeRegistry:
    """Registry stand-in that records loads and can simulate slow loading."""

    def __init__(self, models=None, *, load_delay=0.0, load_raises=None):
        self._models = models or {}
        self.load_delay = load_delay
        self.load_raises = load_raises
        self._loaded: set = set()
        self.get_calls: list = []

    def get(self, name):
        import time

        self.get_calls.append(name)
        if name not in self._loaded:
            if self.load_delay:
                time.sleep(self.load_delay)
            if self.load_raises:
                raise self.load_raises
            self._loaded.add(name)
        return self._models[name]

    def list_loaded(self):
        return list(self._loaded)

    def describe(self, name):
        return {
            "registered": name in self._models,
            "loaded": name in self._loaded,
            "vram_gb": 1.0 if name in self._models else None,
            "version": getattr(self._models.get(name), "version", None),
        }


@pytest.fixture
def fake_model_factory():
    return FakeModel


@pytest.fixture
def fake_registry_factory():
    return FakeRegistry


@pytest.fixture
def client():
    """TestClient with the real app lifespan (builds the real registry)."""
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as c:
        yield c
