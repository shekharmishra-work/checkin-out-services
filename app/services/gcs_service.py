import logging
import os

from google.cloud import storage  # type: ignore[attr-defined]

logger = logging.getLogger(__name__)

_gcs_client: storage.Client | None = None


def _gcs_enabled() -> bool:
    return bool(os.environ.get("GCS_BUCKET_NAME"))


def upload_image(image_bytes: bytes, session_id: str, filename: str) -> str | None:
    if not _gcs_enabled():
        logger.debug("GCS not configured — skipping image upload")
        return None

    global _gcs_client
    if _gcs_client is None:
        try:
            # We don't require an explicit project ID for GCS instantiation
            # if running in a GCP environment or if credentials file specifies it.
            _gcs_client = storage.Client()
        except Exception as e:
            logger.warning(f"Could not initialize GCS client: {e}")
            return None

    bucket_name = os.environ.get("GCS_BUCKET_NAME")
    if not bucket_name:
        return None

    blob_path = f"Checkin-out/audit/{session_id}/{filename}"

    try:
        bucket = _gcs_client.bucket(bucket_name)
        blob = bucket.blob(blob_path)
        blob.upload_from_string(image_bytes, content_type="image/jpeg")
        return f"gs://{bucket_name}/{blob_path}"
    except Exception as e:
        logger.warning(f"Failed to upload image to GCS {blob_path}: {e}")
        return None
