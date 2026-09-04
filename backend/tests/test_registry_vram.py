"""
Regression lock for the VRAM/CUDA path.

`_ensure_vram` and the health endpoint previously called
`torch.cuda.get_device_properties(0).total_mem` — the real attribute is
`total_memory`. Since `_ensure_vram` catches only ImportError, that
AttributeError escaped `_load()` and made *every* model load fail on a real
CUDA box. No CPU-only test run can reach that code, so these tests inject a
fake torch to exercise it.
"""

import sys
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest

from app.models.registry import ModelRegistry


class _FakeCuda:
    def __init__(self, free_gb=2.0, total_gb=8.0):
        self.free_b = int(free_gb * 1e9)
        self.total_b = int(total_gb * 1e9)
        self.empty_cache_calls = 0

    def is_available(self):
        return True

    def mem_get_info(self):
        return (self.free_b, self.total_b)

    def memory_allocated(self):
        return self.total_b - self.free_b

    def empty_cache(self):
        self.empty_cache_calls += 1

    def get_device_properties(self, _index):
        # Deliberately exposes ONLY the correct attribute name, so any
        # reintroduction of `.total_mem` fails loudly here.
        class Props:
            total_memory = self.total_b

        return Props()


class _FakeTorch:
    def __init__(self, cuda):
        self.cuda = cuda


@pytest.fixture
def fake_torch():
    cuda = _FakeCuda()
    module = _FakeTorch(cuda)
    with mock.patch.dict(sys.modules, {"torch": module}):
        yield module


def test_ensure_vram_runs_on_a_cuda_box(fake_torch):
    """The regression: this raised AttributeError before the fix."""
    registry = ModelRegistry()
    registry.register("small", lambda: object(), vram_gb=0.5)

    model = registry.get("small")

    assert model is not None
    assert "small" in registry.list_loaded()


def test_models_are_unloaded_when_vram_is_tight(fake_torch):
    """Only 2 GB free, and the incoming model wants 5.5 GB — the resident
    model must be evicted rather than the load failing."""
    fake_torch.cuda.free_b = int(2.0 * 1e9)

    registry = ModelRegistry()
    registry.register("resident", lambda: object(), vram_gb=1.0)
    registry.register("big", lambda: object(), vram_gb=5.5)

    registry.get("resident")
    assert registry.list_loaded() == ["resident"]

    # Freeing the resident model makes room, from the driver's perspective.
    def _free_on_unload(name):
        fake_torch.cuda.free_b = int(7.0 * 1e9)
        return original_unload(name)

    original_unload = registry.unload
    registry.unload = _free_on_unload

    registry.get("big")

    assert "big" in registry.list_loaded()
    assert "resident" not in registry.list_loaded()


def test_health_endpoint_reports_gpu_memory(fake_torch, client):
    """/api/health used the same broken attribute and would 500."""
    res = client.get("/api/health")

    assert res.status_code == 200
    body = res.json()
    assert body["gpu_available"] is True
    # 8 GB total, 2 GB free → 6 GB used.
    assert "6.0 / 8.0 GB" == body["gpu_memory_used"]


def test_describe_reports_registry_truth():
    registry = ModelRegistry()
    registry.register("known", lambda: object(), vram_gb=0.7)

    unknown = registry.describe("nope")
    assert unknown["registered"] is False
    assert unknown["vram_gb"] is None

    known = registry.describe("known")
    assert known["registered"] is True
    assert known["loaded"] is False
    assert known["vram_gb"] == 0.7
    # No wrapper declares a version today — this must stay null, not "1.0".
    assert known["version"] is None

    registry.get("known")
    assert registry.describe("known")["loaded"] is True
