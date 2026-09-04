"""
Tests for RuleBasedRouter — verifies all 6 task type classifications.

Covers the 10+ test queries from 06-AGENT-ROUTER-PLAN.md plus edge cases.
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.agent.router import RuleBasedRouter, TaskType


def test_single_image_vqa():
    """General question on single image → VQA."""
    router = RuleBasedRouter()
    result = router.route(
        "What objects are present?",
        {"num_images": 1, "modalities": ["optical"]},
    )
    assert result.task_type == TaskType.VQA
    assert "rs_vlm" in result.models


def test_single_image_caption():
    """Caption keywords on single image → CAPTION."""
    router = RuleBasedRouter()
    result = router.route(
        "Describe the scene",
        {"num_images": 1, "modalities": ["optical"]},
    )
    assert result.task_type == TaskType.CAPTION


def test_single_image_grounding():
    """Grounding keywords on single image → GROUNDING."""
    router = RuleBasedRouter()
    result = router.route(
        "Highlight the water body",
        {"num_images": 1, "modalities": ["optical"]},
    )
    assert result.task_type == TaskType.GROUNDING
    assert "grounding_dino" in result.models
    assert "sam" in result.models


def test_bitemporal_change_detection():
    """General query on 2 images → CHANGE_DETECTION."""
    router = RuleBasedRouter()
    result = router.route(
        "What changed?",
        {
            "num_images": 2,
            "modalities": ["optical", "optical"],
            "is_temporal": True,
        },
    )
    assert result.task_type == TaskType.CHANGE_DETECTION
    assert "change_detection" in result.models


def test_bitemporal_change_vqa():
    """Specific change question on 2 images → CHANGE_VQA."""
    router = RuleBasedRouter()
    result = router.route(
        "Has the built-up area increased?",
        {
            "num_images": 2,
            "modalities": ["optical", "optical"],
            "is_temporal": True,
        },
    )
    assert result.task_type == TaskType.CHANGE_VQA


def test_cross_modal_optical_sar():
    """Optical + SAR pair → OPTICAL_SAR."""
    router = RuleBasedRouter()
    result = router.route(
        "Identify regions using both",
        {
            "num_images": 2,
            "modalities": ["optical", "sar"],
            "is_cross_modal": True,
        },
    )
    assert result.task_type == TaskType.OPTICAL_SAR


def test_cross_modal_detection_via_modalities():
    """Cross-modal detected from modality set even without explicit flag."""
    router = RuleBasedRouter()
    result = router.route(
        "What can you see?",
        {
            "num_images": 2,
            "modalities": ["optical", "sar"],
        },
    )
    assert result.task_type == TaskType.OPTICAL_SAR


def test_grounding_keywords_variants():
    """Various grounding keywords work."""
    router = RuleBasedRouter()
    queries = [
        "Show me the buildings",
        "Locate the airport",
        "Find the river",
        "Where is the stadium",
        "Detect the parking lot",
    ]
    for q in queries:
        result = router.route(q, {"num_images": 1, "modalities": ["optical"]})
        assert result.task_type == TaskType.GROUNDING, f"Failed for: '{q}'"


def test_caption_keywords_variants():
    """Various caption keywords work."""
    router = RuleBasedRouter()
    queries = [
        "Summarize what you see",
        "Give me an overview",
        "Tell me about this image",
    ]
    for q in queries:
        result = router.route(q, {"num_images": 1, "modalities": ["optical"]})
        assert result.task_type == TaskType.CAPTION, f"Failed for: '{q}'"


def test_change_vqa_with_question_mark():
    """Question mark helps trigger change VQA."""
    router = RuleBasedRouter()
    result = router.route(
        "Did the forest area decrease between the two dates?",
        {
            "num_images": 2,
            "modalities": ["optical", "optical"],
            "is_temporal": True,
        },
    )
    assert result.task_type == TaskType.CHANGE_VQA


def test_default_vqa_fallback():
    """Unknown query type falls back to VQA."""
    router = RuleBasedRouter()
    result = router.route(
        "How many buildings are there?",
        {"num_images": 1, "modalities": ["optical"]},
    )
    assert result.task_type == TaskType.VQA


def test_routing_decisions_have_no_fabricated_confidence():
    """RoutingDecision carries no `confidence` field — the router is
    deterministic keyword matching, not a learned model, so it has no real
    score to report. `reasoning` carries the actual justification instead."""
    router = RuleBasedRouter()
    test_cases = [
        ("What is this?", {"num_images": 1, "modalities": ["optical"]}),
        ("Highlight the river", {"num_images": 1, "modalities": ["optical"]}),
        ("What changed?", {"num_images": 2, "modalities": ["optical", "optical"]}),
        ("Analyze with both", {"num_images": 2, "modalities": ["optical", "sar"]}),
    ]
    for query, info in test_cases:
        result = router.route(query, info)
        assert not hasattr(result, "confidence"), f"Unexpected confidence field for: '{query}'"
        assert result.reasoning, f"Missing reasoning for: '{query}'"


def test_routing_decision_has_pipeline():
    """Every routing decision includes a non-empty pipeline."""
    router = RuleBasedRouter()
    result = router.route(
        "What is this?",
        {"num_images": 1, "modalities": ["optical"]},
    )
    assert len(result.pipeline) > 0
    assert "step" in result.pipeline[0]
    assert "model" in result.pipeline[0]
    assert "action" in result.pipeline[0]


# ── Telemetry (Phase 4) ──

ROUTE_CASES = [
    ("Describe this scene", {"num_images": 1, "modalities": ["optical"]}, "caption_keywords"),
    ("Highlight the river", {"num_images": 1, "modalities": ["optical"]}, "grounding_keywords"),
    ("How many buildings are there?", {"num_images": 1, "modalities": ["optical"]}, "default_vqa"),
    ("What changed?", {"num_images": 2, "modalities": ["optical", "optical"]}, "bitemporal_general"),
    ("Has the built-up area increased?", {"num_images": 2, "modalities": ["optical", "optical"]}, "bitemporal_specific"),
    ("Analyze with both", {"num_images": 2, "modalities": ["optical", "sar"]}, "cross_modal"),
    ("What can you do?", {"num_images": 0, "modalities": []}, "text_only"),
]


def test_every_branch_reports_its_own_rule_id():
    """rule_id lets telemetry group decisions without parsing prose."""
    router = RuleBasedRouter()
    seen = set()
    for query, info, expected in ROUTE_CASES:
        result = router.route(query, info)
        assert result.rule_id == expected, f"'{query}' → {result.rule_id}"
        seen.add(result.rule_id)
    assert len(seen) == len(ROUTE_CASES), "rule ids must be distinct per branch"


def test_matched_keywords_are_real_substrings_of_the_query():
    """These are shown in the debug panel as the evidence for a decision, so
    they must be what actually matched — not a copy of the keyword list."""
    router = RuleBasedRouter()
    for query, info, _ in ROUTE_CASES:
        result = router.route(query, info)
        for keyword in result.matched_keywords:
            assert keyword in query.lower(), f"'{keyword}' not in '{query}'"


def test_all_routed_models_are_registered():
    """The router hardcodes model-name literals and never consults the
    registry, so a rename in main.py would only surface at runtime as a step
    failure. This catches that drift at test time."""
    from app.models.registry import ModelRegistry

    registry = ModelRegistry()
    for name, vram in [
        ("rs_vlm", 5.5), ("grounding_dino", 0.7), ("sam", 0.35),
        ("change_detection", 0.15), ("change_vqa", 5.5), ("optical_sar_fusion", 0.5),
    ]:
        registry.register(name, lambda: object(), vram_gb=vram)

    registered = {m["name"] for m in registry.list_all()}
    router = RuleBasedRouter()
    for query, info, _ in ROUTE_CASES:
        decision = router.route(query, info)
        for model_name in decision.models:
            assert model_name in registered, (
                f"Router selects unregistered model '{model_name}' for '{query}'"
            )
        for step in decision.pipeline:
            assert step["model"] in registered
