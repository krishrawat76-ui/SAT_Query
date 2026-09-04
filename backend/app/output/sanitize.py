"""
Payload sanitizer — makes arbitrary model outputs JSON-safe and size-bounded.

`StepResult.output` is whatever a model wrapper returned: nested dicts that
may hold numpy arrays (change masks, class maps), PIL images, Paths, bytes,
NaN floats, or objects with no JSON representation at all. This converts any
of that into something `json.dumps` can handle and a browser can render —
without ever raising, and without ever emitting a value it did not observe.

Used only for the debug `payload_snapshot` in the execution trace, so it runs
off the hot path and never affects the actual answer.
"""

import json
import math
from pathlib import PurePath
from typing import Any

# Caps chosen so a snapshot stays readable in a UI panel rather than
# faithful to the last byte — a truncation marker is more useful than
# 262 144 pixel values.
MAX_STRING = 512
MAX_ITEMS = 25
MAX_DEPTH = 6
MAX_TOTAL_BYTES = 32_768
# Hard ceiling on how many values the walk will visit, checked DURING
# traversal. The size cap above bounds the output but not the work: the item
# and depth caps still permit 25**6 ≈ 244M nodes, and a ~200-byte DAG
# (`x = [x] * 25` repeated) hits that, because sibling branches legitimately
# re-expand a shared child. Sanitizing runs synchronously inside the request
# handler, so an unbounded walk stalls the whole event loop. ~20k nodes is far
# more than any readable snapshot needs.
MAX_NODES = 20_000
# Above this element count, computing min/max/mean over an array costs more
# than the debug value it provides.
ARRAY_STATS_MAX_SIZE = 4_000_000


def _summarize_array(obj: Any) -> dict:
    """Shape/dtype summary for a numpy-like array, with stats when cheap.

    Duck-typed on `shape`/`dtype` rather than importing numpy, so this module
    stays dependency-free and also handles torch tensors and anything else
    array-shaped.
    """
    summary: dict = {"__type__": "ndarray"}
    try:
        summary["shape"] = [int(d) for d in obj.shape]
        summary["dtype"] = str(obj.dtype)
        size = 1
        for d in summary["shape"]:
            size *= d
        summary["size"] = size

        if 0 < size <= ARRAY_STATS_MAX_SIZE:
            summary["min"] = _coerce_number(obj.min())
            summary["max"] = _coerce_number(obj.max())
            summary["mean"] = _coerce_number(obj.mean())
    except Exception as e:  # pragma: no cover - defensive
        summary["__summary_error__"] = str(e)
    return summary


def _coerce_number(value: Any) -> Any:
    """Numpy scalar → Python number, with non-finite floats nulled."""
    try:
        if hasattr(value, "item"):
            value = value.item()
        if isinstance(value, float) and not math.isfinite(value):
            return None
        return value
    except Exception:  # pragma: no cover - defensive
        return None


def _is_array_like(obj: Any) -> bool:
    return hasattr(obj, "shape") and hasattr(obj, "dtype")


def _is_pil_image(obj: Any) -> bool:
    return hasattr(obj, "size") and hasattr(obj, "mode") and hasattr(obj, "getbands")


def _sanitize(obj: Any, depth: int, seen: set, budget: list) -> Any:
    # Decremented on every visited value, not just containers, so the walk is
    # bounded by total work rather than by shape. See MAX_NODES.
    budget[0] -= 1
    if budget[0] < 0:
        return {"__truncated__": "node budget exhausted"}

    if obj is None or isinstance(obj, (bool, int)):
        return obj

    if isinstance(obj, float):
        # FastAPI serializes bare NaN/Infinity, which is invalid JSON and
        # throws in JSON.parse on the client.
        return obj if math.isfinite(obj) else None

    if isinstance(obj, str):
        if len(obj) > MAX_STRING:
            return f"{obj[:MAX_STRING]}… [+{len(obj) - MAX_STRING} chars truncated]"
        return obj

    if isinstance(obj, (bytes, bytearray)):
        return {"__type__": "bytes", "len": len(obj)}

    if isinstance(obj, PurePath):
        # Plain path string rather than the noisier PosixPath(...) repr —
        # these show up constantly in step outputs (image paths, result dirs).
        return str(obj)

    if _is_array_like(obj):
        # 0-d arrays and numpy scalars are values, not collections.
        if getattr(obj, "shape", None) == ():
            return _coerce_number(obj)
        return _summarize_array(obj)

    if hasattr(obj, "item") and not hasattr(obj, "__len__"):
        return _coerce_number(obj)

    if _is_pil_image(obj):
        try:
            return {"__type__": "PIL.Image", "size": list(obj.size), "mode": obj.mode}
        except Exception:  # pragma: no cover - defensive
            return {"__type__": "PIL.Image"}

    if depth >= MAX_DEPTH:
        return {"__truncated__": "max depth"}

    if isinstance(obj, dict):
        if id(obj) in seen:
            return {"__cycle__": True}
        seen = seen | {id(obj)}
        out: dict = {}
        for i, (key, value) in enumerate(obj.items()):
            if i >= MAX_ITEMS:
                out["__truncated__"] = len(obj) - MAX_ITEMS
                break
            out[str(key)] = _sanitize(value, depth + 1, seen, budget)
        return out

    if isinstance(obj, (list, tuple, set, frozenset)):
        if id(obj) in seen:
            return [{"__cycle__": True}]
        seen = seen | {id(obj)}
        items = list(obj)
        out_list = [_sanitize(v, depth + 1, seen, budget) for v in items[:MAX_ITEMS]]
        if len(items) > MAX_ITEMS:
            out_list.append({"__truncated__": len(items) - MAX_ITEMS})
        return out_list

    # Path, custom objects, anything else — repr can itself raise.
    try:
        return {"__type__": type(obj).__name__, "repr": repr(obj)[:MAX_STRING]}
    except Exception:  # pragma: no cover - defensive
        return {"__type__": type(obj).__name__}


def sanitize_payload(obj: Any, *, max_total_bytes: int = MAX_TOTAL_BYTES) -> dict:
    """Return ``{"value": <json-safe>, "bytes": <serialized size>}``.

    Never raises: a debug feature must not be able to fail a request.
    """
    try:
        safe = _sanitize(obj, depth=0, seen=set(), budget=[MAX_NODES])
        encoded = json.dumps(safe, default=str, allow_nan=False)
        size = len(encoded)

        if size > max_total_bytes:
            top_level_keys = (
                [str(k) for k in list(obj.keys())[:MAX_ITEMS]]
                if isinstance(obj, dict)
                else []
            )
            safe = {
                "__omitted__": "payload exceeded size budget",
                "bytes": size,
                "top_level_keys": top_level_keys,
            }

        return {"value": safe, "bytes": size}
    except Exception as e:
        # `bytes: None`, not 0 — 0 would assert "this payload was empty",
        # which is a measurement we did not make. Unknown is null.
        return {"value": {"__sanitizer_error__": str(e)}, "bytes": None}
