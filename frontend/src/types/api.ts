// src/types/api.ts
// Mirrors backend/app/api/schemas.py exactly — keep in sync with any backend schema change.

export interface EvidenceImage {
    type: string;
    url: string;
    caption: string;
}

export interface BoundingRegion {
    bbox: number[];
    label: string;
    confidence: number;
}

export interface Evidence {
    images: EvidenceImage[];
    regions: BoundingRegion[];
}

/** Real, model-reported inference counters. Populated only by wrappers that
 * can genuinely measure them (QwenVLMWrapper, when weights are present) —
 * null on every stub/no-weights path, never a guess. */
export interface ModelTelemetry {
    prompt_tokens: number | null;
    completion_tokens: number | null;
    generation_time_ms: number | null;
    tokens_per_sec: number | null;
    max_new_tokens: number | null;
    device: string | null;
}

export interface PipelineStep {
    step: number;
    model: string;
    action: string;
    status: "success" | "error";
    // Total wall clock for the step (load + inference) — unchanged meaning.
    time_ms: number;
    error?: string | null;

    // ── Telemetry (Phase 4), all measured ──
    // Time inside ModelRegistry.get() on the backend. Previously folded into
    // time_ms and misreported as inference cost for a cold model load.
    load_time_ms: number;
    inference_time_ms: number;
    // False when this step paid a cold load; explains a load_time_ms spike.
    model_was_cached: boolean;
    // Offset from pipeline start, for waterfall rendering.
    started_at_ms: number;
    telemetry: ModelTelemetry | null;
    // JSON-safe, size-bounded view of the step's raw output. Null unless the
    // request opted into ?debug=true.
    payload_snapshot: unknown;
    payload_bytes: number | null;
    // Reserved for a future DAG executor — the current one is a strictly
    // linear loop, so this is always null, never a synthesized guess.
    depends_on: number[] | null;
}

export interface ValidationInfo {
    image_count: number;
    format: string[];
    modality: string[];
    temporal: boolean;
    cross_modal: boolean;
    compatible: boolean;
    warnings: string[];
}

export interface SelectedModel {
    name: string;
    // The pipeline actions this model was actually assigned, in step order.
    actions: string[];
    steps: number[];
    // Registry facts, read at trace time — not invented.
    registered: boolean;
    loaded: boolean;
    vram_gb: number | null;
    // No wrapper exposes a version string today — null until one does.
    // Previously a fabricated "1.0" for every model.
    version: string | null;
    // Mechanically composed from the router's own rule + this model's
    // assigned actions — never hand-written per-model justification prose.
    selection_reason: string;
}

/** How the routing decision was actually produced. The `router_type`
 * through `routing_time_ms` fields are real, reported by the in-repo
 * deterministic RuleBasedRouter. Everything from `planner_type` onward is
 * null in this repo — those fields exist only so a future LLM-planner
 * router can populate them without a breaking schema change; they are
 * never filled with placeholder values. */
export interface RouterMetadata {
    router_type: string;
    router_version: string;
    rule_id: string;
    matched_rule: string;
    matched_keywords: string[];
    fallback_used: boolean;
    routing_time_ms: number;

    planner_type: string | null;
    planning_time_ms: number | null;
    prompt_tokens: number | null;
    completion_tokens: number | null;
    tokens_per_sec: number | null;
    intent_decomposition: Record<string, unknown>[] | null;
    planner_raw_output: string | null;
}

/** Wall-clock breakdown of the request handler. All measured. */
export interface StageTimings {
    upload_ms: number;
    validation_ms: number;
    routing_ms: number;
    execution_ms: number;
    integration_ms: number;
    // Sum of PipelineStep.time_ms — what total_time_ms used to (wrongly) be.
    pipeline_steps_ms: number;
    // total_time_ms minus the measured stages above.
    other_ms: number;
}

/** Per-image facts, straight from InputValidator.format_info. */
export interface ImageComposition {
    filename: string;
    width: number;
    height: number;
    bands: number;
    format: string;
    file_size_mb: number;
    modality: string | null;
    date: string | null;
}

export interface InputComposition {
    images: ImageComposition[];
    total_pixels: number;
    total_size_mb: number;
    is_temporal: boolean;
    is_cross_modal: boolean;
    // The backend never reads GeoTIFF CRS today (EPSG is parsed and then
    // discarded client-side in geotiffClient.ts) — null, never assumed.
    crs: string | null;
}

export interface ExecutionTraceData {
    input_validation: ValidationInfo;
    detected_task: string;
    // null when the router had no real confidence to report (the rule-based
    // router is deterministic keyword matching, not a learned model) —
    // never a fabricated number.
    task_confidence: number | null;
    reasoning: string;
    selected_models: SelectedModel[];
    pipeline_steps: PipelineStep[];
    // Server-side handler wall clock. Previously sum(step.time_ms), which
    // excluded upload/validation/routing/integration and so was never
    // request latency — that old figure is preserved as
    // timings.pipeline_steps_ms.
    total_time_ms: number;

    request_id: string | null;
    router_metadata: RouterMetadata | null;
    timings: StageTimings | null;
    input_composition: InputComposition | null;
    // True when this request opted into payload snapshots.
    debug: boolean;
}

export interface AnalysisResponse {
    answer: string;
    // null when no pipeline step reported a real confidence score (every
    // stub/no-weights model path today) — never a fabricated placeholder.
    confidence: number | null;
    evidence: Evidence;
    execution_trace: ExecutionTraceData;
}

export type Modality = "optical" | "sar";

export interface UploadedImage {
    id: string;
    file: File;
    preview: string; // "" when the browser cannot render the format (GeoTIFF)
    modality: Modality;
}

export interface RasterBBox {
    north: number;
    south: number;
    east: number;
    west: number;
}

export interface RasterLayers {
    base: string;
    // null until a real model actually produces one (TinyCD for change
    // detection, a real spectral pipeline for spectral bands) — never a
    // fabricated placeholder image. A tab renders for a layer only when
    // its value here is a real URL; see LayerSwitcher.tsx.
    structural_changes: string | null;
    spectral_bands: string | null;
}

export type LayerKey = keyof RasterLayers;

export interface ProcessRasterResponse {
    bbox: RasterBBox;
    center: [number, number];
    zoom: number;
    layers: RasterLayers;
    source: "geotiff-tags" | "synthetic";
}

/** One user→assistant exchange in the conversational feed. */
export interface ConversationTurn {
    id: string;
    query: string;
    images: UploadedImage[];
    result: AnalysisResponse | null;
    loading: boolean;
    error: string | null;
    createdAt: number;
    raster: ProcessRasterResponse | null;
}

/** A single chat session in the sidebar history. */
export interface ChatSession {
    id: string;
    title: string;
    turns: ConversationTurn[];
    createdAt: number;
    pinned?: boolean;
}
