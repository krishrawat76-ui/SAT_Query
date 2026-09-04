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

export interface PipelineStep {
    step: number;
    model: string;
    action: string;
    status: "success" | "error";
    time_ms: number;
    error?: string | null;
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
    version: string;
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
    total_time_ms: number;
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
    structural_changes: string;
    spectral_bands: string;
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
