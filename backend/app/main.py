"""
SatQuery AI — FastAPI Entry Point

Minimal backend for POC. Registers all model wrappers (real + stubs)
and serves the analysis API.
"""

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from loguru import logger

from app.api.routes import router
from app.api.raster import router as raster_router
from app.utils.config import settings


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup and shutdown logic."""
    logger.info("🚀 Starting SatQuery AI backend...")

    # ── Register all models ──
    from app.models.registry import ModelRegistry
    from app.models.vqa import QwenVLMWrapper
    from app.models.grounding import GroundingModel, SegmentationModel
    from app.models.change_detection import ChangeDetectionModel
    from app.models.change_vqa import ChangeVQAModel
    from app.models.optical_sar import OpticalSARFusionModel

    registry = ModelRegistry()

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
    logger.info("Shutting down — unloading all models...")
    registry.unload_all()
    logger.info("👋 SatQuery AI backend stopped")


app = FastAPI(
    title="SatQuery AI",
    description="Agentic Remote-Sensing AI System — SIH 2026 / ISRO-SAC",
    version="0.1.0",
    lifespan=lifespan,
)

# ── CORS ──
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Static files (evidence images) ──
app.mount("/results", StaticFiles(directory=str(settings.RESULTS_DIR)), name="results")

# ── API routes ──
app.include_router(router, prefix="/api")
app.include_router(raster_router, prefix="/api")
