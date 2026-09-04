"""
API Schemas — Pydantic request/response models.

Agreed contract between M1 (Backend), M2 (Frontend), M3 (Agent).
"""

from pydantic import BaseModel, Field
from typing import Optional


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


class PipelineStep(BaseModel):
    """A single step in the execution pipeline."""
    step: int
    model: str
    action: str
    status: str
    time_ms: float
    error: Optional[str] = None


class ValidationInfo(BaseModel):
    """Input validation details for the execution trace."""
    image_count: int
    format: list[str]
    modality: list[str]
    temporal: bool
    cross_modal: bool
    compatible: bool
    warnings: list[str] = []


class ExecutionTrace(BaseModel):
    """Full execution trace — makes agent decisions transparent."""
    input_validation: ValidationInfo
    detected_task: str
    # None when the router had no real confidence to report (the
    # rule-based router is deterministic keyword matching, not a learned
    # model) — never a fabricated number.
    task_confidence: Optional[float] = None
    reasoning: str
    selected_models: list[dict]
    pipeline_steps: list[PipelineStep]
    total_time_ms: float


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
    """URLs for the three stub analysis layers, served from /results."""
    base: str
    structural_changes: str
    spectral_bands: str


class ProcessRasterResponse(BaseModel):
    """Complete API response for POST /api/process-raster (Phase 3 stub)."""
    bbox: RasterBBox
    center: list[float]  # [lng, lat]
    zoom: float
    layers: RasterLayers
    source: str  # "geotiff-tags" | "synthetic"
