from __future__ import annotations

import logging
import os
from datetime import datetime
from uuid import uuid4

import gspread

from app.core.config import get_settings
from app.models.validation_models import (
    IdentityResult,
    ImageResult,
    PartCondition,
    SubmissionSummary,
    VehicleCondition,
)

logger = logging.getLogger(__name__)

# Initialize client and spreadsheet once at module load
settings = get_settings()
credentials_path = settings.google_sheets_credentials_path
spreadsheet_id = settings.google_sheets_spreadsheet_id

gc: gspread.Client | None = None
sh: gspread.Spreadsheet | None = None

try:
    if os.path.exists(credentials_path):
        gc = gspread.service_account(filename=credentials_path)
    else:
        import google.auth

        credentials, _ = google.auth.default(
            scopes=[
                "https://www.googleapis.com/auth/spreadsheets",
                "https://www.googleapis.com/auth/drive",
            ]
        )
        gc = gspread.authorize(credentials)
    sh = gc.open_by_key(spreadsheet_id)
except Exception as e:
    logger.error(f"Failed to initialize Google Sheets client at module load: {e}", exc_info=True)


def append_audit_row(
    audit_id: str,
    session_id: str,
    check_type: str,
    summary: SubmissionSummary,
    identity: IdentityResult,
    vehicle_condition: VehicleCondition | None,
    created_at: datetime,
) -> None:
    if sh is None:
        raise RuntimeError("Google Sheets client is not initialized")

    sheet = sh.worksheet("audits")
    overall_damage_score = (
        vehicle_condition.overall_damage_score if vehicle_condition is not None else ""
    )
    created_at_str = created_at.strftime("%Y-%m-%d %H:%M:%S")

    row: list[str | int | float] = [
        audit_id,
        session_id,
        identity.consensus_plate or "",
        check_type,
        identity.consensus_color or "",
        identity.status,
        identity.identity_reason or "",
        summary.total,
        summary.passed,
        summary.failed,
        summary.damage_flagged,
        overall_damage_score,
        created_at_str,
    ]
    sheet.append_row(row)


def append_image_rows(audit_id: str, results: list[ImageResult]) -> None:
    if sh is None:
        raise RuntimeError("Google Sheets client is not initialized")

    sheet = sh.worksheet("audit_images")
    rows: list[list[str | int | float]] = []
    for res in results:
        rows.append(
            [
                audit_id,
                res.index,
                res.filename,
                res.validation.valid,
                res.validation.reason or "",
                res.validation.plate or "",
                res.validation.color or "",
                res.validation.damage_detected,
                res.validation.damage_details or "",
                res.metadata.has_exif,
                str(res.metadata.capture_date) if res.metadata.capture_date is not None else "",
                str(res.metadata.current_date),
                res.metadata.is_same_day,
            ]
        )
    sheet.append_rows(rows)


def append_vehicle_part_rows(audit_id: str, parts: list[PartCondition]) -> None:
    if sh is None:
        raise RuntimeError("Google Sheets client is not initialized")

    sheet = sh.worksheet("audit_vehicle_parts")
    rows: list[list[str | int | float]] = []
    for part in parts:
        damage_types_str = (
            ",".join([t.value for t in part.damage_types]) if part.damage_types else ""
        )
        rows.append(
            [
                audit_id,
                part.part.value,
                part.visible_in_image,
                part.source_image_index if part.source_image_index is not None else "",
                part.damaged,
                damage_types_str,
                part.severity,
                part.confidence,
            ]
        )
    sheet.append_rows(rows)


def persist_audit_to_sheets(
    session_id: str,
    check_type: str,
    summary: SubmissionSummary,
    identity: IdentityResult,
    vehicle_condition: VehicleCondition | None,
    results: list[ImageResult],
    created_at: datetime,
) -> str:
    audit_id = str(uuid4())
    try:
        append_audit_row(
            audit_id=audit_id,
            session_id=session_id,
            check_type=check_type,
            summary=summary,
            identity=identity,
            vehicle_condition=vehicle_condition,
            created_at=created_at,
        )
        append_image_rows(audit_id=audit_id, results=results)
        if vehicle_condition is not None:
            append_vehicle_part_rows(audit_id=audit_id, parts=vehicle_condition.parts)
    except Exception as e:
        logger.error(f"Failed to persist audit to Sheets: {e}", exc_info=True)

    return audit_id
