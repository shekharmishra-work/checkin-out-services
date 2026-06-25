import os
from unittest.mock import MagicMock, patch

from app.services.gcs_service import upload_image


@patch.dict(os.environ, clear=True)
def test_gcs_disabled_upload_image() -> None:
    with patch("app.services.gcs_service.logger") as mock_logger:
        result = upload_image(b"fakebytes", "sess-123", "test.jpg")
        assert result is None
        mock_logger.debug.assert_called_with("GCS not configured — skipping image upload")


@patch.dict(os.environ, {"GCS_BUCKET_NAME": "test-bucket"})
@patch("app.services.gcs_service.storage.Client")
def test_upload_image_success(mock_client_cls: MagicMock) -> None:
    import app.services.gcs_service as gcs_module

    gcs_module._gcs_client = None

    mock_client = MagicMock()
    mock_client_cls.return_value = mock_client

    mock_bucket = MagicMock()
    mock_client.bucket.return_value = mock_bucket

    mock_blob = MagicMock()
    mock_bucket.blob.return_value = mock_blob

    result = upload_image(b"fakebytes", "sess-123", "test.jpg")

    assert result == "gs://test-bucket/Checkin-out/audit/sess-123/test.jpg"
    mock_bucket.blob.assert_called_with("Checkin-out/audit/sess-123/test.jpg")
    mock_blob.upload_from_string.assert_called_with(b"fakebytes", content_type="image/jpeg")


@patch.dict(os.environ, {"GCS_BUCKET_NAME": "test-bucket"})
@patch("app.services.gcs_service.storage.Client")
def test_upload_image_exception_handled(mock_client_cls: MagicMock) -> None:
    import app.services.gcs_service as gcs_module

    gcs_module._gcs_client = None

    mock_client = MagicMock()
    mock_client_cls.return_value = mock_client

    mock_bucket = MagicMock()
    mock_client.bucket.return_value = mock_bucket

    mock_blob = MagicMock()
    mock_bucket.blob.return_value = mock_blob

    mock_blob.upload_from_string.side_effect = Exception("Upload failed")

    with patch("app.services.gcs_service.logger") as mock_logger:
        result = upload_image(b"fakebytes", "sess-123", "test.jpg")

        assert result is None
        expected = (
            "Failed to upload image to GCS Checkin-out/audit/sess-123/test.jpg: Upload failed"
        )
        mock_logger.warning.assert_called_with(expected)
