"""
Thin integration wrapper around Shiven's QueryPlanner.

Does NOT modify Shiven classifier / LLM / agent core logic.
Imports Shiven from SHIVEN_ROUTER_ROOT under an isolated load (both packages
are named `app`), then maps QueryPlan → this backend's RoutingDecision.
"""

from __future__ import annotations

import re
import sys
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from loguru import logger

from app.agent.router import ROUTER_VERSION, RoutingDecision, TaskType
from app.utils.config import settings


# Shiven TaskType string → (this backend TaskType, pipeline template, models)
_TASK_PIPELINE: dict[str, tuple[TaskType, list[dict], list[str]]] = {
    "VQA": (
        TaskType.VQA,
        [{"step": 1, "model": "rs_vlm", "action": "answer_question"}],
        ["rs_vlm"],
    ),
    "CAPTIONING": (
        TaskType.CAPTION,
        [{"step": 1, "model": "rs_vlm", "action": "generate_caption"}],
        ["rs_vlm"],
    ),
    "GROUNDING": (
        TaskType.GROUNDING,
        [
            {"step": 1, "model": "grounding_dino", "action": "detect_regions"},
            {"step": 2, "model": "sam", "action": "segment_regions"},
        ],
        ["grounding_dino", "sam"],
    ),
    "CHANGE_DETECTION": (
        TaskType.CHANGE_DETECTION,
        [
            {"step": 1, "model": "change_detection", "action": "generate_change_map"},
            {"step": 2, "model": "rs_vlm", "action": "describe_changes"},
        ],
        ["change_detection", "rs_vlm"],
    ),
    "CHANGE_VQA": (
        TaskType.CHANGE_VQA,
        [
            {"step": 1, "model": "change_detection", "action": "generate_change_map"},
            {"step": 2, "model": "change_vqa", "action": "answer_change_question"},
        ],
        ["change_detection", "change_vqa"],
    ),
    "OPTICAL_SAR": (
        TaskType.OPTICAL_SAR,
        [
            {"step": 1, "model": "optical_sar_fusion", "action": "fuse_modalities"},
            {"step": 2, "model": "rs_vlm", "action": "analyze_fused"},
        ],
        ["optical_sar_fusion", "rs_vlm"],
    ),
    "UNKNOWN": (
        TaskType.VQA,
        [{"step": 1, "model": "rs_vlm", "action": "answer_question"}],
        ["rs_vlm"],
    ),
}


@dataclass
class ShivenRouteResult:
    """RoutingDecision plus planner telemetry for the execution trace."""

    decision: RoutingDecision
    router_type: str = "shiven_llm_planner"
    router_version: str = "shiven/query_planner"
    fallback_used: bool = False
    fallback_reason: Optional[str] = None
    planner_type: Optional[str] = "qwen3:4b-instruct"
    planning_time_ms: Optional[float] = None
    intent_decomposition: list[dict] = field(default_factory=list)
    planner_raw_output: Optional[str] = None


_import_lock = threading.RLock()
_shiven_cache: dict[str, Any] = {}


def _load_shiven_classes() -> tuple[Any, Any, Any]:
    """
    Import Shiven's QueryPlanner / LLMPlanner / OllamaClient once.

    Both this backend and Shiven use the package name `app`, so we temporarily
    swap `sys.modules` entries, prefer Shiven on `sys.path` (and hide this
    backend's cwd), import Shiven, keep strong references to the classes +
    their modules, then restore this backend's `app` package.
    """
    with _import_lock:
        if "QueryPlanner" in _shiven_cache:
            return (
                _shiven_cache["QueryPlanner"],
                _shiven_cache["LLMPlanner"],
                _shiven_cache["OllamaClient"],
            )

        root = Path(settings.SHIVEN_ROUTER_ROOT).resolve()
        if not root.is_dir():
            raise FileNotFoundError(
                f"Shiven router root not found: {root}. "
                "Set SHIVEN_ROUTER_ROOT to SAT_Query_Agent-main."
            )

        rawat_modules = {
            k: v
            for k, v in sys.modules.items()
            if k == "app" or k.startswith("app.")
        }
        for k in list(rawat_modules):
            del sys.modules[k]

        root_str = str(root)
        backend_cwd = str(settings.BASE_DIR.resolve())
        old_path = sys.path[:]
        filtered = [
            p for p in old_path
            if p not in ("", ".")
            and str(Path(p).resolve()) not in (backend_cwd, root_str)
        ]
        sys.path = [root_str] + filtered

        try:
            from app.planner.llm import OllamaClient  # type: ignore
            from app.planner.llm_planner import LLMPlanner  # type: ignore
            from app.planner.planner import QueryPlanner  # type: ignore

            shiven_modules = {
                k: v
                for k, v in sys.modules.items()
                if k == "app" or k.startswith("app.")
            }
            _shiven_cache["QueryPlanner"] = QueryPlanner
            _shiven_cache["LLMPlanner"] = LLMPlanner
            _shiven_cache["OllamaClient"] = OllamaClient
            _shiven_cache["modules"] = shiven_modules
        finally:
            sys.path[:] = old_path
            for k in list(sys.modules):
                if k == "app" or k.startswith("app."):
                    del sys.modules[k]
            sys.modules.update(rawat_modules)

        logger.info(f"Loaded Shiven planner classes from {root}")
        return (
            _shiven_cache["QueryPlanner"],
            _shiven_cache["LLMPlanner"],
            _shiven_cache["OllamaClient"],
        )


