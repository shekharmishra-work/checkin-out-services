from __future__ import annotations

from datetime import date, datetime
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

from app.main import app
from app.models.validation_models import (
    AssessConditionResult,
    DamageType,
    IdentityResult,
    ImageResult,
    ImageValidationResult,
    MetadataResult,
    PartCondition,
    SubmissionSummary,
    VehicleCondition,
    VehiclePart,
)
from app.services.sheets_service import (
    append_audit_row,
    append_image_rows,
    append_vehicle_part_rows,
    persist_audit_to_sheets,
)

client = TestClient(app)


def test_append_audit_row_success() -> None:
    summary = SubmissionSummary(total=2, passed=1, failed=1, damage_flagged=1)
    identity = IdentityResult(
        status="confirmed",
        detected_plates=["MH12"],
        unique_plates=["MH12"],
        consensus_plate="MH12",
        consensus_color="white",
        identity_reason="Matches",
    )
    vehicle_condition = VehicleCondition(overall_damage_score=5, parts=[])
    created_at = datetime(2026, 6, 22, 12, 0, 0)

    with patch("app.services.sheets_service.sh") as mock_sh:
        mock_worksheet = MagicMock()
        mock_sh.worksheet.return_value = mock_worksheet
        append_audit_row(
            audit_id="audit-123",
            session_id="sess-abc",
            check_type="in",
            summary=summary,
            identity=identity,
            vehicle_condition=vehicle_condition,
            created_at=created_at,
        )
        mock_sh.worksheet.assert_called_once_with("audits")
        mock_worksheet.append_row.assert_called_once_with(
            [
                "audit-123",
                "sess-abc",
                "MH12",
                "in",
                "white",
                "confirmed",
                "Matches",
                2,
                1,
                1,
                1,
                5,
                "2026-06-22 12:00:00",
            ]
        )


def test_append_audit_row_none_vehicle_condition() -> None:
    summary = SubmissionSummary(total=2, passed=1, failed=1, damage_flagged=1)
    identity = IdentityResult(
        status="confirmed",
        detected_plates=["MH12"],
        unique_plates=["MH12"],
        consensus_plate="MH12",
        consensus_color="white",
        identity_reason="Matches",
    )
    created_at = datetime(2026, 6, 22, 12, 0, 0)

    with patch("app.services.sheets_service.sh") as mock_sh:
        mock_worksheet = MagicMock()
        mock_sh.worksheet.return_value = mock_worksheet
        append_audit_row(
            audit_id="audit-123",
            session_id="sess-abc",
            check_type="in",
            summary=summary,
            identity=identity,
            vehicle_condition=None,
            created_at=created_at,
        )
        mock_sh.worksheet.assert_called_once_with("audits")
        mock_worksheet.append_row.assert_called_once_with(
            [
                "audit-123",
                "sess-abc",
                "MH12",
                "in",
                "white",
                "confirmed",
                "Matches",
                2,
                1,
                1,
                1,
                "",
                "2026-06-22 12:00:00",
            ]
        )


def test_append_image_rows_success() -> None:
    results = [
        ImageResult(
            index=1,
            filename="front.jpg",
            validation=ImageValidationResult(
                index=1,
                valid=True,
                reason=None,
                plate="MH12",
                color="white",
                damage_detected=True,
                damage_details="Scratch",
            ),
            metadata=MetadataResult(
                has_exif=True,
                capture_date=date(2026, 6, 22),
                current_date=date(2026, 6, 22),
                is_same_day=True,
                meta_reason=None,
            ),
        )
    ]
    with patch("app.services.sheets_service.sh") as mock_sh:
        mock_worksheet = MagicMock()
        mock_sh.worksheet.return_value = mock_worksheet
        append_image_rows("audit-123", results)
        mock_sh.worksheet.assert_called_once_with("audit_images")
        mock_worksheet.append_rows.assert_called_once_with(
            [
                [
                    "audit-123",
                    1,
                    "front.jpg",
                    True,
                    "",
                    "MH12",
                    "white",
                    True,
                    "Scratch",
                    True,
                    "2026-06-22",
                    "2026-06-22",
                    True,
                ]
            ]
        )


