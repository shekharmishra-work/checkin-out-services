"""Vehicle identity cross-check service.

Analyses plate and colour data from a list of ImageValidationResult objects
to determine whether all images show the same vehicle.
"""

from __future__ import annotations

import logging
from collections import Counter

from app.models.validation_models import IdentityResult, ImageValidationResult

logger = logging.getLogger(__name__)


def check_vehicle_identity(results: list[ImageValidationResult]) -> IdentityResult:
    """Cross-check plates and colours across all image validation results.

    Args:
        results: List of per-image validation results produced by the Gemini service.

    Returns:
        IdentityResult describing whether a consistent vehicle identity was found.
    """
    detected_plates: list[str] = [r.plate for r in results if r.plate is not None]
    unique_plates: list[str] = list(dict.fromkeys(detected_plates))  # preserve order, deduplicate

    # Consensus colour: most common non-null colour across all images
    colors: list[str] = [r.color for r in results if r.color is not None]
    consensus_color: str | None = Counter(colors).most_common(1)[0][0] if colors else None

    # Consensus plate: most common plate (used only when status=="confirmed")
    consensus_plate: str | None = (
        Counter(detected_plates).most_common(1)[0][0] if detected_plates else None
    )

    if not detected_plates:
        return IdentityResult(
            status="unverifiable",
            detected_plates=[],
            unique_plates=[],
            consensus_plate=None,
            consensus_color=consensus_color,
            identity_reason=(
                "No number plate visible in any image — manual verification required"
            ),
        )

    if len(unique_plates) == 1:
        return IdentityResult(
            status="confirmed",
            detected_plates=detected_plates,
            unique_plates=unique_plates,
            consensus_plate=consensus_plate,
            consensus_color=consensus_color,
            identity_reason=None,
        )

    # Multiple distinct plates detected
    return IdentityResult(
        status="mismatch",
        detected_plates=detected_plates,
        unique_plates=unique_plates,
        consensus_plate=None,
        consensus_color=consensus_color,
        identity_reason=(
            "Plates detected do not all match — possible mixed vehicle images"
        ),
    )
