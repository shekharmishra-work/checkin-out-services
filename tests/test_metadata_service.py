"""Tests for app.services.metadata_service.extract_metadata_status.

Covers four EXIF scenarios:
  1. No EXIF data at all (screenshot / re-uploaded file)
  2. EXIF present but DateTimeOriginal tag (36867) absent
  3. EXIF present, date is in the past (old photo)
  4. EXIF present, date is today (pass)
"""

from __future__ import annotations

import io
from datetime import date
from unittest.mock import MagicMock, patch

from PIL import Image

from app.services.metadata_service import extract_metadata_status

_TAG_DATE_TIME_ORIGINAL = 36867


def _make_jpeg_bytes() -> bytes:
    """Create minimal in-memory JPEG bytes for PIL to open."""
    buf = io.BytesIO()
    Image.new("RGB", (100, 100), color=(255, 0, 0)).save(buf, format="JPEG")
    buf.seek(0)
    return buf.read()


# ── Scenario 1: No EXIF at all ────────────────────────────────────────────────


def test_no_exif_returns_warn_screenshot_reason() -> None:
    """When _getexif() returns None the image has no EXIF."""
    image_bytes = _make_jpeg_bytes()

    with patch("app.services.metadata_service.Image") as mock_pil:
        mock_img = MagicMock()
        mock_img._getexif.return_value = None
        mock_pil.open.return_value = mock_img

        result = extract_metadata_status(image_bytes)

    assert result.has_exif is False
    assert result.capture_date is None
    assert result.current_date == date.today()
    assert result.is_same_day is False
    assert result.meta_reason == "Image appears to be a screenshot or re-uploaded file"


# ── Scenario 2: EXIF present, DateTimeOriginal tag absent ─────────────────────


def test_exif_without_date_tag_returns_warn_missing_date() -> None:
    """EXIF dict exists but tag 36867 is not present."""
    image_bytes = _make_jpeg_bytes()

    with patch("app.services.metadata_service.Image") as mock_pil:
        mock_img = MagicMock()
        # EXIF dict with no DateTimeOriginal key
        mock_img._getexif.return_value = {271: "Canon", 272: "EOS 5D"}
        mock_pil.open.return_value = mock_img

        result = extract_metadata_status(image_bytes)

    assert result.has_exif is True
    assert result.capture_date is None
    assert result.current_date == date.today()
    assert result.is_same_day is False
    assert result.meta_reason == "Capture date not recorded in image metadata"


# ── Scenario 3: Old date (not today) ─────────────────────────────────────────


def test_old_date_returns_warn_pre_existing_photo() -> None:
    """DateTimeOriginal present but date is in the past."""
    image_bytes = _make_jpeg_bytes()
    old_date = date(2023, 1, 15)
    old_date_str = "2023:01:15 10:30:00"

    with patch("app.services.metadata_service.Image") as mock_pil:
        mock_img = MagicMock()
        mock_img._getexif.return_value = {_TAG_DATE_TIME_ORIGINAL: old_date_str}
        mock_pil.open.return_value = mock_img

        result = extract_metadata_status(image_bytes)

    assert result.has_exif is True
    assert result.capture_date == old_date
    assert result.current_date == date.today()
    assert result.is_same_day is False
    assert result.meta_reason is None


# ── Scenario 4: Date is today (pass) ─────────────────────────────────────────


def test_today_date_returns_pass() -> None:
    """DateTimeOriginal matches today."""
    image_bytes = _make_jpeg_bytes()
    today = date.today()
    today_str = today.strftime("%Y:%m:%d") + " 09:00:00"

    with patch("app.services.metadata_service.Image") as mock_pil:
        mock_img = MagicMock()
        mock_img._getexif.return_value = {_TAG_DATE_TIME_ORIGINAL: today_str}
        mock_pil.open.return_value = mock_img

        result = extract_metadata_status(image_bytes)

    assert result.has_exif is True
    assert result.capture_date == today
    assert result.current_date == today
    assert result.is_same_day is True
    assert result.meta_reason is None


# ── Edge case: malformed date string ─────────────────────────────────────────


def test_malformed_date_string_returns_warn_missing_date() -> None:
    """DateTimeOriginal tag present but value cannot be parsed."""
    image_bytes = _make_jpeg_bytes()

    with patch("app.services.metadata_service.Image") as mock_pil:
        mock_img = MagicMock()
        mock_img._getexif.return_value = {_TAG_DATE_TIME_ORIGINAL: "not-a-date"}
        mock_pil.open.return_value = mock_img

        result = extract_metadata_status(image_bytes)

    assert result.is_same_day is False
    assert result.meta_reason == "Capture date not recorded in image metadata"
