"""
API Routes — POST /api/analyze and GET /api/health.

Wires together: Validator → Router → Executor → Integrator → TraceBuilder.
"""

import time
import uuid
import tempfile
from pathlib import Path

from fastapi import APIRouter, UploadFile, File, Form, Query, Request, HTTPException
from fastapi.responses import JSONResponse
from typing import Optional
from loguru import logger

from app.utils.config import settings

router = APIRouter()


@router.post("/analyze")
async def analyze(
    request: Request,
    images: list[UploadFile] = File(default=[]),
    query: str = Form(...),
    modalities: str = Form(default="optical"),
    dates: Optional[str] = Form(default=None),
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

    # ── 1. Save uploaded images to temp directory ──
    # Each image gets its own temp dir, so the original filename is kept
    # (rather than a generic "image_N.ext") — it's echoed back in synthesized
    # stub answers, and Path(...).name strips any path components for safety.
    upload_start = time.perf_counter()
    image_paths = []
    for i, img_file in enumerate(images):
        original_name = Path(img_file.filename or "").name or f"image_{i}.png"
        tmp_dir = Path(tempfile.mkdtemp(prefix="satquery_"))
        tmp_path = tmp_dir / original_name
        content = await img_file.read()
        tmp_path.write_bytes(content)
        image_paths.append(str(tmp_path))
        logger.debug(f"[{request_id}] Saved image {i}: {tmp_path}")
    upload_ms = (time.perf_counter() - upload_start) * 1000

    # ── 2. Parse metadata ──
    modality_list = [m.strip() for m in modalities.split(",")]
    date_list = [d.strip() for d in dates.split(",")] if dates else []
    metadata = {
        "modalities": modality_list,
        "dates": date_list,
    }

    # ── 3. Validate query ──
    from app.agent.validator import InputValidator

    validation_start = time.perf_counter()
    validator = InputValidator()
    query_valid, query_error = validator.validate_query(query)
    if not query_valid:
        raise HTTPException(status_code=422, detail={"errors": [query_error]})

    # ── 4. Validate images ──
    validation = validator.validate(image_paths, metadata)
    if not validation.is_valid:
        raise HTTPException(status_code=422, detail={"errors": validation.errors})
    validation_ms = (time.perf_counter() - validation_start) * 1000

    # ── 5. Route ──
    from app.agent.router import RuleBasedRouter

    input_info = {
        "num_images": validation.num_images,
        "modalities": validation.modalities,
        "is_temporal": validation.is_temporal,
        "is_cross_modal": validation.is_cross_modal,
    }
    routing_start = time.perf_counter()
    router_inst = RuleBasedRouter()
    decision = router_inst.route(query, input_info)
    routing_ms = (time.perf_counter() - routing_start) * 1000
    logger.info(
        f"[{request_id}] Routed → {decision.task_type.value} "
        f"[{decision.rule_id}] — {decision.reasoning}"
    )

    # ── 6. Execute pipeline ──
    from app.agent.executor import PipelineExecutor

    registry = request.app.state.model_registry
    executor = PipelineExecutor(registry)
    execution_start = time.perf_counter()
    step_results = executor.execute(
        decision.pipeline, image_paths, query, request_id
    )
    execution_ms = (time.perf_counter() - execution_start) * 1000

    # ── 7. Integrate output ──
    # Runs before the trace is built so its cost lands inside the measured
    # total rather than after it.
    from app.output.integrator import OutputIntegrator

    integration_start = time.perf_counter()
    output = OutputIntegrator().integrate(
        step_results, decision.task_type, query, request_id
    )
    integration_ms = (time.perf_counter() - integration_start) * 1000

    # ── 8. Build trace ──
    from app.output.trace import TraceBuilder

    trace = TraceBuilder().build(
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
            "execution_ms": execution_ms,
            "integration_ms": integration_ms,
        },
        request_t0=request_t0,
        debug=debug,
    )

    # ── 9. Return response ──
    response = {
        "answer": output["answer"],
        "confidence": output["confidence"],
        "evidence": output["evidence"],
        "execution_trace": trace,
    }

    logger.info(
        f"[{request_id}] Complete — Task: {decision.task_type.value} | "
        f"Time: {trace['total_time_ms']:.0f}ms | "
        f"Confidence: {output['confidence']}"
    )

    return response


@router.get("/health")
async def health(request: Request):
    """Health check endpoint with GPU and model status."""
    registry = request.app.state.model_registry

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

    return {
        "status": "healthy",
        "models_loaded": registry.list_loaded(),
        "gpu_available": gpu_available,
        "gpu_memory_used": gpu_mem,
        "registered_models": registry.list_all(),
    }
