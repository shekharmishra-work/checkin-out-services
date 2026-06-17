"""Tests for assess_vehicle_condition(), validate_and_assess(), and
POST /api/v1/assess-condition endpoint.

All Gemini API calls are mocked — no real API key required.
Test numbering matches the spec exactly.
"""

from __future__ import annotations

import io
import json
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from app.main import app
from app.models.validation_models import (
    AssessConditionResult,
    DamageType,
    IdentityResult,
    ImageValidationResult,
    MetadataResult,
    PartCondition,
    VehicleCondition,
    VehiclePart,
)
from app.services.gemini_service import assess_vehicle_condition, validate_and_assess

client = TestClient(app)

# ── Helpers ───────────────────────────────────────────────────────────────────

_ALL_PARTS: list[str] = [p.value for p in VehiclePart]


def _jpeg_bytes(color: tuple[int, int, int] = (100, 100, 100)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (50, 50), color=color).save(buf, format="JPEG")
    buf.seek(0)
    return buf.read()


def _make_raw_parts(
    *,
    damaged_part: str | None = None,
    damage_types: list[str] | None = None,
    severity: int = 2,
    count: int = 25,
) -> list[dict[str, object]]:
    """Build a valid 25-part JSON payload as Gemini would return it."""
    parts: list[dict[str, object]] = []
    for _i, name in enumerate(_ALL_PARTS[:count]):
        is_damaged = name == damaged_part
        parts.append(
            {
                "part": name,
                "visible_in_image": True,
                "damaged": is_damaged,
                "damage_types": (damage_types or ["dent"]) if is_damaged else [],
                "severity": severity if is_damaged else 0,
                "confidence": 0.9,
            }
        )
    return parts