def _image_refs(image_paths: list[str], modalities: list[str]) -> list[dict]:
    """Client-facing image references for the execution trace.

    Deliberately carries no absolute path. These refs are serialized into
    router_metadata.intent_decomposition and returned in every successful 200,
    where an entry like
    "/var/folders/f2/5jwpgqns.../T/satquery_jtm636g3/scene.png" disclosed the
    temp-dir scheme, the OS, and the account the server runs as. Nothing reads
    the field — `filename` beside it is what downstream code and the UI use.
    """
    refs = []
    for i, path in enumerate(image_paths):
        refs.append({
            "index": i,
            "filename": Path(path).name,
            "modality": modalities[i] if i < len(modalities) else None,
        })
    return refs


_OVERLAY_MARKERS = (
    "highlight",
    "segment",
    "outline",
    "bounding box",
    "mark the",
    "circle",
    "point out",
    "show me",
)


def _task_name(intent: Any) -> str:
    t = intent.task
    return (t.value if hasattr(t, "value") else str(t)).upper()


def _wants_spatial_overlay(query: str) -> bool:
    q = query.lower()
    if any(m in q for m in _OVERLAY_MARKERS):
        return True
    if re.search(r"\b(locate|find)\b", q):
        return True
    if "where is the" in q or "where are the" in q:
        return True
    return False


def _is_compound_analytical_vqa(query: str) -> bool:
    """Multi-part question seeking one textual answer (not boxes/masks)."""
    q = query.lower()
    if any(m in q for m in _OVERLAY_MARKERS):
        return False
    if any(
        p in q
        for p in (
            "relative to",
            "what evidence",
            "supports your",
            "most prominent",
            "visual features",
        )
    ):
        return True
    return len(re.findall(r"\b(what|where|which|how|why)\b", q)) >= 2


def _filter_plan_tasks(plan_tasks: list[Any], query: str) -> list[tuple[str, Any]]:
    """
    Normalize over-eager plans into executable intents.

    Returns list of (task_name, intent). For compound analytical VQA, forces
    a single VQA entry carrying the full user query.
    """
    if not plan_tasks:
        return []

    names = [_task_name(i) for i in plan_tasks]
    vlmish = {"VQA", "CAPTIONING", "UNKNOWN", "GROUNDING"}

    if _is_compound_analytical_vqa(query) and all(n in vlmish for n in names):
        logger.info(f"Coalescing Shiven plan {names} → single VQA (analytical)")
        return [("VQA", plan_tasks[0])]

    kept: list[tuple[str, Any]] = []
    for intent in plan_tasks:
        name = _task_name(intent)
        if name == "GROUNDING" and not _wants_spatial_overlay(query):
            logger.info("Dropping GROUNDING without spatial-overlay intent")
            continue
        if name == "CAPTIONING" and (
            "VQA" in names or _is_compound_analytical_vqa(query)
        ):
            logger.info("Dropping redundant CAPTIONING alongside VQA/analytical ask")
            continue
        kept.append((name, intent))

    if not kept:
        return [("VQA", plan_tasks[0])]
    return kept


def _plan_task_to_pipeline(
    task_name: str,
    task_id: str,
) -> tuple[TaskType, list[dict], list[str]]:
    task_type, template, models = _TASK_PIPELINE.get(
        task_name, _TASK_PIPELINE["UNKNOWN"]
    )
    pipeline = [
        {
            "step": item["step"],
            "model": item["model"],
            "action": item["action"],
            "task_id": task_id,
            "shiven_task": task_name,
        }
        for item in template
    ]
    return task_type, pipeline, list(models)


