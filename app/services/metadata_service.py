"""EXIF metadata extraction service.

Extracts capture-date metadata from raw image bytes using Pillow.
Must be called on raw bytes *before* any image pre-processing.
"""

from __future__ import annotations

import logging
from datetime import date, datetime
from typing import cast

from PIL import ExifTags, Image  # noqa: F401 – ExifTags not used directly but documents tag IDs

from app.models.validation_models import MetadataResult

logger = logging.getLogger(__name__)

# EXIF tag ID for DateTimeOriginal
_TAG_DATE_TIME_ORIGINAL = 36867
_EXIF_DATE_FMT = "%Y:%m:%d %H:%M:%S"


def extract_metadata_status(image_bytes: bytes) -> MetadataResult:
    """Extract EXIF metadata from raw image bytes and return a MetadataResult.

    Args:
        image_bytes: Raw bytes of the uploaded image file.

    Returns:
        MetadataResult with has_exif, capture_date, current_date, is_same_day, and meta_reason.
    """
    current_date = date.today()

    try:
        img = Image.open(__import__("io").BytesIO(image_bytes))
        raw_exif = img._getexif()  # type: ignore[attr-defined]
    except Exception as exc:
        logger.warning("Could not open image for EXIF extraction: %s", exc)
        raw_exif = None

    if not raw_exif:
        return MetadataResult(
            has_exif=False,
            capture_date=None,
            current_date=current_date,
            is_same_day=False,
            meta_reason="Image appears to be a screenshot or re-uploaded file",
        )

    # EXIF is present – try to read DateTimeOriginal
    date_str = cast(str | None, raw_exif.get(_TAG_DATE_TIME_ORIGINAL))
    if date_str is None:
        return MetadataResult(
            has_exif=True,
            capture_date=None,
            current_date=current_date,
            is_same_day=False,
            meta_reason="Capture date not recorded in image metadata",
        )

    try:
        capture_dt = datetime.strptime(date_str.strip(), _EXIF_DATE_FMT)
        capture_date = capture_dt.date()
    except ValueError:
        logger.warning("Unrecognised EXIF DateTimeOriginal format: %r", date_str)
        return MetadataResult(
            has_exif=True,
            capture_date=None,
            current_date=current_date,
            is_same_day=False,
            meta_reason="Capture date not recorded in image metadata",
        )

    return MetadataResult(
        has_exif=True,
        capture_date=capture_date,
        current_date=current_date,
        is_same_day=(capture_date == current_date),
        meta_reason=None,
    )
