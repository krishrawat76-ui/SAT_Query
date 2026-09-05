"""
API Routes — POST /api/analyze and GET /api/health.

Wires together: Validator → Router → Executor → Integrator → TraceBuilder.
"""

import asyncio
import functools
import re
import shutil
import time
import uuid
import tempfile
from pathlib import Path

from fastapi import APIRouter, UploadFile, File, Form, Query, Request, HTTPException
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool
from typing import Optional
from loguru import logger

from app.agent.inference_lane import run_in_lane
from app.agent.land_cover_check import (
    evaluate_threshold,
    fallback_answer as land_cover_fallback_answer,
    land_cover_result_from_raw,
)
from app.agent.preflight import run_preflight
from app.api.uploads import save_upload_streamed
from app.output.sanitize import json_safe
from app.utils.config import settings

router = APIRouter()

# YYYY, YYYY-MM or YYYY-MM-DD. Deliberately not a full date parse — the backend
# only ever echoes these back in the trace.
_DATE_RE = re.compile(r"^\d{4}(-\d{2}){0,2}$")


def _parse_csv_field(
    raw: Optional[str],
    field: str,
    *,
    allowed: Optional[frozenset] = None,
    max_items: int,
) -> list[str]:
    """Bounded, optionally allowlisted CSV parse for a form field.

    An empty string yields [] rather than [""] — `"".split(",")` is `[""]`, and
    that empty string was carried into the execution trace as if it were a real
    modality. There was also no cap: 20 000 comma-separated entries were
    accepted and propagated.
    """
    if not raw:
        return []

    items = [p.strip() for p in raw.split(",") if p.strip()]
    if len(items) > max_items:
        raise HTTPException(
            status_code=422,
            detail={"errors": [
                f"At most {max_items} {field} values allowed, got {len(items)}."
            ]},
        )

    if allowed is not None:
        bad = sorted({i for i in items if i.lower() not in allowed})
        if bad:
            raise HTTPException(
                status_code=422,
                detail={"errors": [
                    f"Unsupported {field}: {', '.join(bad)[:200]}. "
                    f"Allowed: {', '.join(sorted(allowed))}."
                ]},
            )
        items = [i.lower() for i in items]

    return items


@router.post("/analyze")
async def analyze(
    request: Request,
    images: list[UploadFile] = File(default=[]),
    # max_length here rejects at parse time, before any upload is written to
    # disk. InputValidator.validate_query still enforces the same 2000-char
    # limit for callers that reach it another way.
    query: str = Form(..., max_length=settings.MAX_QUERY_CHARS),
    modalities: str = Form(
        default="optical", max_length=settings.MAX_METADATA_FIELD_CHARS
    ),
    dates: Optional[str] = Form(
        default=None, max_length=settings.MAX_METADATA_FIELD_CHARS
    ),
    debug: Optional[bool] = Query(default=None),
):
    """
    Main analysis endpoint.

    Accepts satellite image(s) + natural language query.
    Agent automatically detects task type, selects models, runs pipeline,
    and returns evidence-backed answer with execution trace.

    `?debug=true` additionally attaches sanitized per-step payload snapshots
    to the execution trace. It is a query param rather than a form field so
    the multipart body stays byte-identical for every client, and so the UI's
    Debug Mode toggle can actually change server behavior without a restart.
    Defaults to the DEBUG_TRACE setting. Only snapshots are gated — all other
    telemetry is a handful of numbers and is always on.
    """
    request_t0 = time.perf_counter()
    request_id = str(uuid.uuid4())[:8]
    debug = settings.DEBUG_TRACE if debug is None else debug
    logger.info(f"[{request_id}] New request — Query: '{query}' | Images: {len(images)}")

    # Every temp dir created below is removed in the `finally` at the end of
    # this handler — previously each request leaked its upload directory for
    # the process lifetime, including on the 422 path.
    tmp_dirs: list[Path] = []
    try:
        return await _run_analysis(
            request=request,
            images=images,
            query=query,
            modalities=modalities,
            dates=dates,
            debug=debug,
            request_id=request_id,
            request_t0=request_t0,
            tmp_dirs=tmp_dirs,
        )
    finally:
        for d in tmp_dirs:
            shutil.rmtree(d, ignore_errors=True)


