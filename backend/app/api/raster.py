"""
Temporary Phase 3 stub — GeoTIFF/image coordinate extraction and synthetic
analysis-layer generation for the map overlay + layer switcher UI. Kept
separate from routes.py since this endpoint is explicitly temporary and
easy to delete once a real geospatial pipeline lands.
"""

import shutil
import tempfile
import uuid
from pathlib import Path

from fastapi import APIRouter, File, HTTPException, UploadFile
from loguru import logger
from PIL import Image

from app.agent.validator import InputValidator
from app.api.uploads import save_upload_streamed
from app.output.raster_stub import extract_bbox, generate_layers, zoom_for_bbox
from app.output.sanitize import json_safe
from app.utils.config import settings

router = APIRouter()


@router.post("/process-raster")
async def process_raster(image: UploadFile = File(...)):
    """Extract (or synthesize) a 4-corner bbox for the upload and generate the
    map's base analysis layer."""
    request_id = str(uuid.uuid4())[:8]

    # The temp dir is removed in the `finally` below. It previously leaked one
    # directory per request for the process lifetime — there was no cleanup at
    # all on this route, unlike /api/analyze.
    tmp_dir = Path(tempfile.mkdtemp(prefix="satquery_raster_"))
    try:
        # Was `tmp_path.write_bytes(await image.read())`: the whole upload was
        # buffered in memory and MAX_UPLOAD_SIZE_MB was never consulted here,
        # so a 60 MB (or 6 GB) body was accepted outright.
        tmp_path = await save_upload_streamed(
            image,
            tmp_dir,
            0,
            max_file_bytes=settings.MAX_UPLOAD_SIZE_MB * 1024 * 1024,
            remaining=[settings.MAX_REQUEST_SIZE_MB * 1024 * 1024],
            limit_label=f"{settings.MAX_UPLOAD_SIZE_MB} MB",
        )

        logger.info(f"[{request_id}] process-raster — file: {tmp_path.name}")

        # Reject non-images up front. This route used to return 200 with a
        # confident-looking bbox and a blank grey base layer for a 0-byte file
        # or for arbitrary bytes — fabricated geospatial output from garbage.
        if tmp_path.suffix.lower() not in InputValidator.VALID_EXTENSIONS:
            raise HTTPException(
                status_code=422,
                detail={"errors": [
                    f"Unsupported format '{tmp_path.suffix}'. Accepted: "
                    f"{', '.join(sorted(InputValidator.VALID_EXTENSIONS))}"
                ]},
            )
        try:
            with Image.open(tmp_path) as probe:
                probe.verify()
        except Exception:
            # Logged, not echoed — PIL's message embeds the absolute temp path.
            logger.warning(
                f"[{request_id}] process-raster: unreadable upload", exc_info=True
            )
            raise HTTPException(
                status_code=422,
                detail={"errors": ["Not a readable image file."]},
            )

        extracted = extract_bbox(str(tmp_path))
        zoom = zoom_for_bbox(extracted["bbox"])
        layers = generate_layers(str(tmp_path), request_id)

        logger.info(
            f"[{request_id}] bbox source: {extracted['source']} — zoom: {zoom:.2f}"
        )

        # json_safe for the same reason as /api/analyze: a non-finite bbox
        # coordinate would fail Starlette's allow_nan=False render as a 500.
        return json_safe({
            "bbox": extracted["bbox"],
            "center": extracted["center"],
            "zoom": zoom,
            "layers": layers,
            "source": extracted["source"],
        })
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)
