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
    task_confidence: number;
    reasoning: string;
    selected_models: SelectedModel[];
    pipeline_steps: PipelineStep[];
    total_time_ms: number;
}

export interface AnalysisResponse {
    answer: string;
    confidence: number;
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

/** One user→assistant exchange in the conversational feed. */
export interface ConversationTurn {
    id: string;
    query: string;
    images: UploadedImage[];
    result: AnalysisResponse | null;
    loading: boolean;
    error: string | null;
    createdAt: number;
}

/** A single chat session in the sidebar history. */
export interface ChatSession {
    id: string;
    title: string;
    turns: ConversationTurn[];
    createdAt: number;
    pinned?: boolean;
}
