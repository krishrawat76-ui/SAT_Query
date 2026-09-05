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


@pytest.fixture(autouse=True)
def _isolate_node_state(tmp_path, monkeypatch):
    """Keep every test off the developer's real .satquery/device.json.

    HybridPipelineExecutor consults the live node registry before falling
    back to local execution, so a machine with real LAN pairing state left
    over from manual testing would silently route test requests to a real
    Model Host over the network (and time out) instead of exercising the
    mocked local registry the test actually set up.
    """
    monkeypatch.setattr(
        "app.node.config_store.satquery_dir",
        lambda: tmp_path / ".satquery",
    )
    import app.node.registry as reg_mod

    reg_mod._registry = None
    yield
    reg_mod._registry = None


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
def client(monkeypatch):
    """TestClient with the real app lifespan (builds the real registry).

    Pins routing/inference flags so API contract tests exercise the in-repo
    RuleBasedRouter + PipelineExecutor, independent of a developer's local
    Ollama / SKIP_MODEL_INFERENCE defaults.
    """
    from fastapi.testclient import TestClient

    from app.main import app
    from app.utils.config import settings

    monkeypatch.setattr(settings, "USE_SHIVEN_ROUTER", False)
    monkeypatch.setattr(settings, "SKIP_MODEL_INFERENCE", False)

    with TestClient(app) as c:
        yield c


@pytest.fixture
def rule_router(monkeypatch):
    """Pin the in-repo RuleBasedRouter for tests that assert its own contract.

    USE_SHIVEN_ROUTER defaults to true, so tests asserting rule_id values like
    "grounding_keywords" or "text_only", or that the LLM-planner fields are
    null, were passing only when Ollama happened to be unreachable AND the
    Shiven import happened to fail. They describe the rule router's behaviour,
    so they should select it rather than depend on the ambient environment.
    """
    from app.utils.config import settings

    monkeypatch.setattr(settings, "USE_SHIVEN_ROUTER", False)


@pytest.fixture
def real_models(monkeypatch):
    """Run the actual model wrappers instead of UnavailableModelExecutor.

    SKIP_MODEL_INFERENCE defaults to true, which bypasses ModelRegistry
    entirely — so a test that monkeypatches registry.get to inject a fake model
    would never see it called.
    """
    from app.utils.config import settings

    monkeypatch.setattr(settings, "SKIP_MODEL_INFERENCE", False)
