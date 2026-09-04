"""
API Schemas — Pydantic request/response models.

Agreed contract between M1 (Backend), M2 (Frontend), M3 (Agent).
"""

from pydantic import BaseModel, Field
from typing import Any, Optional


class EvidenceImage(BaseModel):
    """A generated evidence image (change map, overlay, etc.)."""
    type: str
    url: str
    caption: str


class BoundingRegion(BaseModel):
    """A detected bounding region with label and confidence."""
    bbox: list[float]
    label: str
    confidence: float


class Evidence(BaseModel):
    """Collection of evidence: images and detected regions."""
    images: list[EvidenceImage] = []
    regions: list[BoundingRegion] = []


class ModelTelemetry(BaseModel):
    """Real, model-reported inference counters.

    Populated only by wrappers that can genuinely measure them — today that
    is QwenVLMWrapper on a machine with weights present. Every stub wrapper
    and every no-weights fallback leaves this None rather than guessing.
    """
    prompt_tokens: Optional[int] = None
    completion_tokens: Optional[int] = None
    generation_time_ms: Optional[float] = None
    tokens_per_sec: Optional[float] = None
    max_new_tokens: Optional[int] = None
    device: Optional[str] = None


class PipelineStep(BaseModel):
    """A single step in the execution pipeline."""
    step: int
    model: str
    action: str
    status: str
    # Total wall clock for the step (load + inference) — unchanged meaning.
    time_ms: float
    error: Optional[str] = None

    # ── Telemetry (Phase 4), all measured ──
    # Time inside ModelRegistry.get(). Previously folded into time_ms and
    # misreported as inference cost.
    load_time_ms: float = 0.0
    inference_time_ms: float = 0.0
    # False when this step paid a cold load; explains load_time_ms spikes.
    model_was_cached: bool = True
    # Offset from pipeline start, so a waterfall shows real gaps rather than
    # assuming steps are contiguous.
    started_at_ms: float = 0.0
    telemetry: Optional[ModelTelemetry] = None
    # JSON-safe, size-bounded view of the step's raw output. None unless the
    # request opted into debug mode.
    payload_snapshot: Optional[Any] = None
    payload_bytes: Optional[int] = None
    # Reserved for a future DAG executor. The current executor is a strictly
    # linear loop, so this stays None rather than synthesizing [n-1].
    depends_on: Optional[list[int]] = None


class ValidationInfo(BaseModel):
    """Input validation details for the execution trace."""
    image_count: int
    format: list[str]
    modality: list[str]
    temporal: bool
    cross_modal: bool
    compatible: bool
    warnings: list[str] = []


class SelectedModel(BaseModel):
    """A model the router selected, with its real registry state."""
    name: str
    # The pipeline actions this model was actually assigned, in step order.
    actions: list[str] = []
    steps: list[int] = []
    # Registry facts, read at trace time — not invented. None when no registry
    # was available to ask, rather than an optimistic default.
    registered: Optional[bool] = None
    loaded: Optional[bool] = None
    vram_gb: Optional[float] = None
    # No wrapper exposes a version string today (the registry stores only a
    # loader and a VRAM estimate). Previously hardcoded "1.0"; now honestly
    # null until a wrapper declares one.
    version: Optional[str] = None
    # Mechanically composed from the router's own rule and this model's
    # assigned actions — never hand-written per-model justification prose.
    selection_reason: str = ""


class RouterMetadata(BaseModel):
    """How the routing decision was actually produced.

    Split deliberately into two halves: fields the in-repo RuleBasedRouter
    can genuinely report, and fields only an LLM planner could report. The
    latter are Optional and are null in this repo — they exist so a future
    LLM-planner router can populate them without a breaking schema change.
    They are never filled with placeholder values.
    """
    # ── Real: the router that actually ran ──
    router_type: str
    router_version: str
    rule_id: str
    matched_rule: str
    matched_keywords: list[str] = []
    fallback_used: bool = False
    routing_time_ms: float = 0.0

    # ── Optional: only an LLM planner can report these ──
    # This repo's router is deterministic keyword matching with zero VRAM and
    # no language model in the control path, so all of these are null here.
    planner_type: Optional[str] = None
    planning_time_ms: Optional[float] = None
    prompt_tokens: Optional[int] = None
    completion_tokens: Optional[int] = None
    tokens_per_sec: Optional[float] = None
    intent_decomposition: Optional[list[dict]] = None
    planner_raw_output: Optional[str] = None


