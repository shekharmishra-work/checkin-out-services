from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


@patch("app.services.persistence_service.upload_image")
@patch("app.services.persistence_service.insert_audit_row")
@patch("app.services.persistence_service.persist_audit_to_sheets")
@patch("app.routers.image_validation.gemini_validate")
@patch("app.routers.image_validation.extract_metadata_status")
@patch("app.routers.image_validation.check_vehicle_identity")
def test_validate_images_resilience_background_tasks(
    mock_identity: MagicMock,
    mock_extract: MagicMock,
    mock_gemini: MagicMock,
    mock_sheets: MagicMock,
    mock_bq: MagicMock,
    mock_gcs: MagicMock,
) -> None:
    # Mock successful synchronous path
    from datetime import date

    from app.models.validation_models import (
        IdentityResult,
        ImageValidationResult,
        MetadataResult,
    )

    mock_gemini.return_value = [
        ImageValidationResult(
            index=1,
            valid=True,
            reason=None,
            plate=None,
            color=None,
            damage_detected=False,
            damage_details=None,
        )
    ]
    mock_extract.return_value = MetadataResult(
        has_exif=False,
        capture_date=None,
        current_date=date.today(),
        is_same_day=False,
        meta_reason=None,
    )
    mock_identity.return_value = IdentityResult(
        status="confirmed",
        detected_plates=[],
        unique_plates=[],
        consensus_plate=None,
        consensus_color=None,
        identity_reason=None,
    )

    # Force underlying persistence layers to raise exceptions
    mock_gcs.side_effect = Exception("GCS failure")
    mock_bq.side_effect = Exception("BQ failure")
    mock_sheets.side_effect = Exception("Sheets failure")

    # Call the endpoint
    response = client.post(
        "/api/v1/validate-images",
        files=[("images", ("test.jpg", b"fake_image_bytes", "image/jpeg"))],
    )

    # Ensure it still returns 200 despite background task "failure"
    assert response.status_code == 200
    assert "submission_summary" in response.json()
