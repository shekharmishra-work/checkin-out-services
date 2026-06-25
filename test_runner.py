import os
import sys
from datetime import datetime
from uuid import uuid4

# Adjust Python path to allow importing app
sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))

# Load dotenv to get all configurations
from dotenv import load_dotenv

load_dotenv()

from app.models.validation_models import (
    IdentityResult,
    ImageResult,
    ImageValidationResult,
    MetadataResult,
    PartCondition,
    SubmissionSummary,
    VehicleCondition,
    VehiclePart,
)
from app.services.bq_service import ensure_tables_exist
from app.services.persistence_service import persist_all_outputs


def run_test():
    print("1. Ensuring BigQuery tables exist...")
    ensure_tables_exist()

    print("\n2. Preparing dummy data for testing...")
    audit_id = str(uuid4())
    session_id = f"sess-{uuid4().hex[:8]}-test"
    check_type = "in"
    created_at = datetime.now()

    summary = SubmissionSummary(
        total=1, passed=1, failed=0, damage_flagged=0
    )
    identity = IdentityResult(
        is_same_vehicle=True,
        confidence=0.99,
        consensus_plate="TEST9999",
        consensus_color="blue",
        status="confirmed",
        detected_plates=["TEST9999"],
        unique_plates=["TEST9999"],
        identity_reason=None
    )

    # A tiny random byte sequence to act as dummy image bytes
    dummy_image_bytes = os.urandom(1024)

    results = [
        ImageResult(
            index=1,
            filename="test_image.jpg",
            validation=ImageValidationResult(
                index=1,
                valid=True,
                damage_detected=False,
                plate="TEST9999",
                color="blue",
                reason=None,
                damage_details=None
            ),
            metadata=MetadataResult(
                has_exif=False,
                current_date=created_at.date(),
                capture_date=created_at.date(),
                is_same_day=True,
                meta_reason=None
            )
        )
    ]

    vehicle_condition = VehicleCondition(
        overall_damage_score=0,
        parts=[
            PartCondition(
                part=VehiclePart.front_bumper,
                visible_in_image=True,
                source_image_index=1,
                damaged=False,
                damage_types=[],
                severity=0,
                confidence=0.99
            )
        ]
    )

    print("\n3. Executing persist_all_outputs orchestrator...")
    print(f"   Audit ID: {audit_id}")
    try:
        persist_all_outputs(
            audit_id=audit_id,
            session_id=session_id,
            check_type=check_type,
            image_bytes_list=[dummy_image_bytes],
            filenames=["test_image.jpg"],
            summary=summary,
            identity=identity,
            results=results,
            vehicle_condition=vehicle_condition,
            llm_used="gemini-2.5-flash-test",
            created_at=created_at,
        )
        print("\nSUCCESS! Persistence sequence completed without unhandled exceptions.")
        print("\nPlease verify:")
        print("  - BigQuery: Check the AI_checkin_out dataset tables for rows.")
        print("  - GCS: Check the dk-image-storage-common bucket for Checkin-out/in/<audit_id>/test_image.jpg")
        print("  - Google Sheets: Check the audits, audit_images, and audit_vehicle_parts tabs.")
    except Exception as e:
        print(f"\nERROR: Unhandled exception during persistence orchestration: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    run_test()