def test_append_vehicle_part_rows_success() -> None:
    parts = [
        PartCondition(
            part=VehiclePart.front_bumper,
            visible_in_image=True,
            source_image_index=1,
            damaged=True,
            damage_types=[DamageType.dent, DamageType.scratch],
            severity=2,
            confidence=0.85,
        ),
        PartCondition(
            part=VehiclePart.rear_bumper,
            visible_in_image=False,
            source_image_index=None,
            damaged=False,
            damage_types=[],
            severity=0,
            confidence=0.0,
        ),
    ]
    with patch("app.services.sheets_service.sh") as mock_sh:
        mock_worksheet = MagicMock()
        mock_sh.worksheet.return_value = mock_worksheet
        append_vehicle_part_rows("audit-123", parts)
        mock_sh.worksheet.assert_called_once_with("audit_vehicle_parts")
        mock_worksheet.append_rows.assert_called_once_with(
            [
                [
                    "audit-123",
                    "front_bumper",
                    True,
                    1,
                    True,
                    "dent,scratch",
                    2,
                    0.85,
                ],
                [
                    "audit-123",
                    "rear_bumper",
                    False,
                    "",
                    False,
                    "",
                    0,
                    0.0,
                ],
            ]
        )


def test_persist_audit_to_sheets_swallows_errors() -> None:
    with (
        patch(
            "app.services.sheets_service.append_audit_row",
            side_effect=Exception("Sheets error"),
        ),
        patch("app.services.sheets_service.logger") as mock_logger,
    ):
        audit_id = persist_audit_to_sheets(
            session_id="sess-abc",
            check_type="in",
            summary=MagicMock(),
            identity=MagicMock(),
            vehicle_condition=None,
            results=[],
            created_at=datetime.now(),
        )
        assert audit_id is not None
        mock_logger.error.assert_called_once()


def test_router_endpoints_swallow_sheets_errors() -> None:
    """Verify endpoints return 200 even when sheets_service fails or raises exception."""
    # 1. Mock background tasks / sheets service to raise
    with (
        patch(
            "app.services.sheets_service.append_audit_row",
            side_effect=RuntimeError("Google Sheets failed"),
        ),
        patch(
            "app.routers.image_validation.gemini_validate",
            return_value=[
                ImageValidationResult(
                    index=1,
                    valid=True,
                    reason=None,
                    plate="MH12",
                    color="white",
                    damage_detected=False,
                    damage_details=None,
                )
            ],
        ),
        patch(
            "app.routers.image_validation.extract_metadata_status",
            return_value=MetadataResult(
                has_exif=True,
                capture_date=date.today(),
                current_date=date.today(),
                is_same_day=True,
                meta_reason=None,
            ),
        ),
        patch(
            "app.routers.image_validation.check_vehicle_identity",
            return_value=IdentityResult(
                status="confirmed",
                detected_plates=["MH12"],
                unique_plates=["MH12"],
                consensus_plate="MH12",
                consensus_color="white",
                identity_reason=None,
            ),
        ),
    ):
        files = [("images", ("front.jpg", b"fake-bytes", "image/jpeg"))]
        response = client.post("/api/v1/validate-images", files=files)
        assert response.status_code == 200
        data = response.json()
        assert data["submission_summary"]["total"] == 1

    # 2. Mock assess-condition endpoint
    parts = [
        PartCondition(
            part=VehiclePart(name),
            visible_in_image=True,
            source_image_index=1,
            damaged=False,
            damage_types=[],
            severity=0,
            confidence=0.9,
        )
        for name in [p.value for p in VehiclePart]
    ]
    fake_vc = VehicleCondition(overall_damage_score=0, parts=parts)

    with (
        patch(
            "app.services.sheets_service.append_audit_row",
            side_effect=RuntimeError("Google Sheets failed"),
        ),
        patch(
            "app.routers.image_validation.validate_and_assess",
            return_value=AssessConditionResult(
                submission_summary=SubmissionSummary(total=1, passed=1, failed=0, damage_flagged=0),
                identity=IdentityResult(
                    status="confirmed",
                    detected_plates=["MH12"],
                    unique_plates=["MH12"],
                    consensus_plate="MH12",
                    consensus_color="white",
                    identity_reason=None,
                ),
                results=[
                    ImageResult(
                        index=1,
                        filename="front.jpg",
                        validation=ImageValidationResult(
                            index=1,
                            valid=True,
                            reason=None,
                            plate="MH12",
                            color="white",
                            damage_detected=False,
                            damage_details=None,
                        ),
                        metadata=MetadataResult(
                            has_exif=True,
                            capture_date=date.today(),
                            current_date=date.today(),
                            is_same_day=True,
                            meta_reason=None,
                        ),
                    )
                ],
                vehicle_condition=fake_vc,
            ),
        ),
    ):
        files = [("images", ("front.jpg", b"fake-bytes", "image/jpeg"))]
        response = client.post("/api/v1/assess-condition", files=files)
        assert response.status_code == 200
        data = response.json()
        assert data["submission_summary"]["total"] == 1
        assert len(data["vehicle_condition"]["parts"]) == 25
