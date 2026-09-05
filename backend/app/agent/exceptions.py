"""
Domain exceptions for pipeline inputs that cannot be served.

Every one of these is raised BEFORE a model is loaded, and carries the HTTP
status the boundary should map it to.

These conditions previously surfaced as IndexError/KeyError/TypeError inside a
model wrapper, were swallowed by PipelineExecutor's broad `except Exception`,
and returned HTTP 200 with `answer: "Model not available"` — a rejected request
disguised as a successful one. Routing "what changed between the two images?"
with a single image attached is the canonical case: it reached
ChangeDetectionModel.run and died on `context["images"][1]`.
"""

from typing import Any, Optional


class PipelineInputError(Exception):
    """Base: the request is well-formed HTTP but cannot drive this pipeline."""

    status_code = 422
    code = "pipeline_input_error"

    def __init__(self, message: str, *, details: Optional[dict[str, Any]] = None):
        super().__init__(message)
        self.message = message
        self.details = details or {}


class ArityMismatchError(PipelineInputError):
    """Wrong number of images for the routed task.

    e.g. change detection planned for a request carrying one image.
    """

    code = "arity_mismatch"


class ModalityMismatchError(PipelineInputError):
    """Wrong modality combination for the routed task.

    e.g. optical/SAR fusion planned over two optical images.
    """

    code = "modality_mismatch"


class SpatialMismatchError(PipelineInputError):
    """Georeferenced rasters that do not cover the same ground."""

    code = "spatial_mismatch"


class RasterCompatibilityError(PipelineInputError):
    """Rasters that cannot meaningfully be compared.

    Band count, aspect ratio, ground sample distance, or an all-nodata tile.
    """

    code = "raster_incompatible"


class RasterTooLargeError(PipelineInputError):
    """Decompressed pixel count exceeds what we are willing to hold in memory.

    Distinct from the Phase 1 upload cap, which bounds bytes on the wire: a
    136 KB PNG decompresses to 144 megapixels (~432 MB of RGB).
    """

    status_code = 413
    code = "raster_too_large"


class InferenceOverloadedError(PipelineInputError):
    """The inference lane's wait queue is full — shed load rather than pile up."""

    status_code = 503
    code = "inference_overloaded"


class InferenceTimeoutError(PipelineInputError):
    """Inference exceeded its deadline."""

    status_code = 504
    code = "inference_timeout"
