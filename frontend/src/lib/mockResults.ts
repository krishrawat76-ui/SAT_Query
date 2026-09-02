import type { AnalysisResponse } from "@/types/api";

// Offline demo fallback when the backend is unreachable — keeps the scripted
// Mumbai/DC camera choreography visually verifiable without a live API.

const MUMBAI_RESULT: AnalysisResponse = {
    answer:
        "Satellite analysis complete. Target region shows a 14.2% expansion in built-up infrastructure and suburban density over the baseline period.",
    confidence: 0.91,
    evidence: {
        images: [],
        regions: [{ bbox: [0, 0, 100, 100], label: "Built-up expansion", confidence: 0.91 }],
    },
    execution_trace: {
        input_validation: {
            image_count: 1,
            format: ["PNG"],
            modality: ["optical"],
            temporal: false,
            cross_modal: false,
            compatible: true,
            warnings: [],
        },
        detected_task: "CHANGE_ANALYSIS",
        task_confidence: 0.89,
        reasoning:
            "Built-up density keywords detected in query; structural change-analysis pipeline selected.",
        selected_models: [{ name: "RS-VLM", version: "1.0" }],
        pipeline_steps: [
            { step: 1, model: "rs_vlm", action: "describe_scene", status: "success", time_ms: 1120 },
        ],
        total_time_ms: 1120,
    },
};

const DC_RESULT: AnalysisResponse = {
    answer:
        "Water body analysis complete. Hydrological feature boundaries identified with high confidence; minor surface runoff detected along the perimeter.",
    confidence: 0.88,
    evidence: {
        images: [],
        regions: [{ bbox: [0, 0, 100, 100], label: "Water body boundary", confidence: 0.88 }],
    },
    execution_trace: {
        input_validation: {
            image_count: 1,
            format: ["PNG"],
            modality: ["optical"],
            temporal: false,
            cross_modal: false,
            compatible: true,
            warnings: [],
        },
        detected_task: "VQA_GROUNDING",
        task_confidence: 0.86,
        reasoning:
            "Water-body grounding keywords detected in query; single-image grounding pipeline selected.",
        selected_models: [{ name: "Grounding-VLM", version: "1.0" }],
        pipeline_steps: [
            { step: 1, model: "grounding", action: "segment_water_body", status: "success", time_ms: 860 },
        ],
        total_time_ms: 860,
    },
};

const MOCK_RESULTS: AnalysisResponse[] = [MUMBAI_RESULT, DC_RESULT];

export function getMockResult(turnIndex: number): AnalysisResponse {
    return MOCK_RESULTS[Math.min(turnIndex, MOCK_RESULTS.length - 1)];
}