class StageTimings(BaseModel):
    """Wall-clock breakdown of the request handler. All measured."""
    upload_ms: float = 0.0
    validation_ms: float = 0.0
    routing_ms: float = 0.0
    execution_ms: float = 0.0
    integration_ms: float = 0.0
    # Sum of PipelineStep.time_ms — what total_time_ms used to (wrongly) be.
    pipeline_steps_ms: float = 0.0
    # total_time_ms minus the measured stages: trace building, response
    # assembly, and everything else inside the handler.
    other_ms: float = 0.0


class ImageComposition(BaseModel):
    """Per-image facts, straight from InputValidator.format_info."""
    filename: str = ""
    width: int = 0
    height: int = 0
    bands: int = 0
    format: str = "unknown"
    file_size_mb: float = 0.0
    modality: Optional[str] = None
    # Client-supplied capture date, when the caller sent `dates`.
    date: Optional[str] = None


class InputComposition(BaseModel):
    """What actually arrived, in more detail than ValidationInfo."""
    images: list[ImageComposition] = []
    total_pixels: int = 0
    total_size_mb: float = 0.0
    is_temporal: bool = False
    is_cross_modal: bool = False
    # The backend never reads GeoTIFF CRS today (EPSG is parsed and then
    # discarded client-side in geotiffClient.ts). Null until that moves
    # server-side — never assumed to be EPSG:4326.
    crs: Optional[str] = None


class ExecutionTrace(BaseModel):
    """Full execution trace — makes agent decisions transparent."""
    input_validation: ValidationInfo
    detected_task: str
    # None when the router had no real confidence to report (the
    # rule-based router is deterministic keyword matching, not a learned
    # model) — never a fabricated number.
    task_confidence: Optional[float] = None
    reasoning: str
    selected_models: list[SelectedModel]
    pipeline_steps: list[PipelineStep]
    # Server-side handler wall clock: upload read → response assembled.
    # Previously this was sum(step.time_ms), which excluded upload,
    # validation, routing and integration and so was never request latency.
    # The old figure is preserved as timings.pipeline_steps_ms.
    total_time_ms: float

    # ── Added in Phase 4 ──
    request_id: Optional[str] = None
    router_metadata: Optional[RouterMetadata] = None
    timings: Optional[StageTimings] = None
    input_composition: Optional[InputComposition] = None
    # True when this request opted into payload snapshots.
    debug: bool = False


class AnalysisResponse(BaseModel):
    """Complete API response for POST /api/analyze."""
    answer: str
    # None when no pipeline step reported a real confidence score (every
    # stub/no-weights model path) — never a fabricated placeholder number.
    confidence: Optional[float] = None
    evidence: Evidence
    execution_trace: ExecutionTrace


class HealthResponse(BaseModel):
    """Response for GET /api/health."""
    status: str
    models_loaded: list[str]
    gpu_available: bool
    gpu_memory_used: Optional[str] = None
    registered_models: Optional[list[dict]] = None


class RasterBBox(BaseModel):
    """4-corner geographic bounding box, in decimal degrees."""
    north: float
    south: float
    east: float
    west: float


class RasterLayers(BaseModel):
    """URLs for the map's raster layers, served from /results.

    Only `base` (the real uploaded image) is generated today. The other two
    are `None` until a real model actually produces one — a TinyCD change
    map for `structural_changes`, a real spectral/false-color pipeline for
    `spectral_bands` — never a fabricated placeholder image standing in for
    either. Both used to be fixed image transforms applied identically to
    any upload regardless of content; that fabricated version was deleted
    outright. This time the fields stay in the contract, honestly null,
    so a real model can populate them later with no schema change, the
    same pattern already used for `task_confidence`/`confidence` and the
    LLM-planner fields in `RouterMetadata`.
    """
    base: str
    structural_changes: Optional[str] = None
    spectral_bands: Optional[str] = None


class ProcessRasterResponse(BaseModel):
    """Complete API response for POST /api/process-raster (Phase 3 stub)."""
    bbox: RasterBBox
    center: list[float]  # [lng, lat]
    zoom: float
    layers: RasterLayers
    source: str  # "geotiff-tags" | "synthetic"
