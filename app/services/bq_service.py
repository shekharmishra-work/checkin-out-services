import logging
import os
from datetime import date, datetime

from google.api_core import exceptions
from google.cloud import bigquery

from app.models.validation_models import (
    IdentityResult,
    ImageResult,
    PartCondition,
    SubmissionSummary,
    VehicleCondition,
)
from app.services.bq_schema import TABLE_SCHEMAS

logger = logging.getLogger(__name__)

_bq_client: bigquery.Client | None = None


def _bq_enabled() -> bool:
    return bool(os.environ.get("GCP_PROJECT_ID")) and bool(os.environ.get("BQ_DATASET_ID"))


def _get_client() -> bigquery.Client | None:
    global _bq_client
    if not _bq_enabled():
        return None
    if _bq_client is None:
        _bq_client = bigquery.Client(project=os.environ["GCP_PROJECT_ID"])
    return _bq_client


def ensure_tables_exist() -> None:
    if not _bq_enabled():
        logger.info("BigQuery not configured — skipping table creation")
        return

    client = _get_client()
    if client is None:
        return

    project = os.environ["GCP_PROJECT_ID"]
    dataset = os.environ["BQ_DATASET_ID"]

    for table_name, schema in TABLE_SCHEMAS.items():
        table_id = f"{project}.{dataset}.{table_name}"
        try:
            client.create_table(bigquery.Table(table_id, schema=schema), exists_ok=True)
            logger.info(f"Table {table_name} ready")
        except (exceptions.Forbidden, exceptions.NotFound) as e:
            logger.warning(f"Could not create/verify table {table_name}: {e}")
        except Exception as e:
            logger.warning(f"Unexpected error verifying table {table_name}: {e}")


def insert_audit_row(
    audit_id: str,
    session_id: str,
    check_type: str,
    summary: SubmissionSummary,
    identity: IdentityResult,
    vehicle_condition: VehicleCondition | None,
    llm_used: str,
    created_at: datetime,
) -> None:
    if not _bq_enabled():
        return
    client = _get_client()
    if client is None:
        return

    project = os.environ["GCP_PROJECT_ID"]
    dataset = os.environ["BQ_DATASET_ID"]
    table_id = f"{project}.{dataset}.AI_audits"

    overall_damage_score = (
        vehicle_condition.overall_damage_score if vehicle_condition is not None else None
    )

    row = {
        "audit_id": audit_id,
        "session_id": session_id,
        "driver_id": None,  # Not present in current models
        "check_type": check_type,
        "consensus_plate": identity.consensus_plate,
        "consensus_color": identity.consensus_color,
        "identity_status": identity.status,
        "identity_reason": identity.identity_reason,
        "total_images": summary.total,
        "passed_images": summary.passed,
        "failed_images": summary.failed,
        "damage_flagged_count": summary.damage_flagged,
        "overall_damage_score": overall_damage_score,
        "llm_used": llm_used,
        "input_timestamp": created_at.isoformat(),
        "output_timestamp": datetime.now().isoformat(),
        "processing_ms": None,  # Can be added later if tracked
    }

    try:
        errors = client.insert_rows_json(table_id, [row])
        if errors:
            logger.error(f"Failed to insert audit row: {errors}")
    except Exception as e:
        logger.error(f"Error inserting audit row to BQ: {e}")


def insert_image_rows(
    audit_id: str, results: list[ImageResult], gcs_uris: list[str | None]
) -> None:
    if not _bq_enabled():
        return
    client = _get_client()
    if client is None:
        return

    project = os.environ["GCP_PROJECT_ID"]
    dataset = os.environ["BQ_DATASET_ID"]
    table_id = f"{project}.{dataset}.AI_audit_images"

    rows = []
    for res, gcs_uri in zip(results, gcs_uris, strict=False):
        capture_date = res.metadata.capture_date.isoformat() if res.metadata.capture_date else None
        current_date = res.metadata.current_date.isoformat() if res.metadata.current_date else None

        rows.append(
            {
                "audit_id": audit_id,
                "image_index": res.index,
                "filename": res.filename,
                "gcs_uri": gcs_uri,
                "valid": res.validation.valid,
                "reason": res.validation.reason,
                "plate": res.validation.plate,
                "color": res.validation.color,
                "damage_detected": res.validation.damage_detected,
                "damage_details": res.validation.damage_details,
                "has_exif": res.metadata.has_exif,
                "capture_date": capture_date,
                "current_date": current_date,
                "is_same_day": res.metadata.is_same_day,
            }
        )

    if not rows:
        return

    try:
        errors = client.insert_rows_json(table_id, rows)
        if errors:
            logger.error(f"Failed to insert image rows: {errors}")
    except Exception as e:
        logger.error(f"Error inserting image rows to BQ: {e}")


