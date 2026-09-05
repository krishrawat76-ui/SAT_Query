"""
Application settings and configuration.
"""

import os
import tempfile
from pathlib import Path


def _default_shiven_root() -> Path:
    # backend/app/utils/config.py -> parents[3] == repo root
    repo_root = Path(__file__).resolve().parents[3]
    return repo_root / "router"


def _default_temp_dir() -> str:
    # Prefer a writable OS temp dir (Windows-safe) over hardcoded /tmp.
    return os.environ.get("TEMP_DIR") or str(Path(tempfile.gettempdir()) / "satquery")


class Settings:
    """Central configuration for SatQuery AI backend."""

    # ── Paths ──
    BASE_DIR: Path = Path(__file__).resolve().parent.parent.parent  # backend/
    RESULTS_DIR: Path = BASE_DIR / "results"
    MODELS_DIR: Path = BASE_DIR / "models"

    # Shiven QueryPlanner package root (contains the `app` package).
    SHIVEN_ROUTER_ROOT: str = os.environ.get(
        "SHIVEN_ROUTER_ROOT",
        str(_default_shiven_root()),
    )

    # ── Qwen2.5-VL (specialist inference — separate from Ollama planner) ──
    QWEN_MODEL_PATH: str = os.environ.get(
        "QWEN_MODEL_PATH",
        str(MODELS_DIR / "vqa" / "qwen25vl"),
    )

    # ── Shiven LLM planner (Ollama / Qwen3 4B) ──
    OLLAMA_BASE_URL: str = os.environ.get(
        "OLLAMA_BASE_URL", "http://localhost:11434"
    )
    OLLAMA_PLANNER_MODEL: str = os.environ.get(
        "OLLAMA_PLANNER_MODEL", "qwen3:4b-instruct"
    )
    # Use Shiven QueryPlanner instead of in-repo RuleBasedRouter.
    USE_SHIVEN_ROUTER: bool = os.environ.get(
        "USE_SHIVEN_ROUTER", "true"
    ).lower() in ("1", "true", "yes")
    # When True, do not load stub/real specialist weights — emit honest
    # "Model not available" / "Model not loaded" steps for Debug Mode.
    SKIP_MODEL_INFERENCE: bool = os.environ.get(
        "SKIP_MODEL_INFERENCE", "true"
    ).lower() in ("1", "true", "yes")

    # ── Server ──
    HOST: str = os.environ.get("HOST", "0.0.0.0")
    PORT: int = int(os.environ.get("PORT", "8000"))
    CORS_ORIGINS: list[str] = [
        "http://localhost:3000",
        "http://localhost:5173",
        "http://127.0.0.1:3000",
        "http://127.0.0.1:5173",
        "http://127.0.0.1:5500",   # VS Code Live Server
        "null",                      # file:// protocol
    ]

    # ── GPU ──
    MAX_VRAM_GB: float = float(os.environ.get("MAX_VRAM_GB", "8.0"))

    # ── Inference lane ──
    # Inference runs on a single-worker executor, not the event loop and not a
    # general threadpool: the registry holds one major model at a time for an
    # 8 GB card, so concurrent inferences would thrash VRAM. The queue bounds
    # how many requests may wait, so overload sheds as 503 instead of piling up.
    INFERENCE_TIMEOUT_S: float = float(os.environ.get("INFERENCE_TIMEOUT_S", "180"))
    INFERENCE_QUEUE_DEPTH: int = int(os.environ.get("INFERENCE_QUEUE_DEPTH", "4"))
    INFERENCE_QUEUE_WAIT_S: float = float(
        os.environ.get("INFERENCE_QUEUE_WAIT_S", "30")
    )

    # ── Uploads ──
    MAX_UPLOAD_SIZE_MB: int = 50          # per image
    # Mirrors InputValidator's own 1-or-2 image rule. Checked in the route
    # BEFORE the write loop — the validator's copy runs after every file has
    # already been streamed to disk.
    MAX_IMAGES_PER_REQUEST: int = 2
    # Whole-body ceiling: two images at the per-file cap plus multipart overhead.
    MAX_REQUEST_SIZE_MB: int = 110
    TEMP_DIR: str = _default_temp_dir()

    # ── Request field limits ──
    # The frontend's own type is `Modality = "optical" | "sar"`
    # (frontend/src/types/api.ts), so an allowlist costs it nothing.
    ALLOWED_MODALITIES: frozenset = frozenset({"optical", "sar"})
    MAX_MODALITY_ITEMS: int = 2
    MAX_DATE_ITEMS: int = 2
    # Kept in step with InputValidator.validate_query's own 2000-char check;
    # declaring it on the Form field rejects at parse time instead of after
    # the upload has already been written to disk.
    MAX_QUERY_CHARS: int = 2000
    MAX_METADATA_FIELD_CHARS: int = 512

    # ── Land cover pre-check ──
    # A lightweight local segmentation pass, run concurrently with query
    # routing, that can answer a request (or skip the slow remote VLM round
    # trip) from a land-cover breakdown alone when the scene lacks
    # high-level feature signal. See app/agent/land_cover_check.py.
    LAND_COVER_THRESHOLD_PCT: float = float(
        os.environ.get("LAND_COVER_THRESHOLD_PCT", "70.0")
    )

    # ── Debug ──
    # Default for the execution trace's per-step payload snapshots when a
    # request doesn't pass ?debug explicitly. Snapshotting costs real CPU on
    # large model outputs, so it stays off unless asked for; every other
    # telemetry field in the trace is always on.
    DEBUG_TRACE: bool = os.environ.get("SATQUERY_DEBUG", "").lower() in (
        "1", "true", "yes",
    )

    # ── Multi-device (optional env overrides; primary store is .satquery/device.json) ──
    SATQUERY_ROLE: str = os.environ.get("SATQUERY_ROLE", "")
    SATQUERY_NODE_PORT: int = int(os.environ.get("SATQUERY_NODE_PORT", "8100"))
    SATQUERY_REMOTE_TIMEOUT: float = float(
        os.environ.get("SATQUERY_REMOTE_TIMEOUT", "120")
    )


settings = Settings()

# Ensure dirs exist
settings.RESULTS_DIR.mkdir(parents=True, exist_ok=True)
Path(settings.TEMP_DIR).mkdir(parents=True, exist_ok=True)