class ShivenRouterAdapter:
    """
    Calls Shiven QueryPlanner (LLM → rule fallback) without altering Shiven code.

    Fallback detection mirrors QueryPlanner.create_plan's try/except, but records
    whether the LLM path succeeded so the frontend Debug panel can show it.
    Post-filters over-decomposed plans (VQA+CAPTION+GROUNDING for one question).
    """

    def route(
        self,
        query: str,
        input_info: dict,
        image_paths: Optional[list[str]] = None,
    ) -> ShivenRouteResult:
        image_paths = image_paths or []
        modalities = input_info.get("modalities") or ["optical"]
        images = _image_refs(image_paths, modalities)

        QueryPlanner, LLMPlanner, OllamaClient = _load_shiven_classes()

        planner = QueryPlanner()
        client = OllamaClient(
            model=settings.OLLAMA_PLANNER_MODEL,
            base_url=settings.OLLAMA_BASE_URL,
        )
        llm_planner = LLMPlanner(client=client)

        fallback_used = False
        fallback_reason: Optional[str] = None
        planner_type: Optional[str] = settings.OLLAMA_PLANNER_MODEL
        raw_output: Optional[str] = None

        t0 = time.perf_counter()
        try:
            plan = llm_planner.create_plan(query)
            planner._apply_dependencies(plan, query)
            try:
                raw_output = plan.model_dump_json()
            except Exception:
                raw_output = str(plan)
            logger.info("Shiven LLM planner produced a QueryPlan")
        except Exception as exc:
            fallback_used = True
            fallback_reason = f"{type(exc).__name__}: {exc}"
            logger.warning(
                f"Shiven LLM planner failed — using rule-based fallback ({fallback_reason})"
            )
            plan = planner._create_rule_based_plan(query)
            try:
                raw_output = plan.model_dump_json()
            except Exception:
                raw_output = str(plan)
        planning_ms = (time.perf_counter() - t0) * 1000

        pipeline: list[dict] = []
        models: list[str] = []
        decomposition: list[dict] = []
        primary_task = TaskType.VQA
        step_offset = 0

        filtered = _filter_plan_tasks(list(plan.tasks), query)
        for task_name, intent in filtered:
            task_id = getattr(intent, "task_id", "task_1") or "task_1"
            if task_name == "VQA" and (
                _is_compound_analytical_vqa(query) or len(filtered) == 1
            ):
                query_fragment = query
            else:
                query_fragment = intent.target if intent.target else query

            mapped_type, steps, step_models = _plan_task_to_pipeline(task_name, task_id)
            if not pipeline:
                primary_task = mapped_type

            renumbered = []
            for i, s in enumerate(steps, start=1):
                renumbered.append({**s, "step": step_offset + i})
            pipeline.extend(renumbered)
            for m in step_models:
                if m not in models:
                    models.append(m)

            decomposition.append({
                "task_id": task_id,
                "task": task_name,
                "target": intent.target if task_name != "VQA" else None,
                "depends_on": list(intent.depends_on or []),
                "confidence": getattr(intent, "confidence", None),
                "requires_spatial_evidence": getattr(
                    intent, "requires_spatial_evidence", False
                ),
                "requires_segmentation": getattr(
                    intent, "requires_segmentation", False
                ),
                "requires_comparison": getattr(intent, "requires_comparison", False),
                "capabilities": [
                    c.value if hasattr(c, "value") else str(c)
                    for c in (intent.capabilities or [])
                ],
                "assigned_models": step_models,
                "pipeline_steps": [
                    {"step": s["step"], "model": s["model"], "action": s["action"]}
                    for s in renumbered
                ],
                "query": query_fragment,
                "images": images,
            })
            step_offset += len(renumbered)

        if not pipeline:
            primary_task, pipeline, models = _plan_task_to_pipeline("UNKNOWN", "task_1")
            pipeline = [{**s, "step": i} for i, s in enumerate(pipeline, start=1)]

        task_summary = ", ".join(
            f"{d['task_id']}={d['task']}" for d in decomposition
        ) or "empty"
        source = (
            "rule-based classifier fallback"
            if fallback_used
            else f"Ollama/{settings.OLLAMA_PLANNER_MODEL}"
        )
        reasoning = (
            f"Shiven QueryPlanner ({source}) -> {task_summary}. "
            f"{len(images)} image(s) attached for downstream models."
        )
        if fallback_reason:
            reasoning += f" Fallback reason: {fallback_reason}"

        decision = RoutingDecision(
            task_type=primary_task,
            models=models,
            pipeline=pipeline,
            reasoning=reasoning,
            rule_id="shiven_llm_fallback" if fallback_used else "shiven_llm_plan",
            matched_keywords=[],
            router_type="shiven_llm_planner",
            router_version="shiven/query_planner",
            fallback_used=fallback_used,
            planner_type=planner_type,
            planning_time_ms=round(planning_ms, 3),
            intent_decomposition=decomposition,
            planner_raw_output=raw_output,
        )

        return ShivenRouteResult(
            decision=decision,
            fallback_used=fallback_used,
            fallback_reason=fallback_reason,
            planner_type=planner_type,
            planning_time_ms=round(planning_ms, 3),
            intent_decomposition=decomposition,
            planner_raw_output=raw_output,
        )