async def _run_analysis(
    *,
    request: Request,
    images: list[UploadFile],
    query: str,
    modalities: str,
    dates: Optional[str],
    debug: bool,
    request_id: str,
    request_t0: float,
    tmp_dirs: list[Path],
):
    """Body of POST /api/analyze, split out so the route can guarantee temp
    directory cleanup in a `finally` regardless of how this returns or raises."""
    # ── 1. Save uploaded images to temp directory ──
    # The image-count check runs BEFORE the write loop. InputValidator enforces
    # the same limit at step 4, but only after every file has already been
    # streamed to disk — 20 uploads of 3 MB each cost 60 MB of disk I/O to
    # produce one 422, and Starlette allows up to 1000 files per request.
    if len(images) > settings.MAX_IMAGES_PER_REQUEST:
        raise HTTPException(
            status_code=422,
            detail={"errors": [
                f"Maximum {settings.MAX_IMAGES_PER_REQUEST} images allowed, but "
                f"{len(images)} were provided. Upload 1 image for VQA/grounding, "
                "or 2 for change detection/cross-modal."
            ]},
        )

    # Each image gets its own temp dir, so the original filename is kept
    # (rather than a generic "image_N.ext") — it's echoed back in synthesized
    # stub answers. save_upload_streamed sanitizes it; an over-long name used
    # to raise OSError straight through as a 500.
    upload_start = time.perf_counter()
    # Shared byte budget across every file in the request: the per-file cap
    # alone put no ceiling on the request as a whole.
    budget = [settings.MAX_REQUEST_SIZE_MB * 1024 * 1024]
    image_paths = []
    for i, img_file in enumerate(images):
        tmp_dir = Path(tempfile.mkdtemp(prefix="satquery_"))
        tmp_dirs.append(tmp_dir)
        tmp_path = await save_upload_streamed(
            img_file,
            tmp_dir,
            i,
            max_file_bytes=settings.MAX_UPLOAD_SIZE_MB * 1024 * 1024,
            remaining=budget,
            limit_label=f"{settings.MAX_UPLOAD_SIZE_MB} MB",
        )
        image_paths.append(str(tmp_path))
        logger.debug(f"[{request_id}] Saved image {i}: {tmp_path}")
    # Note: this measures the spool→disk copy only. FastAPI has already
    # received and parsed the multipart body by the time this handler runs,
    # so network receive time is not included here or in total_time_ms.
    upload_ms = (time.perf_counter() - upload_start) * 1000

    # ── 2. Parse metadata ──
    modality_list = _parse_csv_field(
        modalities,
        "modalities",
        allowed=settings.ALLOWED_MODALITIES,
        max_items=settings.MAX_MODALITY_ITEMS,
    ) or ["optical"]

    date_list = _parse_csv_field(dates, "dates", max_items=settings.MAX_DATE_ITEMS)
    bad_dates = [d for d in date_list if not _DATE_RE.match(d)]
    if bad_dates:
        raise HTTPException(
            status_code=422,
            detail={"errors": [
                f"Invalid date format: {', '.join(bad_dates)[:200]}. "
                "Expected YYYY, YYYY-MM or YYYY-MM-DD."
            ]},
        )

    metadata = {
        # A copy: InputValidator.validate() appends to this list in place to pad
        # it out to the image count, which would otherwise mutate the very
        # object the trace reports back as the request's metadata.
        "modalities": list(modality_list),
        "dates": date_list,
    }

    # ── 3. Validate query ──
    from app.agent.validator import InputValidator

    validation_start = time.perf_counter()
    validator = InputValidator()
    query_valid, query_error = validator.validate_query(query)
    if not query_valid:
        raise HTTPException(status_code=422, detail={"errors": [query_error]})

    # ── 4. Validate images + query↔input sufficiency (before routing) ──
    # Off the loop: this decodes every upload with PIL, which for a large raster
    # is real CPU time that the event loop should not be spending.
    validation = await run_in_threadpool(
        validator.validate, image_paths, metadata, query=query
    )
    if not validation.is_valid:
        # Keep `errors` as string list for the existing frontend contract;
        # attach structured codes/status for clients that can use them.
        raise HTTPException(
            status_code=422,
            detail={
                "errors": validation.errors,
                "status": getattr(validation.status, "value", str(validation.status)),
                "codes": list(validation.error_codes),
                "issues": [
                    {
                        "code": iss.code,
                        "message": iss.message,
                        "images": iss.images,
                    }
                    for iss in validation.issues
                    if iss.code in validation.error_codes
                ],
            },
        )
    validation_ms = (time.perf_counter() - validation_start) * 1000

    # ── 5. Route, concurrently with the fast land-cover pre-check ──
    # Prefer Shiven QueryPlanner (Ollama Qwen3) via a thin adapter; fall back
    # to the in-repo RuleBasedRouter only if disabled or import/path fails.
    from app.agent.router import RuleBasedRouter
    from app.utils.config import settings as app_settings

    # Read once, up front: both the concurrent land-cover check below and
    # the execution step further down need it.
    registry = request.app.state.model_registry

    input_info = {
        "num_images": validation.num_images,
        "modalities": validation.modalities,
        "is_temporal": validation.is_temporal,
        "is_cross_modal": validation.is_cross_modal,
    }

    async def _route() -> tuple:
        intent_decomposition = None
        if app_settings.USE_SHIVEN_ROUTER:
            try:
                from app.agent.shiven_adapter import ShivenRouterAdapter

                # Off the loop: this makes a BLOCKING urllib call to Ollama.
                shiven = await run_in_threadpool(
                    ShivenRouterAdapter().route,
                    query,
                    input_info,
                    image_paths=image_paths,
                )
                decision = shiven.decision
                intent_decomposition = shiven.intent_decomposition
                # Preserve spatial / sufficiency facts from validation on the
                # plan without altering router core logic.
                if intent_decomposition and validation.requirements:
                    for item in intent_decomposition:
                        if isinstance(item, dict):
                            item.setdefault(
                                "spatial_constraint",
                                validation.requirements.get("spatial_constraint"),
                            )
                            item.setdefault(
                                "required_inputs",
                                validation.requirements,
                            )
                if validation.requirements and decision.intent_decomposition is None:
                    decision.intent_decomposition = intent_decomposition
                logger.info(
                    f"[{request_id}] Shiven routed → {decision.task_type.value} "
                    f"[{decision.rule_id}] fallback={shiven.fallback_used} — "
                    f"{decision.reasoning}"
                )
            except Exception as exc:
                logger.error(
                    f"[{request_id}] Shiven adapter failed ({exc}); "
                    "using RuleBasedRouter"
                )
                decision = RuleBasedRouter().route(query, input_info)
        else:
            # Off the loop even though RuleBasedRouter is normally
            # microseconds of pure keyword matching: with no await point at
            # all, a synchronous call here would run to completion before
            # ever yielding control, which would serialize this branch
            # against _check_land_cover() below instead of truly overlapping
            # it — the whole point of gathering the two.
            decision = await run_in_threadpool(RuleBasedRouter().route, query, input_info)
            logger.info(
                f"[{request_id}] Routed → {decision.task_type.value} "
                f"[{decision.rule_id}] — {decision.reasoning}"
            )
        return decision, intent_decomposition

    # Only meaningful for an optical image. Genuinely concurrent with
    # routing via asyncio.gather below, not sequential before or after it —
    # a slow NLP planning call (Ollama can take a second or more) must not
    # sit in front of an answer this cheap check could already provide.
    has_optical_image = bool(image_paths) and any(
        m == "optical" for m in validation.modalities[: len(image_paths)]
    )

    async def _check_land_cover():
        if not has_optical_image:
            return None
        try:
            land_cover_model = registry.get("land_cover")
        except (KeyError, ValueError) as exc:
            logger.debug(f"[{request_id}] land_cover model unavailable: {exc}")
            return None
        lc_context = {"images": image_paths, "query": query, "request_id": request_id}
        raw = await run_in_threadpool(
            land_cover_model.run, "segment_land_cover", lc_context
        )
        return land_cover_result_from_raw(raw)

    routing_start = time.perf_counter()
    land_cover_start = time.perf_counter()
    (decision, intent_decomposition), land_cover_result = await asyncio.gather(
        _route(), _check_land_cover()
    )
    routing_ms = (time.perf_counter() - routing_start) * 1000
    land_cover_ms = (
        (time.perf_counter() - land_cover_start) * 1000 if has_optical_image else 0.0
    )

    # ── 5a. Land-cover threshold gate ──
    # True: proceed to the VLM as normal. False: the scene already has a
    # confident land-cover answer — skip dispatch entirely rather than pay
    # for a remote round trip nothing downstream needed ("cancelling" the
    # remote request, in practice — see land_cover_check.py's docstring for
    # why that means "never start it" rather than interrupting one already
    # in flight). None: no real model loaded (the stub today, always), so
    # this never blocks a real request — proceeds exactly as if the check
    # had not run at all.
    land_cover_decision = (
        evaluate_threshold(land_cover_result, app_settings.LAND_COVER_THRESHOLD_PCT)
        if land_cover_result is not None
        else None
    )

    def _land_cover_trace_block() -> Optional[dict]:
        if land_cover_result is None:
            return None
        return {
            "threshold": app_settings.LAND_COVER_THRESHOLD_PCT,
            "breakdown": land_cover_result.breakdown,
            "land_pct": land_cover_result.land_pct,
            "available": land_cover_result.available,
            "passed": land_cover_decision,
        }

    if land_cover_decision is False:
        logger.info(
            f"[{request_id}] Land-cover check below threshold "
            f"({land_cover_result.land_pct:.1f}% < "
            f"{app_settings.LAND_COVER_THRESHOLD_PCT:.0f}%) — "
            "skipping remote VLM dispatch."
        )
        from app.output.trace import TraceBuilder

        trace = await run_in_threadpool(
            functools.partial(
                TraceBuilder().build,
                validation,
                decision,
                [],
                registry=registry,
                metadata=metadata,
                request_id=request_id,
                stage_ms={
                    "upload_ms": upload_ms,
                    "validation_ms": validation_ms,
                    "routing_ms": routing_ms,
                    "land_cover_ms": land_cover_ms,
                    "preflight_ms": 0.0,
                    "execution_ms": 0.0,
                    "integration_ms": 0.0,
                },
                request_t0=request_t0,
                debug=debug,
                spatial=None,
                land_cover_check=_land_cover_trace_block(),
                remote_dispatch={"dispatched": False, "node_id": None, "task": None},
                fallback_strategy={
                    "triggered": True,
                    "reason": "land_cover_below_threshold",
                    "action": (
                        "Displayed the fast land-cover breakdown instead of "
                        "dispatching to the remote VLM."
                    ),
                },
            )
        )
        response = json_safe({
            "answer": land_cover_fallback_answer(
                land_cover_result, app_settings.LAND_COVER_THRESHOLD_PCT
            ),
            "confidence": None,
            "evidence": {"images": [], "regions": []},
            "execution_trace": trace,
        })
        logger.info(f"[{request_id}] Complete — land-cover fallback, no dispatch")
        return response

    # ── 5b. Preflight: reject an impossible plan BEFORE loading any model ──
    # The router picks a pipeline from query text; the Shiven adapter (the
    # default) never reads num_images at all. "what changed between the two
    # images?" with one image attached used to reach ChangeDetectionModel and
    # die on images[1] — an IndexError the executor swallowed into an HTTP 200
    # carrying answer "Model not available". Raises PipelineInputError, which
    # main.py maps to 422/413/503/504 with a machine-readable `code`.
    preflight_start = time.perf_counter()
    preflight = await run_in_threadpool(
        run_preflight, decision.pipeline, image_paths, validation.modalities
    )
    validation.warnings.extend(preflight["warnings"])
    # A zero-image request is downgraded to the conversational plan rather than
    # rejected, so the trace reports the pipeline that actually ran.
    decision.pipeline = preflight["pipeline"]
    preflight_ms = (time.perf_counter() - preflight_start) * 1000

    logger.info(
        f"[{request_id}] Pipeline plan: "
        f"{[(s.get('model'), s.get('action')) for s in decision.pipeline]}"
    )

    # ── 6. Execute pipeline ──
    # Hybrid executor: paired Model Hosts handle rs_vlm remotely; otherwise
    # preserve SKIP_MODEL_INFERENCE / local PipelineExecutor behavior.
    # (registry was already read in step 5, for the land-cover check.)
    execution_start = time.perf_counter()
    from app.agent.hybrid_executor import HybridPipelineExecutor

    # The serialized inference lane: one worker, bounded queue. Running local
    # inference on the event loop froze the entire server for the duration of
    # every forward pass, health checks included. HybridPipelineExecutor
    # already falls back to UnavailableModelExecutor internally when
    # skip_local_inference is set and no remote Model Host is paired, so it
    # is the only executor this needs to run — just serialized through the lane.
    step_results = await run_in_lane(
        HybridPipelineExecutor(
            registry,
            skip_local_inference=app_settings.SKIP_MODEL_INFERENCE,
        ).execute,
        decision.pipeline,
        image_paths,
        query,
        request_id,
        intent_decomposition=intent_decomposition
        or getattr(decision, "intent_decomposition", None),
    )
    execution_ms = (time.perf_counter() - execution_start) * 1000

    # ── 7. Integrate output ──
    # Runs before the trace is built so its cost lands inside the measured
    # total rather than after it.
    from app.output.integrator import OutputIntegrator

    integration_start = time.perf_counter()
    output = await run_in_threadpool(
        OutputIntegrator().integrate,
        step_results,
        decision.task_type,
        query,
        request_id,
    )
    # When every step was skipped (no weights), surface a clear answer instead
    # of the integrator's "No answer generated."
    post_exec_fallback = False
    if not any(r.success for r in step_results):
        # Prefer a concrete remote/local error over a generic placeholder
        remote_err = next(
            (
                (r.output or {}).get("answer")
                for r in reversed(step_results)
                if isinstance(r.output, dict)
                and r.output.get("status") == "remote_error"
                and r.output.get("answer")
            ),
            None,
        )
        # Covers the spec's "OR if the remote VLM service times out/fails"
        # trigger specifically — distinct from "no weights loaded locally
        # and no Model Host paired," which is this app's normal honest-stub
        # state (see UnavailableModelExecutor) and not a failure to fall
        # back from. Only a genuine remote_error, with real land-cover data
        # to fall back to, upgrades the answer here.
        post_exec_fallback = (
            remote_err is not None
            and land_cover_result is not None
            and land_cover_result.available
        )
        if post_exec_fallback:
            output["answer"] = land_cover_fallback_answer(
                land_cover_result, app_settings.LAND_COVER_THRESHOLD_PCT
            )
        else:
            output["answer"] = remote_err or "Model not available"
        output["confidence"] = None
    integration_ms = (time.perf_counter() - integration_start) * 1000

    # ── 8. Build trace ──
    from app.output.trace import TraceBuilder

    remote_step = next(
        (
            r for r in step_results
            if isinstance(r.output, dict) and r.output.get("execution") == "REMOTE"
        ),
        None,
    )
    remote_dispatch_info = {
        "dispatched": remote_step is not None,
        "node_id": remote_step.output.get("node_id") if remote_step else None,
        "task": remote_step.action if remote_step else None,
    }
    fallback_strategy_info = {
        "triggered": post_exec_fallback,
        "reason": "remote_vlm_failed" if post_exec_fallback else None,
        "action": (
            "Displayed the fast land-cover breakdown after the model path failed."
            if post_exec_fallback else None
        ),
    }

    # Off the loop: under ?debug=true, sanitizing per-step payload snapshots is
    # the most expensive non-inference work in the request.
    trace = await run_in_threadpool(
        functools.partial(
            TraceBuilder().build,
            validation,
            decision,
            step_results,
            registry=registry,
            metadata=metadata,
            request_id=request_id,
            stage_ms={
                "upload_ms": upload_ms,
                "validation_ms": validation_ms,
                "routing_ms": routing_ms,
                "land_cover_ms": land_cover_ms,
                "preflight_ms": preflight_ms,
                "execution_ms": execution_ms,
                "integration_ms": integration_ms,
            },
            request_t0=request_t0,
            debug=debug,
            spatial=preflight["spatial"],
            land_cover_check=_land_cover_trace_block(),
            remote_dispatch=remote_dispatch_info,
            fallback_strategy=fallback_strategy_info,
        )
    )

    # ── 9. Return response ──
    # json_safe is the last line of defence against the allow_nan=False 500:
    # Starlette refuses to render a bare NaN/Infinity, so one non-finite float
    # anywhere in the trace would turn a successful analysis into a 500. The
    # integrator and the debug sanitizer already guard their own sources; this
    # covers telemetry, timings, and anything added later.
    response = json_safe({
        "answer": output["answer"],
        "confidence": output["confidence"],
        "evidence": output["evidence"],
        "execution_trace": trace,
    })

    logger.info(
        f"[{request_id}] Complete — Task: {decision.task_type.value} | "
        f"Time: {trace['total_time_ms']:.0f}ms | "
        f"Confidence: {output['confidence']}"
    )

    return response


