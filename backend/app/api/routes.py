"""
API Routes — POST /api/analyze and GET /api/health.

Wires together: Validator → Router → Executor → Integrator → TraceBuilder.
"""

import uuid
import tempfile
from pathlib import Path

from fastapi import APIRouter, UploadFile, File, Form, Request, HTTPException
from fastapi.responses import JSONResponse
from typing import Optional
from loguru import logger

router = APIRouter()


@router.post("/analyze")
async def analyze(
    request: Request,
    images: list[UploadFile] = File(default=[]),
    query: str = Form(...),
    modalities: str = Form(default="optical"),
    dates: Optional[str] = Form(default=None),
):
    """
    Main analysis endpoint.

    Accepts satellite image(s) + natural language query.
    Agent automatically detects task type, selects models, runs pipeline,
    and returns evidence-backed answer with execution trace.
    """
    request_id = str(uuid.uuid4())[:8]
    logger.info(f"[{request_id}] New request — Query: '{query}' | Images: {len(images)}")

    # ── 1. Save uploaded images to temp directory ──
    # Each image gets its own temp dir, so the original filename is kept
    # (rather than a generic "image_N.ext") — it's echoed back in synthesized
    # stub answers, and Path(...).name strips any path components for safety.
    image_paths = []
    for i, img_file in enumerate(images):
        original_name = Path(img_file.filename or "").name or f"image_{i}.png"
        tmp_dir = Path(tempfile.mkdtemp(prefix="satquery_"))
        tmp_path = tmp_dir / original_name
        content = await img_file.read()
        tmp_path.write_bytes(content)
        image_paths.append(str(tmp_path))
        logger.debug(f"[{request_id}] Saved image {i}: {tmp_path}")

    # ── 2. Parse metadata ──
    modality_list = [m.strip() for m in modalities.split(",")]
    date_list = [d.strip() for d in dates.split(",")] if dates else []
    metadata = {
        "modalities": modality_list,
        "dates": date_list,
    }

    # ── 3. Validate query ──
    from app.agent.validator import InputValidator

    validator = InputValidator()
    query_valid, query_error = validator.validate_query(query)
    if not query_valid:
        raise HTTPException(status_code=422, detail={"errors": [query_error]})

    # ── 4. Validate images ──
    validation = validator.validate(image_paths, metadata)
    if not validation.is_valid:
        raise HTTPException(status_code=422, detail={"errors": validation.errors})

    # ── 5. Route ──
    from app.agent.router import RuleBasedRouter

    input_info = {
        "num_images": validation.num_images,
        "modalities": validation.modalities,
        "is_temporal": validation.is_temporal,
        "is_cross_modal": validation.is_cross_modal,
    }
    router_inst = RuleBasedRouter()
    decision = router_inst.route(query, input_info)
    logger.info(
        f"[{request_id}] Routed → {decision.task_type.value} — {decision.reasoning}"
    )

    # ── 6. Execute pipeline ──
    from app.agent.executor import PipelineExecutor

    registry = request.app.state.model_registry
    executor = PipelineExecutor(registry)
    step_results = executor.execute(
        decision.pipeline, image_paths, query, request_id
    )

    # ── 7. Build trace ──
    from app.output.trace import TraceBuilder

    trace = TraceBuilder().build(validation, decision, step_results)

    # ── 8. Integrate output ──
    from app.output.integrator import OutputIntegrator

    output = OutputIntegrator().integrate(
        step_results, decision.task_type, query, request_id
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
            used = torch.cuda.memory_allocated() / 1e9
            total = torch.cuda.get_device_properties(0).total_mem / 1e9
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
