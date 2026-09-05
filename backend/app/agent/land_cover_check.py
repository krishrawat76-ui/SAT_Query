"""
Fast land-cover pre-check — gates whether a request needs the (slow, remote)
VLM at all.

Runs concurrently with query routing (see app/api/routes.py), not after it —
the whole point is to never pay for the routing→dispatch round trip serially
in front of a cheap, already-available answer. A scene the lightweight
segmentation model classifies as mostly Forest/Vegetation/Barren land needs
no further high-level reasoning from the VLM; one that fails the threshold —
or whose VLM call later times out/fails — falls back to the land-cover
breakdown itself rather than a bare error.

On "cancelling" the remote VLM request: the executor (HybridPipelineExecutor)
runs synchronously on the serialized inference lane, and Python has no safe
way to kill a running thread (see inference_lane.py's own docstring for the
same constraint). So "abort" here means "never start it" — the threshold is
evaluated from a concurrently-run check BEFORE dispatch, not by interrupting
an in-flight remote call. That is a strictly better outcome than a mid-flight
cancel would be anyway: no wasted round trip at all, rather than one
abandoned partway through.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from app.models.land_cover import LAND_CATEGORIES


@dataclass
class LandCoverResult:
    """Outcome of the fast land-cover check.

    `land_pct` is None when no real model is loaded (today, always — see
    LandCoverModel) — a missing value, never a fabricated 0.0 or 100.0.
    `available` mirrors that: False means "this check ran but had nothing
    real to report," not "this check failed."
    """

    breakdown: dict[str, Optional[float]] = field(default_factory=dict)
    land_pct: Optional[float] = None
    available: bool = False


def land_cover_result_from_raw(raw: object) -> LandCoverResult:
    """Build a LandCoverResult from a LandCoverModel.run() output.

    A wrapper is free to return anything from run() (see
    OutputIntegrator.integrate's own isinstance check for the same reason) —
    a non-dict here previously raised AttributeError and 500'd the whole
    request. Degrades to "unavailable" instead, exactly like every other
    caller of a model wrapper's output in this codebase.
    """
    if not isinstance(raw, dict):
        return LandCoverResult()
    land_pct = raw.get("land_pct")
    return LandCoverResult(
        breakdown=dict(raw.get("breakdown") or {}),
        land_pct=land_pct,
        available=land_pct is not None,
    )


def evaluate_threshold(result: LandCoverResult, threshold: float) -> Optional[bool]:
    """True (accept — proceed to the VLM) / False (fall back) / None (undecidable).

    None is deliberately not coerced to either outcome here — the caller
    decides what "undecidable" means for its own path. routes.py currently
    treats None as "proceed exactly as if this check never ran," so a stub
    with no real weights never blocks a real request.
    """
    if result.land_pct is None:
        return None
    return result.land_pct >= threshold


def fallback_answer(result: LandCoverResult, threshold: float) -> str:
    """User-facing text for a land-cover-driven fallback response."""
    parts = ", ".join(
        f"{cat}: {pct:.1f}%"
        for cat, pct in result.breakdown.items()
        if isinstance(pct, (int, float))
    )
    land_pct = result.land_pct if result.land_pct is not None else 0.0
    return (
        "High-level feature extraction was bypassed: the fast land-cover check "
        f"found {land_pct:.1f}% land cover ({'/'.join(LAND_CATEGORIES)}), below "
        f"the {threshold:.0f}% threshold used to decide whether a full model "
        f"analysis is warranted. Land-cover breakdown — {parts}."
    )
