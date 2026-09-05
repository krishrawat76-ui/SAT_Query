"""
Serialized off-loop execution lane for model inference.

The whole pipeline ran synchronously inside an `async def` handler. Measured
with a 1.5s simulated forward pass and an asyncio heartbeat due every 0.2s: the
ticks at 0.2/0.4/.../1.4s never fired, the first arrived at t+1.52s, and a
concurrent GET /api/health could not be served until inference finished. With
real Qwen2.5-VL that is 5-60s during which the server answers nothing —
including the health check an orchestrator reads to decide the pod is alive.

One worker, not a general threadpool: ModelRegistry deliberately holds one major
model at a time for an 8 GB card, so N concurrent inferences would thrash VRAM
and race in the registry. The semaphore bounds the wait queue, so overload sheds
as 503 rather than piling up unboundedly.
"""

import asyncio
import functools
import threading
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable, Optional, TypeVar

from loguru import logger

from app.agent.exceptions import InferenceOverloadedError, InferenceTimeoutError
from app.utils.config import settings

T = TypeVar("T")

_lane: Optional[ThreadPoolExecutor] = None
_slots: Optional[asyncio.Semaphore] = None
_lane_lock = threading.Lock()


def _get_lane() -> ThreadPoolExecutor:
    """The executor, created on demand.

    Deliberately not a module-level constant: shutdown_lane() runs on every
    lifespan exit, and a process that starts the app more than once — the test
    suite does, once per TestClient — would otherwise be left with a permanently
    shut-down executor and every later inference raising "cannot schedule new
    futures after shutdown".
    """
    global _lane
    with _lane_lock:
        if _lane is None:
            _lane = ThreadPoolExecutor(
                max_workers=1, thread_name_prefix="satquery-infer"
            )
        return _lane


def _get_slots() -> asyncio.Semaphore:
    """Created lazily: a Semaphore binds to the running loop on first use, so it
    cannot be built at import time."""
    global _slots
    if _slots is None:
        _slots = asyncio.Semaphore(settings.INFERENCE_QUEUE_DEPTH)
    return _slots


async def run_in_lane(fn: Callable[..., T], *args: Any, **kwargs: Any) -> T:
    """Run a blocking callable on the serialized inference lane.

    IMPORTANT: the timeout bounds how long the CLIENT waits. It cannot kill the
    running thread — Python has no safe thread termination — so a hung inference
    still occupies the lane until it returns on its own. The timeout protects
    the caller and the queue, not the GPU.
    """
    slots = _get_slots()
    try:
        await asyncio.wait_for(
            slots.acquire(), timeout=settings.INFERENCE_QUEUE_WAIT_S
        )
    except asyncio.TimeoutError:
        raise InferenceOverloadedError(
            "The inference queue is full. Please retry shortly.",
            details={
                "queue_depth": settings.INFERENCE_QUEUE_DEPTH,
                "queue_wait_s": settings.INFERENCE_QUEUE_WAIT_S,
            },
        ) from None

    try:
        loop = asyncio.get_running_loop()
        return await asyncio.wait_for(
            loop.run_in_executor(
                _get_lane(), functools.partial(fn, *args, **kwargs)
            ),
            timeout=settings.INFERENCE_TIMEOUT_S,
        )
    except asyncio.TimeoutError:
        logger.error(
            f"Inference exceeded {settings.INFERENCE_TIMEOUT_S}s. The worker "
            "thread is still running and holds the lane until it completes."
        )
        raise InferenceTimeoutError(
            f"Inference exceeded the {settings.INFERENCE_TIMEOUT_S}s time limit.",
            details={"timeout_s": settings.INFERENCE_TIMEOUT_S},
        ) from None
    finally:
        slots.release()


def shutdown_lane() -> None:
    """Drain and drop the lane. Called from the lifespan shutdown.

    Clearing `_lane` (rather than leaving a dead executor behind) lets a later
    app start build a fresh one, so the module survives more than one lifespan
    in a process.
    """
    global _lane, _slots
    with _lane_lock:
        lane, _lane = _lane, None
        _slots = None
    if lane is not None:
        lane.shutdown(wait=True, cancel_futures=True)
