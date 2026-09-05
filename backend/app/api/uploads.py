"""
Hardened multipart upload handling, shared by /analyze and /process-raster.

Both routes previously wrote client-supplied filenames straight onto disk and
enforced (at best) a per-file byte cap. That left two holes: an over-long or
NUL-bearing filename raised an uncaught OSError/ValueError and 500'd the
request, and a per-file cap alone put no ceiling on the *request*, so many
files each just under the limit still reached disk before any count check ran.
"""

import re
import unicodedata
from pathlib import Path
from typing import Optional

from fastapi import HTTPException, UploadFile

CHUNK_BYTES = 1024 * 1024
MAX_STEM_LEN = 80
_UNSAFE = re.compile(r"[^A-Za-z0-9._-]")


def safe_filename(raw: Optional[str], index: int) -> str:
    """Filesystem-safe, length-bounded name for a client-supplied filename.

    Keeps the *real* extension rather than defaulting to ".png": InputValidator
    checks the extension against VALID_EXTENSIONS, so coercing an extensionless
    upload to ".png" would turn a clear "Unsupported format" 422 into a
    confusing "Cannot read image" one.

    Strips path separators (traversal), NUL bytes (ValueError in open()), and
    caps the stem — a 400-character filename used to raise OSError: File name
    too long and surface as a 500.
    """
    name = Path((raw or "").replace("\\", "/")).name
    name = unicodedata.normalize("NFKD", name).replace("\x00", "")

    stem, dot, ext = name.rpartition(".")
    if not dot:
        stem, ext = name, ""

    stem = _UNSAFE.sub("_", stem).strip("._")[:MAX_STEM_LEN] or f"image_{index}"
    ext = _UNSAFE.sub("_", ext).lower()[:12]
    return f"{stem}.{ext}" if ext else stem


async def save_upload_streamed(
    upload: UploadFile,
    dest_dir: Path,
    index: int,
    *,
    max_file_bytes: int,
    remaining: list[int],
    limit_label: str,
) -> Path:
    """Stream one upload to disk under both a per-file cap and a request budget.

    `remaining` is a single-element list used as a mutable byte budget shared
    across every file in the request. The per-file cap alone let N files each
    just under it reach disk before the image-count check rejected the request.

    Raises HTTPException (413 over budget, 422 unwritable) rather than letting
    an OSError escape as a 500.
    """
    dest = dest_dir / safe_filename(upload.filename, index)
    written = 0
    try:
        with dest.open("wb") as fh:
            while chunk := await upload.read(CHUNK_BYTES):
                written += len(chunk)
                remaining[0] -= len(chunk)
                if written > max_file_bytes or remaining[0] < 0:
                    raise HTTPException(
                        status_code=413,
                        detail={"errors": [
                            f"Image {index + 1}: exceeds the {limit_label} upload limit."
                        ]},
                    )
                fh.write(chunk)
    except OSError as exc:
        # Over-long or otherwise unwritable names, a full disk, encoding the
        # filesystem rejects. The message deliberately carries no path — the
        # temp path used to reach the client verbatim.
        raise HTTPException(
            status_code=422,
            detail={"errors": [
                f"Image {index + 1}: could not be stored — "
                "invalid filename or unwritable upload."
            ]},
        ) from exc
    return dest
