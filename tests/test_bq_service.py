import os
from datetime import datetime
from unittest.mock import MagicMock, patch

from google.api_core import exceptions

from app.models.validation_models import (
    IdentityResult,
    SubmissionSummary,
)
from app.services.bq_service import (
    ensure_tables_exist,
    insert_audit_row,
    upsert_llm_call_stats,
)


@patch.dict(os.environ, clear=True)
def test_bq_disabled_ensure_tables_exist() -> None:
    # With no env vars, _bq_enabled() returns False
    with patch("app.services.bq_service.logger") as mock_logger:
        ensure_tables_exist()
        mock_logger.info.assert_called_with("BigQuery not configured — skipping table creation")


@patch.dict(os.environ, {"GCP_PROJECT_ID": "test-project", "BQ_DATASET_ID": "test-dataset"})
@patch("app.services.bq_service.bigquery.Client")
def test_ensure_tables_exist_forbidden_continues(mock_client_cls: MagicMock) -> None:
    import app.services.bq_service as bq_module

    bq_module._bq_client = None

    mock_client = MagicMock()
    mock_client_cls.return_value = mock_client

    # First table creation fails with Forbidden, second succeeds
    mock_client.create_table.side_effect = [
        exceptions.Forbidden("Permission denied"),  # type: ignore[no-untyped-call]
        None,
        None,
        None,
    ]

    with patch("app.services.bq_service.logger") as mock_logger:
        ensure_tables_exist()

        # Verify it attempted to create all 4 tables
        assert mock_client.create_table.call_count == 4
        # Verify it logged the warning for the first table
        mock_logger.warning.assert_called_with(
            "Could not create/verify table AI_audits: 403 Permission denied"
        )
        # Verify it logged success for the others
        mock_logger.info.assert_any_call("Table AI_audit_images ready")


@patch.dict(os.environ, {"GCP_PROJECT_ID": "test-project", "BQ_DATASET_ID": "test-dataset"})
@patch("app.services.bq_service.bigquery.Client")
def test_insert_audit_row_calls_insert_rows_json(mock_client_cls: MagicMock) -> None:
    import app.services.bq_service as bq_module

    bq_module._bq_client = None

    mock_client = MagicMock()
    mock_client_cls.return_value = mock_client
    mock_client.insert_rows_json.return_value = []

    summary = SubmissionSummary(total=1, passed=1, failed=0, damage_flagged=0)
    identity = IdentityResult(
        status="confirmed",
        detected_plates=["A123"],
        unique_plates=["A123"],
        consensus_plate="A123",
        consensus_color="red",
        identity_reason=None,
    )
    created_at = datetime.now()

    insert_audit_row(
        audit_id="audit-123",
        session_id="sess-456",
        check_type="in",
        summary=summary,
        identity=identity,
        vehicle_condition=None,
        llm_used="gemini-test",
        created_at=created_at,
    )

    mock_client.insert_rows_json.assert_called_once()
    table_id, rows = mock_client.insert_rows_json.call_args[0]

    assert table_id == "test-project.test-dataset.AI_audits"
    assert len(rows) == 1
    assert rows[0]["audit_id"] == "audit-123"
    assert rows[0]["session_id"] == "sess-456"
    assert rows[0]["consensus_plate"] == "A123"
    assert rows[0]["total_images"] == 1


@patch.dict(os.environ, {"GCP_PROJECT_ID": "test-project", "BQ_DATASET_ID": "test-dataset"})
@patch("app.services.bq_service.bigquery.Client")
def test_upsert_llm_call_stats_builds_correct_params(mock_client_cls: MagicMock) -> None:
    import app.services.bq_service as bq_module

    bq_module._bq_client = None

    mock_client = MagicMock()
    mock_client_cls.return_value = mock_client

    # Mock empty result for SELECT query (triggering INSERT)
    mock_client.query.return_value.result.return_value = []
    # If list(query) is called:
    mock_client.query.side_effect = [
        [],  # select result
        MagicMock(),  # insert/update result
    ]

    upsert_llm_call_stats(model_name="test-model", success=False)

    assert mock_client.query.call_count == 2

    select_call = mock_client.query.call_args_list[0]
    select_job_config = select_call[1]["job_config"]
    assert len(select_job_config.query_parameters) == 2

    insert_call = mock_client.query.call_args_list[1]
    insert_job_config = insert_call[1]["job_config"]
    # For a failed call, it should have 4 params (date, model_name, failed_count, last_error)
    assert len(insert_job_config.query_parameters) == 4

    # Verify the failed_count param
    failed_count_param = next(
        p for p in insert_job_config.query_parameters if p.name == "failed_count"
    )
    assert failed_count_param.value == 1
