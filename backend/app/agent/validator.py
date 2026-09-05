"""
InputValidator — file, query sufficiency, and compatibility checks.

Runs before routing. Distinguishes VALID / WARNING / INVALID /
NEEDS_CLARIFICATION / UNSUPPORTED without fabricating metadata or
performing vision-model inference.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Optional

from PIL import Image
from loguru import logger

from app.agent.geo_checks import (
    compare_footprints,
    content_fingerprint,
    inspect_georef,
)
from app.agent.query_requirements import QueryRequirements, derive_query_requirements


class ValidationStatus(str, Enum):
    VALID = "VALID"
    WARNING = "WARNING"
    INVALID = "INVALID"
    NEEDS_CLARIFICATION = "NEEDS_CLARIFICATION"
    UNSUPPORTED = "UNSUPPORTED"


@dataclass
class ValidationIssue:
    code: str
    message: str
    images: list[int] = field(default_factory=list)


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
    # Spec extensions (backward-compatible extras)
    status: ValidationStatus = ValidationStatus.VALID
    error_codes: list[str] = field(default_factory=list)
    issues: list[ValidationIssue] = field(default_factory=list)
    requirements: Optional[dict] = None
    footprint_check: Optional[dict] = None


class InputValidator:
    """Validates uploads + query↔input sufficiency before routing."""

    VALID_EXTENSIONS = {".tif", ".tiff", ".geotiff", ".png", ".jpg", ".jpeg"}

    MAX_IMAGE_SIZE_MB = 50
    MAX_DIMENSION = 8192
    # Extreme absolute rejection (DoS / unusable)
    HARD_MAX_DIMENSION = 30000
    MIN_DIMENSION = 1

    def validate(
        self,
        image_paths: list[str],
        metadata: Optional[dict] = None,
        query: Optional[str] = None,
    ) -> ValidationResult:
        errors: list[str] = []
        warnings: list[str] = []
        issues: list[ValidationIssue] = []
        format_info: list[dict] = []
        error_codes: list[str] = []
        status = ValidationStatus.VALID

        metadata = metadata or {}
        modalities = list(metadata.get("modalities") or ["optical"])
        dates = list(metadata.get("dates") or [])
        requirements = derive_query_requirements(query or "")

        def add_error(code: str, message: str, images: Optional[list[int]] = None, *, clarif: bool = False, unsupported: bool = False):
            nonlocal status
            errors.append(message)
            error_codes.append(code)
            issues.append(ValidationIssue(code=code, message=message, images=images or []))
            if unsupported:
                status = ValidationStatus.UNSUPPORTED
            elif clarif and status not in (ValidationStatus.INVALID, ValidationStatus.UNSUPPORTED):
                status = ValidationStatus.NEEDS_CLARIFICATION
            elif status != ValidationStatus.UNSUPPORTED:
                status = ValidationStatus.INVALID

        def add_warning(code: str, message: str, images: Optional[list[int]] = None):
            nonlocal status
            warnings.append(message)
            issues.append(ValidationIssue(code=code, message=message, images=images or []))
            if status == ValidationStatus.VALID:
                status = ValidationStatus.WARNING

        # ── Count / ambiguity ──
        n = len(image_paths)
        if n > 2:
            add_error(
                "AMBIGUOUS_IMAGE_SET",
                f"Maximum 2 images allowed for automatic routing, but {n} were provided. "
                "Provide exactly 1 image for single-scene analysis or exactly 2 images "
                "for a bitemporal/cross-modal pair — ambiguous multi-image sets are "
                "not auto-assigned as T1/T2/T3.",
                list(range(n)),
                clarif=True,
            )

        # ── Per-image checks ──
        fingerprints: dict[str, list[int]] = {}
        trusted_bboxes: list[Optional[dict]] = [None] * n

        for i, path in enumerate(image_paths):
            p = Path(path)
            img_label = f"Image {i + 1}"
            # Never trust raw path components from client names beyond basename
            safe_name = p.name

            if not p.exists():
                add_error("FILE_NOT_FOUND", f"{img_label}: File does not exist.", [i])
                continue

            try:
                size_bytes = p.stat().st_size
            except OSError:
                # The raw OSError text embeds the absolute temp path, disclosing
                # the temp-dir scheme, the OS, and the account the server runs
                # as. Log it, don't echo it.
                logger.warning(f"{img_label}: stat() failed for {p}", exc_info=True)
                add_error("FILE_UNREADABLE", f"{img_label}: Upload could not be read from storage.", [i])
                continue

            if size_bytes == 0:
                add_error("EMPTY_FILE", f"{img_label}: File is empty.", [i])
                continue

            ext = p.suffix.lower()
            if ext not in self.VALID_EXTENSIONS:
                add_error(
                    "UNSUPPORTED_FORMAT",
                    f"{img_label}: Unsupported format '{ext}'. "
                    f"Accepted: {', '.join(sorted(self.VALID_EXTENSIONS))}",
                    [i],
                )
                continue

            size_mb = size_bytes / (1024 * 1024)
            if size_mb > self.MAX_IMAGE_SIZE_MB:
                add_error(
                    "FILE_TOO_LARGE",
                    f"{img_label}: File too large ({size_mb:.1f} MB). "
                    f"Maximum: {self.MAX_IMAGE_SIZE_MB} MB.",
                    [i],
                )
                continue

            try:
                fp = content_fingerprint(path)
                fingerprints.setdefault(fp, []).append(i)
            except OSError:
                pass

            try:
                with Image.open(path) as img:
                    img.load()  # force decode — catches truncated/corrupt
                    width, height = img.size
                    bands = len(img.getbands())
                    mode = img.mode

                    if width < self.MIN_DIMENSION or height < self.MIN_DIMENSION:
                        add_error(
                            "INVALID_DIMENSIONS",
                            f"{img_label}: Invalid dimensions ({width}x{height}).",
                            [i],
                        )
                        continue

                    if width > self.HARD_MAX_DIMENSION or height > self.HARD_MAX_DIMENSION:
                        add_error(
                            "EXTREME_DIMENSIONS",
                            f"{img_label}: Dimensions ({width}x{height}) exceed hard limit "
                            f"{self.HARD_MAX_DIMENSION}px.",
                            [i],
                        )
                        continue

                    if width > self.MAX_DIMENSION or height > self.MAX_DIMENSION:
                        add_warning(
                            "LARGE_DIMENSIONS",
                            f"{img_label}: Large image ({width}x{height}). "
                            "May be resized for inference.",
                            [i],
                        )

                    # Heavy NoData heuristic for modes that expose extremes — not cloud detection
                    nodata_ratio = None
                    try:
                        if mode in ("L", "I;16", "I"):
                            # Sample a small grid for speed
                            sample = img.resize((64, 64))
                            pixels = list(sample.get_flattened_data()) if hasattr(sample, "get_flattened_data") else list(sample.getdata())
                            if pixels:
                                zeroish = sum(1 for v in pixels if v == 0)
                                nodata_ratio = zeroish / len(pixels)
                                if nodata_ratio >= 0.98:
                                    add_error(
                                        "NODATA_HEAVY",
                                        f"{img_label}: Raster appears almost entirely invalid/NoData "
                                        f"(~{nodata_ratio:.0%} zero on sample). Unusable.",
                                        [i],
                                    )
                                    continue
                                if nodata_ratio >= 0.5:
                                    add_warning(
                                        "NODATA_PARTIAL",
                                        f"{img_label}: High invalid/zero pixel coverage "
                                        f"(~{nodata_ratio:.0%} on sample).",
                                        [i],
                                    )
                    except Exception:
                        nodata_ratio = None

                    georef = inspect_georef(path)
                    if georef.get("location_known"):
                        trusted_bboxes[i] = georef.get("bbox")

                    # Modality: never invent from pixels — client label or unknown
                    mod = modalities[i] if i < len(modalities) else None
                    if mod not in ("optical", "sar"):
                        mod = "unknown"
                        add_warning(
                            "MODALITY_UNKNOWN",
                            f"{img_label}: Modality not provided; left as unknown "
                            "(not inferred from pixels).",
                            [i],
                        )

                    date_val = dates[i] if i < len(dates) and dates[i] else None

                    format_info.append({
                        "index": i,
                        "filename": safe_name,
                        "size": [width, height],
                        "bands": bands,
                        "format": ext,
                        "file_size_mb": round(size_mb, 2),
                        "modality": mod,
                        "date": date_val,
                        "location_known": bool(georef.get("location_known")),
                        "bbox": georef.get("bbox"),
                        "crs": georef.get("crs"),
                        "georef_source": georef.get("source"),
                        "nodata_ratio_sample": nodata_ratio,
                    })
            except Exception:
                # PIL's raw message is
                # "cannot identify image file '/var/folders/.../satquery_xxx/f.png'"
                # — the same temp-path disclosure as the OSError branch above.
                # Log it, don't echo it.
                logger.warning(f"{img_label}: PIL could not open {path}", exc_info=True)
                add_error(
                    "CORRUPT_OR_UNREADABLE",
                    f"{img_label}: Not a readable image. Accepted formats: "
                    f"{', '.join(sorted(self.VALID_EXTENSIONS))}.",
                    [i],
                )

        # ── Duplicate content ──
        for fp, idxs in fingerprints.items():
            if len(idxs) >= 2:
                add_warning(
                    "DUPLICATE_IMAGES",
                    "Identical raster content detected across uploads "
                    f"(images {[i + 1 for i in idxs]}). "
                    "No meaningful temporal change can be established from duplicates.",
                    idxs,
                )

        # ── Normalize modalities list length ──
        while len(modalities) < n:
            modalities.append("unknown")
            add_warning(
                "MODALITY_PADDED",
                "Missing modality label(s); remaining slots marked unknown.",
            )
        modalities = modalities[:n]
        # Reflect per-image resolved modality from format_info when present
        for info in format_info:
            idx = info["index"]
            if idx < len(modalities) and info.get("modality"):
                modalities[idx] = info["modality"]

        is_cross = (
            n == 2
            and len(modalities) >= 2
            and set(modalities[:2]) == {"optical", "sar"}
        )
        is_temporal = n == 2 and not is_cross

        # ── Footprint correspondence (trusted geo only) ──
        footprint_check = None
        if n == 2 and format_info:
            by_index = {f["index"]: f for f in format_info}
            if 0 in by_index and 1 in by_index:
                b0 = by_index[0].get("bbox") if by_index[0].get("location_known") else None
                b1 = by_index[1].get("bbox") if by_index[1].get("location_known") else None
                footprint_check = compare_footprints(b0, b1)

        # ── Query ↔ input sufficiency (before routing) ──
        if requirements.is_external_information and n >= 0:
            add_error(
                "EXTERNAL_INFORMATION_REQUIRED",
                "This query requires external demographic/economic information "
                "that satellite imagery alone cannot provide.",
                unsupported=True,
            )

        # n == 0 is left to the router/preflight, which coerce a zero-image
        # request to the conversational path rather than rejecting it — only
        # a *partially* supplied pair (exactly one image) is a real mismatch
        # here.
        if (
            requirements.needs_temporal_pair
            and 0 < n < 2
            and status != ValidationStatus.UNSUPPORTED
        ):
            add_error(
                "MISSING_TEMPORAL_INPUT",
                "This query requires two temporally distinct images of the same area, "
                f"but only {n} image(s) were provided.",
                list(range(n)),
            )

        if requirements.needs_cross_modal and n >= 1:
            present = set(modalities[:n])
            if "sar" not in present or "optical" not in present:
                add_error(
                    "MISSING_CROSS_MODAL_INPUT",
                    "Query requires both optical and SAR imagery, but the upload "
                    f"modalities are {modalities[:n]}.",
                    list(range(n)),
                )

        if requirements.requires_modality == "sar" and n >= 1:
            if not any(m == "sar" for m in modalities[:n]):
                add_error(
                    "MODALITY_MISMATCH_SAR_REQUIRED",
                    "Query requests SAR imagery, but no SAR modality was provided "
                    f"(got {modalities[:n]}). Modality is taken from request metadata, "
                    "not invented from pixels.",
                    list(range(n)),
                )

        if requirements.requires_modality == "optical" and n >= 1:
            if any(m == "sar" for m in modalities[:n]) and not any(
                m == "optical" for m in modalities[:n]
            ):
                add_error(
                    "MODALITY_MISMATCH_OPTICAL_REQUIRED",
                    "Query requests optical imagery, but only SAR was provided.",
                    list(range(n)),
                )

        # Same-location for bitemporal / cross-modal fusion
        if (
            requirements.requires_same_location
            and n == 2
            and footprint_check is not None
            and status not in (ValidationStatus.UNSUPPORTED,)
        ):
            corr = footprint_check.get("correspondence")
            if corr == "none":
                add_error(
                    "TEMPORAL_PAIR_LOCATION_MISMATCH",
                    "The uploaded images do not represent sufficiently corresponding "
                    "geographic areas for the requested same-location comparison. "
                    + str(footprint_check.get("reason") or ""),
                    [0, 1],
                )
            elif corr == "partial":
                add_warning(
                    "PARTIAL_GEOGRAPHIC_OVERLAP",
                    "Images overlap only partially. Analysis should be restricted to "
                    "the overlapping region. " + str(footprint_check.get("reason") or ""),
                    [0, 1],
                )
            elif corr == "unknown" and requirements.needs_temporal_pair:
                add_warning(
                    "LOCATION_METADATA_UNKNOWN",
                    "Trusted geospatial bounds are unavailable for one or both images; "
                    "same-location compatibility cannot be verified and is left unknown "
                    "(not assumed).",
                    [0, 1],
                )

        if requirements.needs_cross_modal and n == 2 and footprint_check is not None:
            if footprint_check.get("correspondence") == "none":
                add_error(
                    "CROSS_MODAL_LOCATION_MISMATCH",
                    "Optical/SAR pair does not share a corresponding geographic area.",
                    [0, 1],
                )

        # Dates
        if is_temporal or requirements.needs_temporal_pair:
            if n == 2 and (not dates or len([d for d in dates if d]) < 2):
                if requirements.mentioned_years and len(requirements.mentioned_years) >= 2:
                    add_error(
                        "MISSING_ACQUISITION_DATES",
                        "Query names specific dates/years, but acquisition dates were "
                        "not provided for both images.",
                        [0, 1],
                        clarif=True,
                    )
                else:
                    add_warning(
                        "DATES_MISSING",
                        "Bi-temporal input detected but acquisition dates were not "
                        "provided. Temporal validity cannot be fully established.",
                    )

            if n == 2 and len(dates) >= 2 and dates[0] and dates[1]:
                if dates[0] == dates[1] and requirements.requires_distinct_dates:
                    add_error(
                        "SAME_ACQUISITION_DATE",
                        f"Both images share the same acquisition date ({dates[0]}); "
                        "a temporal change query requires distinct dates.",
                        [0, 1],
                    )

                # Explicit year mismatch vs query
                if requirements.mentioned_years:
                    file_years = set()
                    for d in dates[:2]:
                        file_years.update(
                            y for y in __import__("re").findall(r"((?:19|20)\d{2})", d)
                        )
                    query_years = set(requirements.mentioned_years)
                    if file_years and query_years and not query_years.issubset(file_years):
                        add_error(
                            "EXPLICIT_DATE_MISMATCH",
                            f"Query references year(s) {sorted(query_years)}, but "
                            f"provided acquisition dates are {dates[:2]}.",
                            [0, 1],
                        )

        # Ambiguous change wording with enough images still warns about unspecified target
        if requirements.is_ambiguous_change and n == 2 and status in (
            ValidationStatus.VALID,
            ValidationStatus.WARNING,
        ):
            add_warning(
                "AMBIGUOUS_CHANGE_TARGET",
                "Change intent detected but the change target is unspecified; "
                "routing may proceed with a general change-detection task.",
            )

        # Upload order must not define temporal order — record chronological sort when dates exist
        temporal_order = None
        if n == 2 and len(dates) >= 2 and dates[0] and dates[1]:
            temporal_order = sorted([0, 1], key=lambda i: dates[i])
            if temporal_order != [0, 1]:
                add_warning(
                    "TEMPORAL_ORDER_NORMALIZED",
                    f"Upload order differs from chronological order; "
                    f"normalized order is images {[i + 1 for i in temporal_order]}.",
                    temporal_order,
                )

        # Final status: errors force non-VALID; pure warnings keep WARNING
        is_valid = status in (ValidationStatus.VALID, ValidationStatus.WARNING)

        if temporal_order and footprint_check is not None:
            footprint_check = {**footprint_check, "temporal_order": temporal_order}

        result = ValidationResult(
            is_valid=is_valid,
            num_images=n,
            modalities=modalities,
            is_temporal=is_temporal,
            is_cross_modal=is_cross,
            format_info=format_info,
            errors=errors,
            warnings=warnings,
            status=status,
            error_codes=error_codes,
            issues=issues,
            requirements=requirements.to_dict(),
            footprint_check=footprint_check,
        )
        logger.debug(
            f"Validation status={status.value} codes={error_codes} warnings={len(warnings)}"
        )
        return result

    def validate_query(self, query: str) -> tuple[bool, str]:
        if not query or not query.strip():
            return False, "Query cannot be empty. Please ask a question about the satellite image(s)."
        if len(query.strip()) < 3:
            return False, "Query too short. Please provide a meaningful question."
        if len(query) > 2000:
            return False, "Query too long (max 2000 characters)."
        return True, ""
