"""
Temporary Phase 3 stub — GeoTIFF/image coordinate extraction and synthetic
analysis-layer generation for the map overlay + layer switcher UI. Kept
separate from routes.py since this endpoint is explicitly temporary and
easy to delete once a real geospatial pipeline lands.
"""

import tempfile
import uuid
from pathlib import Path

from fastapi import APIRouter, File, UploadFile
from loguru import logger

from app.output.raster_stub import extract_bbox, generate_layers, zoom_for_bbox

router = APIRouter()


@router.post("/process-raster")
async def process_raster(image: UploadFile = File(...)):
    """Extract (or synthesize) a 4-corner bbox for the upload and generate
    three stub analysis layers (base / structural changes / spectral bands)."""
    request_id = str(uuid.uuid4())[:8]

    suffix = Path(image.filename).suffix or ".png"
    tmp_dir = Path(tempfile.mkdtemp(prefix="satquery_raster_"))
    tmp_path = tmp_dir / f"upload{suffix}"
    tmp_path.write_bytes(await image.read())

    logger.info(f"[{request_id}] process-raster — file: {image.filename}")

    extracted = extract_bbox(str(tmp_path))
    zoom = zoom_for_bbox(extracted["bbox"])
    layers = generate_layers(str(tmp_path), request_id)

    logger.info(f"[{request_id}] bbox source: {extracted['source']} — zoom: {zoom:.2f}")

    return {
        "bbox": extracted["bbox"],
        "center": extracted["center"],
        "zoom": zoom,
        "layers": layers,
        "source": extracted["source"],
    }
