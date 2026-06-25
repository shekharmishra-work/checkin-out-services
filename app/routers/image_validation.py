"""FastAPI router for image-validation endpoints.

Two endpoints are available — they accept identical multipart/form-data but
serve different stages of the fleet workflow:

POST /api/v1/validate-images  (gate check — lightweight, 1 Gemini call)
    Is each image a clear, valid photo of a vehicle?
    Fast. Used to reject bad uploads early.
    UNCHANGED — do not modify.

POST /api/v1/assess-condition  (full inspection — 2 Gemini calls)
    Gate check PLUS a structured part-by-part damage snapshot across all images.
    Used at check-in / check-out. The backend team stores the vehicle_condition
    JSON for later comparison between check-in and check-out states.
"""

from __future__ import annotations

import logging
from datetime import date, datetime
from uuid import uuid4

from fastapi import APIRouter, BackgroundTasks, File, HTTPException, UploadFile

from app.models.validation_models import (
    AssessConditionResult,
    ImageResult,
    SubmissionSummary,
    ValidateImagesResponse,
)
from app.services.gemini_service import validate_and_assess
from app.services.gemini_service import validate_images as gemini_validate
from app.services.identity_service import check_vehicle_identity
from app.services.metadata_service import extract_metadata_status
from app.services.persistence_service import persist_all_outputs

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1", tags=["image-validation"])


# ── Endpoint 1: gate check only ───────────────────────────────────────────────


@router.post("/validate-images", response_model=ValidateImagesResponse)
async def validate_images_endpoint(
    background_tasks: BackgroundTasks,
    images: list[UploadFile] = File(...),
    check_type: str = "in",
) -> ValidateImagesResponse:
    """Validate a batch of EV taxi images.

    Steps:
    1. Read raw bytes from every uploaded file.
    2. Extract EXIF metadata from raw bytes (before any preprocessing).
    3. Send all images to Gemini in a single call.
    4. Run vehicle-identity cross-check on the Gemini results.
    5. Assemble and return the compound response.

    Always returns HTTP 200 — the caller interprets the flags.
    """
    # 1. Read raw bytes and filenames up-front
    raw_bytes_list: list[bytes] = []
    filenames: list[str] = []
    for upload in images:
        raw_bytes_list.append(await upload.read())
        filenames.append(upload.filename or f"image_{len(filenames) + 1}")

    # 2. Metadata extraction (on raw bytes)
    metadata_results = [extract_metadata_status(b) for b in raw_bytes_list]

    # 3. Single Gemini call for all images
    try:
        validation_results = gemini_validate(raw_bytes_list)
    except Exception as exc:
        logger.error("Gemini validation failed: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=f"Gemini validation failed: {exc}") from exc

    # 4. Identity cross-check
    identity = check_vehicle_identity(validation_results)

    # 5. Assemble per-image compound results (use 1-based index to match Gemini)
    image_results: list[ImageResult] = []
    for i, (val, meta, fname) in enumerate(
        zip(validation_results, metadata_results, filenames, strict=False), start=1
    ):
        image_results.append(
            ImageResult(
                index=i,
                filename=fname,
                validation=val,
                metadata=meta,
            )
        )

    # 6. Summary counts
    total = len(image_results)
    passed = sum(1 for r in validation_results if r.valid)
    failed = total - passed
    damage_flagged = sum(1 for r in validation_results if r.damage_detected)

    summary = SubmissionSummary(
        total=total,
        passed=passed,
        failed=failed,
        damage_flagged=damage_flagged,
    )

    response = ValidateImagesResponse(
        submission_summary=summary,
        identity=identity,
        results=image_results,
    )

    session_id = f"sess-{uuid4().hex[:8]}-{date.today()}-{check_type}"
    background_tasks.add_task(
        persist_all_outputs,
        audit_id=str(uuid4()),
        session_id=session_id,
        check_type=check_type,
        image_bytes_list=raw_bytes_list,
        filenames=filenames,
        summary=response.submission_summary,
        identity=response.identity,
        results=response.results,
        vehicle_condition=None,
        llm_used="gemini-2.5-flash",
        created_at=datetime.now(),
    )

    return response


# ── Endpoint 2: full inspection (gate check + damage snapshot) ────────────────


@router.post("/assess-condition", response_model=AssessConditionResult)
async def assess_condition_endpoint(
    background_tasks: BackgroundTasks,
    images: list[UploadFile] = File(...),
    check_type: str = "in",
) -> AssessConditionResult:
    """Full vehicle inspection: gate check + structured part-by-part damage snapshot.

    Makes exactly TWO Gemini API calls internally via validate_and_assess():
      Call 1 — per-image gate check (same logic as /api/v1/validate-images)
      Call 2 — cross-image damage snapshot for all 25 vehicle parts

    The vehicle_condition block in the response is the structured damage JSON
    that the backend team stores for check-in / check-out comparison.

    If the damage assessment (Call 2) fails, vehicle_condition will be null —
    the gate check result is still fully valid and returned with HTTP 200.

    Always returns HTTP 200 — the caller interprets the flags.
    """
    raw_bytes_list: list[bytes] = []
    filenames: list[str] = []
    for upload in images:
        raw_bytes_list.append(await upload.read())
        filenames.append(upload.filename or f"image_{len(filenames) + 1}")

    try:
        result = validate_and_assess(raw_bytes_list, filenames)
    except Exception as exc:
        logger.error("validate_and_assess failed: %s", exc, exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Assessment failed: {exc}",
        ) from exc

    session_id = f"sess-{uuid4().hex[:8]}-{date.today()}-{check_type}"
    background_tasks.add_task(
        persist_all_outputs,
        audit_id=str(uuid4()),
        session_id=session_id,
        check_type=check_type,
        image_bytes_list=raw_bytes_list,
        filenames=filenames,
        summary=result.submission_summary,
        identity=result.identity,
        results=result.results,
        vehicle_condition=result.vehicle_condition,
        llm_used="gemini-2.5-flash",
        created_at=datetime.now(),
    )

    return result
