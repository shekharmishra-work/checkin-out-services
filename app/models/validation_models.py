"""Pydantic request / response models for the image-validation feature."""

from __future__ import annotations

from datetime import date
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel

# ── Metadata ──────────────────────────────────────────────────────────────────


class MetadataResult(BaseModel):
    """EXIF metadata extraction result for a single image."""

    has_exif: bool
    capture_date: date | None       # parsed from EXIF DateTimeOriginal, None if absent
    current_date: date              # datetime.date.today() at time of request, always present
    is_same_day: bool                # capture_date == current_date, False if capture_date is None
    meta_reason: str | None          # short text when has_exif is False or capture_date is None


# ── Gemini vision ─────────────────────────────────────────────────────────────


class ImageValidationResult(BaseModel):
    """Per-image result returned by the Gemini vision service."""

    index: int
    valid: bool
    reason: str | None
    plate: str | None  # uppercase, no spaces; None if not visible
    color: str | None  # dominant exterior colour, lowercase
    damage_detected: bool
    damage_details: str | None


# ── Identity ──────────────────────────────────────────────────────────────────


class IdentityResult(BaseModel):
    """Cross-image vehicle identity check result."""

    status: Literal["confirmed", "mismatch", "unverifiable"]
    detected_plates: list[str]
    unique_plates: list[str]
    consensus_plate: str | None
    consensus_color: str | None
    identity_reason: str | None


# ── Endpoint response ─────────────────────────────────────────────────────────


class SubmissionSummary(BaseModel):
    """Aggregate counts for the batch of submitted images."""

    total: int
    passed: int
    failed: int
    damage_flagged: int


class ImageResult(BaseModel):
    """Compound result for a single image in the batch response."""

    index: int
    filename: str
    validation: ImageValidationResult
    metadata: MetadataResult


class ValidateImagesResponse(BaseModel):
    """Top-level response for POST /api/v1/validate-images."""

    submission_summary: SubmissionSummary
    identity: IdentityResult
    results: list[ImageResult]


# ── Damage assessment models ──────────────────────────────────────────────────
# Used exclusively by POST /api/v1/assess-condition.
# The validate-images endpoint and all its models above are untouched.


class DamageType(StrEnum):
    """Granular damage category applied to a single vehicle part."""

    dent = "dent"
    scratch = "scratch"
    crack = "crack"
    missing_part = "missing_part"
    discoloration = "discoloration"
    broken_glass = "broken_glass"
    rust = "rust"


class VehiclePart(StrEnum):
    """Exhaustive set of assessable vehicle parts (exactly 25)."""

    front_bumper = "front_bumper"
    front_hood = "front_hood"
    front_windshield = "front_windshield"
    front_left_headlight = "front_left_headlight"
    front_right_headlight = "front_right_headlight"
    left_front_fender = "left_front_fender"
    left_front_door = "left_front_door"
    left_rear_door = "left_rear_door"
    left_rear_fender = "left_rear_fender"
    left_side_mirror = "left_side_mirror"
    right_front_fender = "right_front_fender"
    right_front_door = "right_front_door"
    right_rear_door = "right_rear_door"
    right_rear_fender = "right_rear_fender"
    right_side_mirror = "right_side_mirror"
    rear_bumper = "rear_bumper"
    rear_trunk = "rear_trunk"
    rear_windshield = "rear_windshield"
    left_tail_light = "left_tail_light"
    right_tail_light = "right_tail_light"
    roof_panel = "roof_panel"
    front_left_wheel = "front_left_wheel"
    front_right_wheel = "front_right_wheel"
    rear_left_wheel = "rear_left_wheel"
    rear_right_wheel = "rear_right_wheel"


class PartCondition(BaseModel):
    """Condition snapshot for one vehicle part across all submitted images."""

    part: VehiclePart
    visible_in_image: bool
    damaged: bool
    damage_types: list[DamageType]  # always empty list when damaged=False
    severity: int  # 0=none, 1=minor, 2=moderate, 3=severe
    confidence: float  # 0.0–1.0


class VehicleCondition(BaseModel):
    """Aggregated damage snapshot across all 25 vehicle parts."""

    overall_damage_score: int  # sum of all severity values across all 25 parts
    parts: list[PartCondition]  # exactly 25 entries, one per VehiclePart


class AssessConditionResult(BaseModel):
    """Top-level response for POST /api/v1/assess-condition.

    Extends the validate-images response shape — all existing fields preserved,
    vehicle_condition block added at the top level.  The backend team stores the
    vehicle_condition JSON for later check-in / check-out comparison.
    """

    submission_summary: SubmissionSummary
    identity: IdentityResult
    results: list[ImageResult]
    vehicle_condition: VehicleCondition | None  # None when condition assessment fails