@router.get("/health")
async def health(request: Request):
    """Health check endpoint with GPU and model status."""
    # app.state.model_registry only exists once the lifespan has run to
    # completion. Reading it unguarded raised AttributeError → 500, and an
    # orchestrator reads a 500 health check as "kill the pod" rather than
    # "not ready yet" — the same distinction the GPU branch below already makes.
    registry = getattr(request.app.state, "model_registry", None)
    if registry is None:
        return JSONResponse(
            status_code=503,
            content={
                "status": "starting",
                "models_loaded": [],
                "gpu_available": False,
                "gpu_memory_used": None,
                "registered_models": None,
            },
        )

    gpu_available = False
    gpu_mem = None
    try:
        import torch
        gpu_available = torch.cuda.is_available()
        if gpu_available:
            # mem_get_info() reports the driver's real free/total, which
            # accounts for PyTorch's cache and other processes. The previous
            # `.total_mem` was also a typo for `.total_memory` and raised
            # AttributeError on any actual CUDA box.
            free_b, total_b = torch.cuda.mem_get_info()
            used = (total_b - free_b) / 1e9
            total = total_b / 1e9
            gpu_mem = f"{used:.1f} / {total:.1f} GB"
    except ImportError:
        pass
    except Exception as e:
        # A sick GPU must not make the health endpoint 500 — an orchestrator
        # reads that as "kill the pod" instead of "drain it". Report what we
        # know and leave the memory figure null.
        logger.warning(f"GPU status unavailable: {e}")
        gpu_mem = None

    device = None
    try:
        from app.node.config_store import config_summary, load_device_config, local_ip
        from app.node.registry import get_registry

        cfg = load_device_config()
        device = {
            **(config_summary(cfg) if cfg else {"role": None}),
            "lan_ip": local_ip(),
            "paired_nodes": get_registry().status_payload().get("nodes", []),
        }
    except Exception as exc:
        logger.debug(f"device status skipped: {exc}")

    return {
        "status": "healthy",
        "models_loaded": registry.list_loaded(),
        "gpu_available": gpu_available,
        "gpu_memory_used": gpu_mem,
        "registered_models": registry.list_all(),
        "device": device,
    }