def _fake_validation_results(n: int = 2) -> list[ImageValidationResult]:
    return [
        ImageValidationResult(
            index=i + 1,
            valid=True,
            reason=None,
            plate="DL52GD6992",
            color="white",
            damage_detected=True,
            damage_details="Dent on fender",
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
        detected_plates=["DL52GD6992"],
        unique_plates=["DL52GD6992"],
        consensus_plate="DL52GD6992",
        consensus_color="white",
        identity_reason=None,
    )


def _fake_vehicle_condition() -> VehicleCondition:
    parts = [
        PartCondition(
            part=VehiclePart(name),
            visible_in_image=True,
            damaged=(i == 0),
            damage_types=[DamageType.dent] if i == 0 else [],
            severity=2 if i == 0 else 0,
            confidence=0.9,
        )
        for i, name in enumerate(_ALL_PARTS)
    ]
    return VehicleCondition(overall_damage_score=2, parts=parts)


# ── Test 1: valid 25-part response → correct VehicleCondition ─────────────────


def test_assess_vehicle_condition_valid_25_parts() -> None:
    """assess_vehicle_condition with a valid 25-part response parses correctly
    and overall_damage_score equals the sum of all severity values."""
    raw_parts = _make_raw_parts(damaged_part="left_rear_fender", severity=2)
    # Make two parts damaged to verify sum
    raw_parts[0]["damaged"] = True
    raw_parts[0]["damage_types"] = ["scratch"]
    raw_parts[0]["severity"] = 1

    mock_model = MagicMock()
    mock_model.generate_content.return_value = MagicMock(
        text=json.dumps(raw_parts)
    )

    with (
        patch("app.services.gemini_service._get_api_key", return_value="test-key"),
        patch("app.services.gemini_service.genai") as mock_genai,
    ):
        mock_genai.GenerativeModel.return_value = mock_model
        result = assess_vehicle_condition([_jpeg_bytes()])

    assert isinstance(result, VehicleCondition)
    assert len(result.parts) == 25
    expected_score = sum(p.severity for p in result.parts)
    assert result.overall_damage_score == expected_score


# ── Test 2: 24 parts → raises ValueError ──────────────────────────────────────


def test_assess_vehicle_condition_24_parts_raises() -> None:
    """assess_vehicle_condition raises ValueError when Gemini returns 24 parts."""
    raw_parts = _make_raw_parts(count=24)  # only 24 parts

    mock_model = MagicMock()
    mock_model.generate_content.return_value = MagicMock(
        text=json.dumps(raw_parts)
    )

    with (
        patch("app.services.gemini_service._get_api_key", return_value="test-key"),
        patch("app.services.gemini_service.genai") as mock_genai,
    ):
        mock_genai.GenerativeModel.return_value = mock_model
        with pytest.raises(ValueError, match="expected 25"):
            assess_vehicle_condition([_jpeg_bytes()])


# ── Test 3: unknown part name → raises ValueError ─────────────────────────────


def test_assess_vehicle_condition_unknown_part_raises() -> None:
    """assess_vehicle_condition raises ValueError on an unknown part name."""
    raw_parts = _make_raw_parts()
    raw_parts[0]["part"] = "flying_door"  # not a valid VehiclePart

    mock_model = MagicMock()
    mock_model.generate_content.return_value = MagicMock(
        text=json.dumps(raw_parts)
    )

    with (
        patch("app.services.gemini_service._get_api_key", return_value="test-key"),
        patch("app.services.gemini_service.genai") as mock_genai,
    ):
        mock_genai.GenerativeModel.return_value = mock_model
        with pytest.raises(ValueError, match="unknown part name"):
            assess_vehicle_condition([_jpeg_bytes()])


# ── Test 4: damaged=false but non-empty damage_types → parses without crash ───


def test_assess_vehicle_condition_inconsistent_flags_does_not_crash() -> None:
    """Defensive: damaged=false with non-empty damage_types still parses.

    The model may occasionally return inconsistent data. Pydantic validates the
    schema, not the business logic invariants — so this parses without crashing.
    Callers are responsible for downstream business logic enforcement.
    """
    raw_parts = _make_raw_parts()
    # Introduce inconsistent data: damaged=false but damage_types non-empty
    raw_parts[5]["damaged"] = False
    raw_parts[5]["damage_types"] = ["dent"]
    raw_parts[5]["severity"] = 0

    mock_model = MagicMock()
    mock_model.generate_content.return_value = MagicMock(
        text=json.dumps(raw_parts)
    )

    with (
        patch("app.services.gemini_service._get_api_key", return_value="test-key"),
        patch("app.services.gemini_service.genai") as mock_genai,
    ):
        mock_genai.GenerativeModel.return_value = mock_model
        result = assess_vehicle_condition([_jpeg_bytes()])

    assert len(result.parts) == 25
    # The inconsistent part is still present — parsed defensively
    assert result.parts[5].damaged is False
    assert DamageType.dent in result.parts[5].damage_types


# ── Test 5: all 25 parts severity=0 → overall_damage_score=0 ─────────────────


def test_assess_vehicle_condition_all_zero_severity() -> None:
    """When every part has severity=0, overall_damage_score must be 0."""
    raw_parts = _make_raw_parts()  # no damaged_part specified → all severity=0

    mock_model = MagicMock()
    mock_model.generate_content.return_value = MagicMock(
        text=json.dumps(raw_parts)
    )

    with (
        patch("app.services.gemini_service._get_api_key", return_value="test-key"),
        patch("app.services.gemini_service.genai") as mock_genai,
    ):
        mock_genai.GenerativeModel.return_value = mock_model
        result = assess_vehicle_condition([_jpeg_bytes()])

    assert result.overall_damage_score == 0
    assert all(p.severity == 0 for p in result.parts)


# ── Test 6: validate_and_assess → full AssessConditionResult ──────────────────


def test_validate_and_assess_returns_full_result() -> None:
    """validate_and_assess merges both assessments with all fields intact."""
    fake_vc = _fake_vehicle_condition()

    with (
        patch(
            "app.services.gemini_service.validate_images",
            return_value=_fake_validation_results(2),
        ),
        patch(
            "app.services.gemini_service.extract_metadata_status",
            return_value=_fake_metadata(),
        ),
        patch(
            "app.services.gemini_service.check_vehicle_identity",
            return_value=_fake_identity(),
        ),
        patch(
            "app.services.gemini_service.assess_vehicle_condition",
            return_value=fake_vc,
        ),
    ):
        result = validate_and_assess(
            [_jpeg_bytes(), _jpeg_bytes()],
            ["front.jpg", "rear.jpg"],
        )

    assert isinstance(result, AssessConditionResult)
    # Existing fields must be intact
    assert result.submission_summary.total == 2
    assert result.submission_summary.passed == 2
    assert result.identity.status == "confirmed"
    assert len(result.results) == 2
    assert result.results[0].filename == "front.jpg"
    assert result.results[1].filename == "rear.jpg"
    # New field
    assert result.vehicle_condition is not None
    assert len(result.vehicle_condition.parts) == 25


# ── Test 7: assess_vehicle_condition raises → vehicle_condition is None ────────


def test_validate_and_assess_condition_failure_returns_none_vehicle_condition() -> None:
    """If assess_vehicle_condition raises, vehicle_condition is None but the
    rest of the response (submission_summary, identity, results) is still valid."""
    with (
        patch(
            "app.services.gemini_service.validate_images",
            return_value=_fake_validation_results(1),
        ),
        patch(
            "app.services.gemini_service.extract_metadata_status",
            return_value=_fake_metadata(),
        ),
        patch(
            "app.services.gemini_service.check_vehicle_identity",
            return_value=_fake_identity(),
        ),
        patch(
            "app.services.gemini_service.assess_vehicle_condition",
            side_effect=ValueError("Gemini returned 24 parts, expected 25"),
        ),
    ):
        result = validate_and_assess([_jpeg_bytes()], ["img.jpg"])

    assert isinstance(result, AssessConditionResult)
    assert result.vehicle_condition is None
    # Gate-check fields must still be populated
    assert result.submission_summary.total == 1
    assert result.identity.status == "confirmed"
    assert len(result.results) == 1


# ── Test 8: POST /api/v1/assess-condition → HTTP 200 with correct shape ───────


def test_assess_condition_endpoint_returns_200_with_correct_shape() -> None:
    """POST /api/v1/assess-condition returns HTTP 200 and a response matching
    AssessConditionResult shape with vehicle_condition present."""
    n = 2
    fake_vc = _fake_vehicle_condition()
    files = [
        ("images", (f"img_{i}.jpg", _jpeg_bytes(), "image/jpeg")) for i in range(n)
    ]

    with patch(
        "app.routers.image_validation.validate_and_assess",
        return_value=AssessConditionResult(
            submission_summary=__import__(
                "app.models.validation_models", fromlist=["SubmissionSummary"]
            ).SubmissionSummary(total=n, passed=n, failed=0, damage_flagged=1),
            identity=_fake_identity(),
            results=[
                __import__(
                    "app.models.validation_models", fromlist=["ImageResult"]
                ).ImageResult(
                    index=i + 1,
                    filename=f"img_{i}.jpg",
                    validation=_fake_validation_results(n)[i],
                    metadata=_fake_metadata(),
                )
                for i in range(n)
            ],
            vehicle_condition=fake_vc,
        ),
    ):
        response = client.post("/api/v1/assess-condition", files=files)

    assert response.status_code == 200
    data = response.json()

    # Top-level keys
    assert "submission_summary" in data
    assert "identity" in data
    assert "results" in data
    assert "vehicle_condition" in data

    # vehicle_condition shape
    vc = data["vehicle_condition"]
    assert "overall_damage_score" in vc
    assert "parts" in vc
    assert len(vc["parts"]) == 25

    # Each part has required keys
    for part in vc["parts"]:
        assert "part" in part
        assert "visible_in_image" in part
        assert "damaged" in part
        assert "damage_types" in part
        assert "severity" in part
        assert "confidence" in part

    # Existing endpoint shape is unchanged
    assert len(data["results"]) == n
    for result in data["results"]:
        assert "index" in result
        assert "filename" in result
        assert "validation" in result
        assert "metadata" in result
