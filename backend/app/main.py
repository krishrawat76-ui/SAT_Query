"""
SatQuery AI — FastAPI Entry Point

Minimal backend for POC. Registers all model wrappers (real + stubs)
and serves the analysis API.
"""

from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from loguru import logger
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.formparsers import MultiPartException

from app.agent.exceptions import PipelineInputError
from app.agent.inference_lane import shutdown_lane
from app.api.routes import router
from app.api.raster import router as raster_router
from app.api.node_controller import router as nodes_router
from app.node.host_routes import router as host_router
from app.node.config_store import DeviceRole, load_device_config, local_ip
from app.utils.config import settings


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup and shutdown logic."""
    logger.info("🚀 Starting SatQuery AI backend...")

    cfg = load_device_config()
    if cfg:
        logger.info(
            f"Device role={cfg.role} node_id={cfg.node_id} lan={local_ip()}"
        )
        if cfg.role == DeviceRole.MODEL_HOST.value:
            logger.warning(
                "device.json role is model_host — prefer app.node.host_app:app "
                "on the node port; analyze API still loads for Full/Controller."
            )

    # ── Register all models ──
    from app.models.registry import ModelRegistry
    from app.models.vqa import QwenVLMWrapper
    from app.models.grounding import GroundingModel, SegmentationModel
    from app.models.change_detection import ChangeDetectionModel
    from app.models.change_vqa import ChangeVQAModel
    from app.models.optical_sar import OpticalSARFusionModel
    from app.models.land_cover import LandCoverModel

    registry = ModelRegistry()

    # Fast land-cover pre-check (MobileNetV4 UNet in the real deployment) —
    # lightweight by design, registered first and never competes meaningfully
    # with rs_vlm's VRAM budget.
    registry.register("land_cover", lambda: LandCoverModel(), vram_gb=0.1)

    # VQA + Caption + Change Description (Qwen2.5-VL-7B)
    registry.register("rs_vlm", lambda: QwenVLMWrapper(), vram_gb=5.5)

    # Grounding (GDINO + SAM) — stubs
    registry.register("grounding_dino", lambda: GroundingModel(), vram_gb=0.7)
    registry.register("sam", lambda: SegmentationModel(), vram_gb=0.35)

    # Change Detection (TinyCD) — stub
    registry.register("change_detection", lambda: ChangeDetectionModel(), vram_gb=0.15)

    # Change VQA (reuses VLM backbone) — stub
    registry.register("change_vqa", lambda: ChangeVQAModel(), vram_gb=5.5)

    # Optical-SAR Fusion — stub
    registry.register("optical_sar_fusion", lambda: OpticalSARFusionModel(), vram_gb=0.5)

    app.state.model_registry = registry

    logger.info(
        f"Registered {len(registry.list_all())} models: "
        f"{[m['name'] for m in registry.list_all()]}"
    )
    logger.info("✅ SatQuery AI backend ready")

    yield  # App runs

    # ── Shutdown ──
    # Lane first: unloading weights out from under a running inference would
    # leave the worker thread holding a half-freed model.
    logger.info("Shutting down — draining the inference lane...")
    shutdown_lane()
    logger.info("Unloading all models...")
    registry.unload_all()
    logger.info("👋 SatQuery AI backend stopped")


app = FastAPI(
    title="SatQuery AI",
    description="Agentic Remote-Sensing AI System — SIH 2026 / ISRO-SAC",
    version="0.1.0",
    lifespan=lifespan,
)

MAX_BODY_BYTES = settings.MAX_REQUEST_SIZE_MB * 1024 * 1024


def _envelope(errors: list[str], **extra) -> dict:
    """One error shape for the whole API: {"detail": {"errors": [...]}}.

    The API previously spoke two dialects — FastAPI's own
    {"detail": [{loc, msg, type}]} for framework validation, and
    {"detail": {"errors": [...]}} for hand-raised HTTPExceptions — forcing
    every client to branch on the shape of a failure.
    """
    return {"detail": {"errors": errors, **extra}}


# ── Request body size gate ──
@app.middleware("http")
async def limit_request_body(request: Request, call_next):
    """Reject oversized bodies before the multipart parser touches them.

    Content-Length only. A chunked request carries none, which is exactly why
    the streaming budget in app/api/uploads.py is the real backstop and this
    middleware is only the cheap first pass.
    """
    raw = request.headers.get("content-length")
    if raw is not None:
        try:
            declared = int(raw)
        except ValueError:
            return JSONResponse(
                status_code=400,
                content=_envelope(["Malformed Content-Length header."]),
            )
        if declared > MAX_BODY_BYTES:
            return JSONResponse(
                status_code=413,
                content=_envelope([
                    f"Request body exceeds the {settings.MAX_REQUEST_SIZE_MB} MB limit."
                ]),
            )
    return await call_next(request)


# ── Exception handlers ──
@app.exception_handler(PipelineInputError)
async def _pipeline_input_error(request: Request, exc: PipelineInputError):
    """Domain rejections: the request cannot drive the pipeline it was routed to.

    These previously surfaced as IndexError/KeyError inside a model wrapper,
    were swallowed by PipelineExecutor's broad except, and returned HTTP 200
    with answer "Model not available". They carry a machine-readable `code`
    (arity_mismatch, modality_mismatch, spatial_mismatch, ...) so the client can
    branch without parsing prose.
    """
    logger.info(f"Pipeline input rejected [{exc.code}]: {exc.message}")
    extra = {"context": exc.details} if exc.details else {}
    return JSONResponse(
        status_code=exc.status_code,
        content=_envelope([exc.message], code=exc.code, **extra),
    )


@app.exception_handler(StarletteHTTPException)
async def _http_error(request: Request, exc: StarletteHTTPException):
    detail = exc.detail
    if isinstance(detail, dict) and "errors" in detail:
        errors = [str(e) for e in detail["errors"]]
        # Preserve any extra fields a hand-raised HTTPException attached
        # (e.g. the validator's `status`/`codes`/`issues`) — collapsing to
        # bare `errors` here would silently discard them for every 4xx/5xx
        # raised as HTTPException(detail={"errors": [...], ...}).
        extra = {k: v for k, v in detail.items() if k != "errors"}
    else:
        errors = [str(detail)]
        extra = {}
    return JSONResponse(
        status_code=exc.status_code,
        content=_envelope(errors, **extra),
        headers=getattr(exc, "headers", None),
    )


@app.exception_handler(RequestValidationError)
async def _validation_error(request: Request, exc: RequestValidationError):
    """Flatten FastAPI's validation errors into the shared envelope.

    Only `loc` and `msg` are forwarded. Each entry also carries an `input` that
    echoes the client's own value back — reflecting a hostile or multi-megabyte
    field into the response body is not something an error path should do.
    """
    errors = [
        f"{'.'.join(str(p) for p in e.get('loc', [])[1:]) or 'body'}: "
        f"{e.get('msg', 'invalid value')}"
        for e in exc.errors()
    ]
    return JSONResponse(status_code=422, content=_envelope(errors))


@app.exception_handler(MultiPartException)
async def _multipart_error(request: Request, exc: MultiPartException):
    """A malformed or over-sized multipart body is the client's error, not a 500."""
    return JSONResponse(
        status_code=400,
        content=_envelope([f"Malformed multipart body: {exc.message}"]),
    )


@app.exception_handler(Exception)
async def _unhandled(request: Request, exc: Exception):
    """Never let an unexpected exception reach the client as a non-JSON 500.

    Starlette's default returns the plain-text string "Internal Server Error",
    which breaks the frontend's res.json(). The traceback stays server-side.
    """
    logger.opt(exception=exc).error(
        f"Unhandled {type(exc).__name__} on {request.method} {request.url.path}"
    )
    return JSONResponse(status_code=500, content=_envelope(["Internal server error."]))


# ── CORS ──
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,   # "null" stays, for file:// demos
    # Was True. Paired with the "null" origin it let any sandboxed iframe or
    # file:// page issue credentialed cross-origin requests. This API uses no
    # cookies or auth headers, so credentials buy nothing.
    allow_credentials=False,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Content-Type"],
)

# ── Static files (evidence images) ──
app.mount("/results", StaticFiles(directory=str(settings.RESULTS_DIR)), name="results")

# ── API routes ──
app.include_router(router, prefix="/api")
app.include_router(raster_router, prefix="/api")
app.include_router(nodes_router, prefix="/api")
# Model Host endpoints also mounted on Controller/Full System so a Full
# System machine can host models locally and accept pairing.
app.include_router(host_router)
