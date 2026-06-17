"""Tests for app.services.identity_service.check_vehicle_identity.

Covers three plate scenarios:
  1. All detected plates are identical → confirmed
  2. Plates differ across images → mismatch
  3. No plates visible in any image → unverifiable
"""

from __future__ import annotations

from app.models.validation_models import ImageValidationResult
from app.services.identity_service import check_vehicle_identity


def _make_result(
    index: int,
    plate: str | None,
    color: str | None = "white",
    valid: bool = True,
) -> ImageValidationResult:
    """Helper: build a minimal ImageValidationResult for testing."""
    return ImageValidationResult(
        index=index,
        valid=valid,
        reason=None,
        plate=plate,
        color=color,
        damage_detected=False,
        damage_details=None,
    )


# ── Scenario 1: All plates match ──────────────────────────────────────────────


def test_matching_plates_returns_confirmed() -> None:
    results = [
        _make_result(1, "MH12AB1234"),
        _make_result(2, "MH12AB1234"),
        _make_result(3, "MH12AB1234"),
    ]

    identity = check_vehicle_identity(results)

    assert identity.status == "confirmed"
    assert identity.unique_plates == ["MH12AB1234"]
    assert identity.consensus_plate == "MH12AB1234"
    assert identity.identity_reason is None


def test_confirmed_picks_correct_consensus_color() -> None:
    results = [
        _make_result(1, "MH12AB1234", color="white"),
        _make_result(2, "MH12AB1234", color="white"),
        _make_result(3, "MH12AB1234", color="silver"),
    ]

    identity = check_vehicle_identity(results)

    assert identity.status == "confirmed"
    assert identity.consensus_color == "white"


# ── Scenario 2: Plates differ ─────────────────────────────────────────────────


def test_mismatched_plates_returns_mismatch() -> None:
    results = [
        _make_result(1, "MH12AB1234"),
        _make_result(2, "DL01XY9999"),
        _make_result(3, "MH12AB1234"),
    ]

    identity = check_vehicle_identity(results)

    assert identity.status == "mismatch"
    assert set(identity.unique_plates) == {"MH12AB1234", "DL01XY9999"}
    assert identity.consensus_plate is None
    assert "do not all match" in (identity.identity_reason or "")


def test_mismatch_detected_plates_includes_all_occurrences() -> None:
    """detected_plates should include duplicates (raw list), not just uniques."""
    results = [
        _make_result(1, "AAA000"),
        _make_result(2, "BBB111"),
        _make_result(3, "AAA000"),
    ]

    identity = check_vehicle_identity(results)

    assert identity.detected_plates.count("AAA000") == 2
    assert identity.detected_plates.count("BBB111") == 1


# ── Scenario 3: No plates visible ────────────────────────────────────────────


def test_no_plates_returns_unverifiable() -> None:
    results = [
        _make_result(1, None),
        _make_result(2, None),
    ]

    identity = check_vehicle_identity(results)

    assert identity.status == "unverifiable"
    assert identity.detected_plates == []
    assert identity.unique_plates == []
    assert identity.consensus_plate is None
    assert "manual verification" in (identity.identity_reason or "")


def test_unverifiable_still_reports_consensus_color() -> None:
    """Even when no plate is found, the dominant colour should be returned."""
    results = [
        _make_result(1, None, color="black"),
        _make_result(2, None, color="black"),
        _make_result(3, None, color="red"),
    ]

    identity = check_vehicle_identity(results)

    assert identity.status == "unverifiable"
    assert identity.consensus_color == "black"


def test_empty_results_list_returns_unverifiable() -> None:
    identity = check_vehicle_identity([])

    assert identity.status == "unverifiable"
    assert identity.consensus_color is None