def insert_vehicle_part_rows(audit_id: str, parts: list[PartCondition]) -> None:
    if not _bq_enabled():
        return
    client = _get_client()
    if client is None:
        return

    project = os.environ["GCP_PROJECT_ID"]
    dataset = os.environ["BQ_DATASET_ID"]
    table_id = f"{project}.{dataset}.AI_audit_vehicle_parts"

    rows = []
    for part in parts:
        damage_types_str = (
            ",".join([t.value for t in part.damage_types]) if part.damage_types else None
        )
        rows.append(
            {
                "audit_id": audit_id,
                "part": part.part.value,
                "visible_in_image": part.visible_in_image,
                "source_image_index": part.source_image_index,
                "damaged": part.damaged,
                "damage_types": damage_types_str,
                "severity": part.severity,
                "confidence": part.confidence,
            }
        )

    if not rows:
        return

    try:
        errors = client.insert_rows_json(table_id, rows)
        if errors:
            logger.error(f"Failed to insert vehicle part rows: {errors}")
    except Exception as e:
        logger.error(f"Error inserting vehicle part rows to BQ: {e}")


def upsert_llm_call_stats(model_name: str, success: bool) -> None:
    if not _bq_enabled():
        return
    client = _get_client()
    if client is None:
        return

    project = os.environ["GCP_PROJECT_ID"]
    dataset = os.environ["BQ_DATASET_ID"]
    table_id = f"{project}.{dataset}.AI_llm_api_calls"

    today = date.today()

    select_query = f"""
        SELECT 1
        FROM `{table_id}`
        WHERE date = @date AND model_name = @model_name
        LIMIT 1
    """
    job_config = bigquery.QueryJobConfig(
        query_parameters=[
            bigquery.ScalarQueryParameter("date", "DATE", today),
            bigquery.ScalarQueryParameter("model_name", "STRING", model_name),
        ]
    )

    try:
        results = list(client.query(select_query, job_config=job_config))

        if results:
            # Row exists, update it
            failed_inc = 0 if success else 1
            last_error_update = ""
            if not success:
                last_error_update = ", last_error = @last_error"

            update_query = f"""
                UPDATE `{table_id}`
                SET total_calls = total_calls + 1,
                    failed_count = failed_count + @failed_inc
                    {last_error_update}
                WHERE date = @date AND model_name = @model_name
            """

            update_params = [
                bigquery.ScalarQueryParameter("failed_inc", "INTEGER", failed_inc),
                bigquery.ScalarQueryParameter("date", "DATE", today),
                bigquery.ScalarQueryParameter("model_name", "STRING", model_name),
            ]
            if not success:
                # In a real scenario we'd pass the actual error message, but here we just flag it
                update_params.append(
                    bigquery.ScalarQueryParameter("last_error", "STRING", "API Call Failed")
                )

            update_config = bigquery.QueryJobConfig(query_parameters=update_params)
            client.query(update_query, job_config=update_config).result()
        else:
            # Row doesn't exist, insert new
            failed_count = 0 if success else 1
            last_error = None if success else "API Call Failed"

            insert_query = f"""
                INSERT INTO `{table_id}` (date, model_name, total_calls, failed_count, last_error)
                VALUES (@date, @model_name, 1, @failed_count, @last_error)
            """
            insert_params = [
                bigquery.ScalarQueryParameter("date", "DATE", today),
                bigquery.ScalarQueryParameter("model_name", "STRING", model_name),
                bigquery.ScalarQueryParameter("failed_count", "INTEGER", failed_count),
                bigquery.ScalarQueryParameter("last_error", "STRING", last_error),
            ]
            insert_config = bigquery.QueryJobConfig(query_parameters=insert_params)
            client.query(insert_query, job_config=insert_config).result()

    except Exception as e:
        logger.error(f"Error upserting LLM call stats: {e}")
