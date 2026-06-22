"""Tests for POST /api/v1/validate-images endpoint.

The Gemini service is mocked so tests run without a real API key.
Covers:
  - Correct response shape (all required keys present)
  - submission_summary counts (passed / failed / damage_flagged)
  - identity aggregation flows through from identity_service
  - metadata list length matches number of uploaded files
"""

from __future__ import annotations

import io
from typing import Any
from unittest.mock import patch

from fastapi.testclient import TestClient
from PIL import Image

from app.main import app
from app.models.validation_models import (
    IdentityResult,
    ImageValidationResult,
    MetadataResult,
)

client = TestClient(app)


# ── Fixtures ──────────────────────────────────────────────────────────────────


def _jpeg_bytes(color: tuple[int, int, int] = (128, 128, 128)) -> bytes:
    """Produce a minimal in-memory JPEG for upload."""
    buf = io.BytesIO()
    Image.new("RGB", (50, 50), color=color).save(buf, format="JPEG")
    buf.seek(0)
    return buf.read()


def _fake_validation_results(n: int) -> list[ImageValidationResult]:
    return [
        ImageValidationResult(
            index=i + 1,
            valid=True,
            reason=None,
            plate="MH12AB1234",
            color="white",
            damage_detected=(i == 0),  # first image has damage
            damage_details="Minor dent on bonnet" if i == 0 else None,
        )
        for i in range(n)
    ]


def _fake_metadata() -> MetadataResult:
    from datetime import date

    return MetadataResult(
        has_exif=True,
        capture_date=date.today(),
        current_date=date.today(),
        is_same_day=True,
        meta_reason=None,
    )


def _fake_identity() -> IdentityResult:
    return IdentityResult(
        status="confirmed",
        detected_plates=["MH12AB1234", "MH12AB1234"],
        unique_plates=["MH12AB1234"],
        consensus_plate="MH12AB1234",
        consensus_color="white",
        identity_reason=None,
    )


# ── Helper to POST files ───────────────────────────────────────────────────────


def _post_images(n: int = 2) -> dict[str, Any]:
    files = [("images", (f"img_{i}.jpg", _jpeg_bytes(), "image/jpeg")) for i in range(n)]
    with (
        patch(
            "app.routers.image_validation.gemini_validate",
            return_value=_fake_validation_results(n),
        ),
        patch(
            "app.routers.image_validation.extract_metadata_status",
            return_value=_fake_metadata(),
        ),
        patch(
            "app.routers.image_validation.check_vehicle_identity",
            return_value=_fake_identity(),
        ),
    ):
        response = client.post("/api/v1/validate-images", files=files)

    assert response.status_code == 200
    return response.json()  # type: ignore[no-any-return]


# ── Tests ─────────────────────────────────────────────────────────────────────


def test_response_has_required_top_level_keys() -> None:
    data = _post_images(2)

    assert "submission_summary" in data
    assert "identity" in data
    assert "results" in data


def test_submission_summary_counts_are_correct() -> None:
    """2 images uploaded, both valid, 1 has damage."""
    data = _post_images(2)
    summary = data["submission_summary"]

    assert summary["total"] == 2
    assert summary["passed"] == 2
    assert summary["failed"] == 0
    assert summary["damage_flagged"] == 1


def test_results_list_length_matches_uploaded_files() -> None:
    data = _post_images(3)

    assert len(data["results"]) == 3


def test_each_result_has_expected_keys() -> None:
    data = _post_images(2)
    for result in data["results"]:
        assert "index" in result
        assert "filename" in result
        assert "validation" in result
        assert "metadata" in result


def test_validation_block_matches_gemini_mock_output() -> None:
    data = _post_images(2)
    val = data["results"][0]["validation"]

    assert val["valid"] is True
    assert val["plate"] == "MH12AB1234"
    assert val["color"] == "white"


def test_metadata_block_present_and_structured() -> None:
    data = _post_images(2)
    meta = data["results"][0]["metadata"]

    assert "has_exif" in meta
    assert "current_date" in meta
    assert "is_same_day" in meta
    assert meta["is_same_day"] is True


def test_identity_block_present_and_structured() -> None:
    data = _post_images(2)
    identity = data["identity"]

    assert "status" in identity
    assert identity["status"] in ("confirmed", "mismatch", "unverifiable")
    assert "detected_plates" in identity
    assert "unique_plates" in identity


def test_endpoint_returns_200_even_with_invalid_images() -> None:
    """Endpoint must not raise 4xx for images that fail validation."""
    failed_results = [
        ImageValidationResult(
            index=1,
            valid=False,
            reason="Too blurry",
            plate=None,
            color=None,
            damage_detected=False,
            damage_details=None,
        )
    ]
    unverifiable = IdentityResult(
        status="unverifiable",
        detected_plates=[],
        unique_plates=[],
        consensus_plate=None,
        consensus_color=None,
        identity_reason="No number plate visible in any image — manual verification required",
    )

    files = [("images", ("bad.jpg", _jpeg_bytes(), "image/jpeg"))]
    with (
        patch(
            "app.routers.image_validation.gemini_validate",
            return_value=failed_results,
        ),
        patch(
            "app.routers.image_validation.extract_metadata_status",
            return_value=_fake_metadata(),
        ),
        patch(
            "app.routers.image_validation.check_vehicle_identity",
            return_value=unverifiable,
        ),
    ):
        response = client.post("/api/v1/validate-images", files=files)

    assert response.status_code == 200
    data = response.json()
    assert data["submission_summary"]["failed"] == 1
    assert data["identity"]["status"] == "unverifiable"


def test_filenames_are_preserved_in_results() -> None:
    """The filename field in each result must match the upload filename."""
    n = 2
    fake_results = _fake_validation_results(n)
    files = [
        ("images", ("front.jpg", _jpeg_bytes(), "image/jpeg")),
        ("images", ("rear.jpg", _jpeg_bytes(), "image/jpeg")),
    ]
    with (
        patch(
            "app.routers.image_validation.gemini_validate",
            return_value=fake_results,
        ),
        patch(
            "app.routers.image_validation.extract_metadata_status",
            return_value=_fake_metadata(),
        ),
        patch(
            "app.routers.image_validation.check_vehicle_identity",
            return_value=_fake_identity(),
        ),
    ):
        response = client.post("/api/v1/validate-images", files=files)

    results = response.json()["results"]
    assert results[0]["filename"] == "front.jpg"
    assert results[1]["filename"] == "rear.jpg"
