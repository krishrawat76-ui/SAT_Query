"""
Tests for the payload sanitizer.

This is the only genuinely new algorithm in the telemetry work, and it runs
on arbitrary model output, so it gets the most coverage. The overriding
requirement: it must never raise, because a debug feature must not be able
to fail a request.
"""

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest

from app.output.sanitize import MAX_ITEMS, MAX_STRING, sanitize_payload


def test_plain_values_pass_through():
    result = sanitize_payload({"a": 1, "b": True, "c": None, "d": "hi", "e": 1.5})
    assert result["value"] == {"a": 1, "b": True, "c": None, "d": "hi", "e": 1.5}


def test_non_finite_floats_become_null():
    """FastAPI emits bare NaN/Infinity, which is invalid JSON and throws in
    JSON.parse on the client."""
    result = sanitize_payload({"nan": float("nan"), "inf": float("inf"), "ninf": float("-inf")})
    assert result["value"] == {"nan": None, "inf": None, "ninf": None}
    # Must be strictly valid JSON.
    json.loads(json.dumps(result["value"], allow_nan=False))


def test_numpy_array_is_summarized_not_dumped():
    np = pytest.importorskip("numpy")
    arr = np.zeros((512, 512), dtype="uint8")
    result = sanitize_payload({"change_mask": arr})
    summary = result["value"]["change_mask"]

    assert summary["__type__"] == "ndarray"
    assert summary["shape"] == [512, 512]
    assert summary["dtype"] == "uint8"
    assert summary["size"] == 262144
    assert summary["min"] == 0 and summary["max"] == 0
    # The whole point: we did not serialize 262 144 numbers.
    assert result["bytes"] < 1000


def test_numpy_scalar_becomes_python_number():
    np = pytest.importorskip("numpy")
    result = sanitize_payload({"ratio": np.float32(0.25)})
    assert result["value"]["ratio"] == pytest.approx(0.25)


def test_numpy_nan_scalar_becomes_null():
    np = pytest.importorskip("numpy")
    result = sanitize_payload({"ratio": np.float32("nan")})
    assert result["value"]["ratio"] is None


def test_long_string_is_truncated_and_stays_a_string():
    result = sanitize_payload({"s": "x" * (MAX_STRING + 100)})
    value = result["value"]["s"]
    assert isinstance(value, str)
    assert "truncated" in value
    assert len(value) < MAX_STRING + 60


def test_long_list_is_truncated_with_a_count():
    result = sanitize_payload({"items": list(range(500))})
    items = result["value"]["items"]
    assert len(items) == MAX_ITEMS + 1
    assert items[-1] == {"__truncated__": 500 - MAX_ITEMS}


def test_large_dict_is_truncated_with_a_count():
    result = sanitize_payload({str(i): i for i in range(100)})
    assert result["value"]["__truncated__"] == 100 - MAX_ITEMS


def test_deep_nesting_hits_the_depth_marker():
    obj = current = {}
    for _ in range(12):
        current["next"] = {}
        current = current["next"]

    result = sanitize_payload(obj)
    blob = json.dumps(result["value"])
    assert "max depth" in blob


def test_self_referential_dict_terminates():
    obj = {"name": "loop"}
    obj["self"] = obj

    result = sanitize_payload(obj)
    assert result["value"]["self"] == {"__cycle__": True}


def test_self_referential_list_terminates():
    items = [1, 2]
    items.append(items)

    result = sanitize_payload({"items": items})
    assert result["value"]["items"][-1] == [{"__cycle__": True}]


def test_repr_that_raises_does_not_propagate():
    class Hostile:
        def __repr__(self):
            raise RuntimeError("nope")

    result = sanitize_payload({"bad": Hostile()})
    assert result["value"]["bad"]["__type__"] == "Hostile"


def test_bytes_are_summarized():
    result = sanitize_payload({"blob": b"\x00" * 4096})
    assert result["value"]["blob"] == {"__type__": "bytes", "len": 4096}


def test_path_is_stringified():
    """Plain path string, not the noisier PosixPath(...) repr — image paths
    appear in almost every step output."""
    result = sanitize_payload({"p": Path("/tmp/x.png")})
    assert result["value"]["p"] == "/tmp/x.png"


def test_pil_image_is_summarized():
    Image = pytest.importorskip("PIL.Image")
    img = Image.new("RGB", (8, 4))
    result = sanitize_payload({"img": img})
    assert result["value"]["img"]["__type__"] == "PIL.Image"
    assert result["value"]["img"]["size"] == [8, 4]
    assert result["value"]["img"]["mode"] == "RGB"


def test_oversized_payload_becomes_a_truthful_summary():
    """Per-container item caps run first, so the byte budget is only reached
    by structures that survive them — here 25 keys x 25 long strings."""
    payload = {
        f"key_{i}": ["y" * (MAX_STRING - 1) for _ in range(MAX_ITEMS)]
        for i in range(MAX_ITEMS)
    }
    result = sanitize_payload(payload)

    assert result["value"]["__omitted__"] == "payload exceeded size budget"
    # The reported size is the real serialized size, not a guess.
    assert result["bytes"] == result["value"]["bytes"]
    assert result["bytes"] > 32_768
    assert len(result["value"]["top_level_keys"]) <= MAX_ITEMS


def test_flat_payload_under_budget_is_kept_intact():
    """The item caps normally keep payloads well under the byte budget, so
    the __omitted__ path stays rare rather than swallowing ordinary output."""
    result = sanitize_payload({f"key_{i}": "y" * 400 for i in range(200)})
    assert "__omitted__" not in result["value"]
    assert result["value"]["__truncated__"] == 200 - MAX_ITEMS


def test_result_is_always_json_serializable():
    np = pytest.importorskip("numpy")

    class Weird:
        pass

    payload = {
        "arr": np.ones((4, 4)),
        "nan": float("nan"),
        "obj": Weird(),
        "nested": {"bytes": b"abc", "path": Path("/tmp")},
    }
    result = sanitize_payload(payload)
    json.dumps(result["value"], allow_nan=False)


def test_wide_dag_is_bounded_by_the_node_budget():
    """A DAG, not a cycle: `x = [x] * 25` repeated builds ~7 objects that the
    item/depth caps alone would expand to 25**6 ≈ 244M nodes, because sibling
    branches each legitimately re-expand the shared child. The size cap can't
    prevent that — it only runs after the whole tree is built. Sanitizing
    happens inside the request handler, so an unbounded walk stalls the event
    loop; this must terminate quickly."""
    x = [1] * 25
    for _ in range(6):
        x = [x] * 25

    started = time.perf_counter()
    result = sanitize_payload(x)
    elapsed = time.perf_counter() - started

    # Generous bound — the point is "fast", not a precise budget.
    assert elapsed < 5.0, f"sanitize took {elapsed:.1f}s on a ~200-byte DAG"
    assert "value" in result
    json.dumps(result["value"], allow_nan=False)


def test_sanitizer_never_raises_on_pathological_input():
    class ExplodingDict(dict):
        def items(self):
            raise RuntimeError("boom")

    result = sanitize_payload(ExplodingDict())
    # Either it degraded gracefully or it reported the error — never raised.
    assert "value" in result and "bytes" in result
