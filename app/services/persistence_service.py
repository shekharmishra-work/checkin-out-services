import logging
from datetime import datetime

from app.models.validation_models import (
    IdentityResult,
    ImageResult,
    SubmissionSummary,
    VehicleCondition,
)
from app.services.bq_service import (
    insert_audit_row,
    insert_image_rows,
    insert_vehicle_part_rows,
    upsert_llm_call_stats,
)
from app.services.gcs_service import upload_image
from app.services.sheets_service import persist_audit_to_sheets

logger = logging.getLogger(__name__)


def persist_all_outputs(
    audit_id: str,
    session_id: str,
    check_type: str,
    image_bytes_list: list[bytes],
    filenames: list[str],
    summary: SubmissionSummary,
    identity: IdentityResult,
    results: list[ImageResult],
    vehicle_condition: VehicleCondition | None,
    llm_used: str,
    created_at: datetime,
) -> None:
    """Orchestrates writing outputs to GCS, BigQuery, and Google Sheets safely.

    Each step is isolated so that a failure in one persistence mechanism
    does not prevent the others from executing.
    """

    # 1. Upload images to GCS
    gcs_uris: list[str | None] = []
    try:
        for img_bytes, fname in zip(image_bytes_list, filenames, strict=False):
            uri = upload_image(img_bytes, session_id, fname)
            gcs_uris.append(uri)
    except Exception as e:
        logger.error(f"Failed during GCS image upload orchestration: {e}")
        # Pad with Nones if failed to match the length of results
        while len(gcs_uris) < len(results):
            gcs_uris.append(None)

    # 2. Write to BigQuery
    try:
        insert_audit_row(
            audit_id=audit_id,
            session_id=session_id,
            check_type=check_type,
            summary=summary,
            identity=identity,
            vehicle_condition=vehicle_condition,
            llm_used=llm_used,
            created_at=created_at,
        )
        insert_image_rows(audit_id=audit_id, results=results, gcs_uris=gcs_uris)
        if vehicle_condition:
            insert_vehicle_part_rows(audit_id=audit_id, parts=vehicle_condition.parts)
        upsert_llm_call_stats(model_name=llm_used, success=True)
    except Exception as e:
        logger.error(f"Failed during BigQuery orchestration: {e}")

    # 3. Mirror to Sheets (existing function, unchanged)
    # The existing function generates its own audit_id but takes session_id
    try:
        persist_audit_to_sheets(
            session_id=session_id,
            check_type=check_type,
            summary=summary,
            identity=identity,
            vehicle_condition=vehicle_condition,
            results=results,
            created_at=created_at,
        )
    except Exception as e:
        logger.error(f"Failed during Sheets orchestration: {e}")
