"""
InputValidator — Format, count, and modality validation for uploaded images.

Owner: M3 (Agent/Router Lead)

Checks:
  - Image count (1 or 2, reject 0 or 3+)
  - File format (GeoTIFF, TIFF, PNG, JPEG)
  - Image readability (can PIL open it?)
  - Modality classification (optical / SAR)
  - Cross-modal vs temporal detection
"""

from pathlib import Path
from dataclasses import dataclass, field
from typing import Optional

from PIL import Image
from loguru import logger


@dataclass
class ValidationResult:
    """Result of input validation — passed to router and trace builder."""
    is_valid: bool
    num_images: int
    modalities: list[str]
    is_temporal: bool
    is_cross_modal: bool
    format_info: list[dict]
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


class InputValidator:
    """
    Validates user-uploaded images before routing.

    Enforces:
      - 1 or 2 images only
      - Supported formats: .tif, .tiff, .geotiff, .png, .jpg, .jpeg
      - Images must be readable by PIL
    """

    VALID_EXTENSIONS = {".tif", ".tiff", ".geotiff", ".png", ".jpg", ".jpeg"}

    MAX_IMAGE_SIZE_MB = 50  # Reject images larger than 50 MB
    MAX_DIMENSION = 8192    # Reject images wider/taller than 8192px

    def validate(
        self,
        image_paths: list[str],
        metadata: Optional[dict] = None,
    ) -> ValidationResult:
        """
        Validate uploaded image files.

        Args:
            image_paths: List of file paths to uploaded images.
            metadata: Optional dict with:
                - modalities (list[str]): e.g. ["optical", "sar"]
                - dates (list[str]): e.g. ["2024-01", "2024-08"]

        Returns:
            ValidationResult with all validation info.
        """
        errors: list[str] = []
        warnings: list[str] = []
        format_info: list[dict] = []

        modalities = (
            metadata.get("modalities", ["optical"]) if metadata else ["optical"]
        )

        # ── Count check ──
        # 0 images is valid — a text-only conversational query. Routed to a
        # dedicated task in RuleBasedRouter rather than the image pipelines.
        if len(image_paths) > 2:
            errors.append(
                f"Maximum 2 images allowed, but {len(image_paths)} were provided. "
                "Upload 1 image for VQA/grounding, or 2 for change detection/cross-modal."
            )

        # ── Per-image checks ──
        for i, path in enumerate(image_paths):
            p = Path(path)
            img_label = f"Image {i + 1}"

            # Extension check
            ext = p.suffix.lower()
            if ext not in self.VALID_EXTENSIONS:
                errors.append(
                    f"{img_label}: Unsupported format '{ext}'. "
                    f"Accepted: {', '.join(sorted(self.VALID_EXTENSIONS))}"
                )
                continue

            # File size check
            try:
                size_mb = p.stat().st_size / (1024 * 1024)
                if size_mb > self.MAX_IMAGE_SIZE_MB:
                    errors.append(
                        f"{img_label}: File too large ({size_mb:.1f} MB). "
                        f"Maximum: {self.MAX_IMAGE_SIZE_MB} MB."
                    )
                    continue
            except OSError as e:
                errors.append(f"{img_label}: Cannot access file — {e}")
                continue

            # Readability check
            try:
                img = Image.open(path)
                width, height = img.size
                bands = len(img.getbands())

                if width > self.MAX_DIMENSION or height > self.MAX_DIMENSION:
                    warnings.append(
                        f"{img_label}: Large image ({width}×{height}). "
                        "May be resized for inference."
                    )

                format_info.append({
                    # Index into the ORIGINAL image_paths list. Entries are
                    # skipped for images that fail a check above, so a
                    # positional zip against `modalities`/`dates` downstream
                    # would silently attach the wrong image's metadata once
                    # any image is skipped. Carrying the source index keeps
                    # that correlation correct.
                    "index": i,
                    "filename": p.name,
                    "size": [width, height],
                    "bands": bands,
                    "format": ext,
                    "file_size_mb": round(size_mb, 2),
                })

            except Exception as e:
                errors.append(f"{img_label}: Cannot read image — {e}")

        # ── Extend modalities to match image count ──
        while len(modalities) < len(image_paths):
            modalities.append("optical")
        modalities = modalities[: len(image_paths)]

        # ── Cross-modal / temporal detection ──
        is_cross = (
            len(image_paths) == 2
            and len(modalities) >= 2
            and set(modalities[:2]) == {"optical", "sar"}
        )
        is_temporal = len(image_paths) == 2 and not is_cross

        if is_temporal:
            dates = metadata.get("dates", []) if metadata else []
            if not dates or len(dates) < 2:
                warnings.append(
                    "Bi-temporal input detected but no dates provided. "
                    "Results may be less accurate."
                )

        return ValidationResult(
            is_valid=len(errors) == 0,
            num_images=len(image_paths),
            modalities=modalities,
            is_temporal=is_temporal,
            is_cross_modal=is_cross,
            format_info=format_info,
            errors=errors,
            warnings=warnings,
        )

    def validate_query(self, query: str) -> tuple[bool, str]:
        """
        Basic query validation.

        Returns:
            (is_valid, error_message)
        """
        if not query or not query.strip():
            return False, "Query cannot be empty. Please ask a question about the satellite image(s)."

        if len(query.strip()) < 3:
            return False, "Query too short. Please provide a meaningful question."

        if len(query) > 2000:
            return False, "Query too long (max 2000 characters)."

        return True, ""
