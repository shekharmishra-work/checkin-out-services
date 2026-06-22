"""Gemini Vision service for batch EV-taxi image validation.

Sends all images in a *single* model.generate_content() call, parses the
JSON array response, and returns a list of ImageValidationResult objects.

Key design decisions
--------------------
* A module-level threading.Semaphore caps concurrent Gemini calls to 5.
* Failed calls are retried up to 3 times with exponential back-off on
  ResourceExhausted and ServiceUnavailable errors.
* Markdown code-fences are stripped before JSON parsing so the model
  can "accidentally" wrap its output without breaking the service.
"""

from __future__ import annotations

import io
import json
import logging
import os
import re
import threading
import time
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.models.validation_models import AssessConditionResult, VehicleCondition

import google.generativeai as genai
from google.api_core import exceptions as api_exceptions
from PIL import Image

from app.models.validation_models import ImageValidationResult
from app.services.identity_service import check_vehicle_identity
from app.services.metadata_service import extract_metadata_status

logger = logging.getLogger(__name__)

# ── Module-level constants ────────────────────────────────────────────────────

MODEL_NAME = "gemini-2.5-flash"
MAX_IMAGE_PX = 1024
JPEG_QUALITY = 85
MAX_RETRIES = 3
BASE_BACKOFF_S = 1.0

# Cap concurrent Gemini calls across all threads
_semaphore = threading.Semaphore(5)

# Retryable API error types
_RETRYABLE = (api_exceptions.ResourceExhausted, api_exceptions.ServiceUnavailable)


# ── Internal helpers ──────────────────────────────────────────────────────────


def _get_api_key() -> str:
    from pathlib import Path

    from dotenv import load_dotenv

    dotenv_path = Path(__file__).resolve().parent.parent.parent / ".env"
    load_dotenv(dotenv_path=dotenv_path, override=True)
    key = os.environ.get("GOOGLE_API_KEY")
    if not key:
        raise RuntimeError("GOOGLE_API_KEY environment variable is not set")
    return key


def _preprocess(image_bytes: bytes) -> Image.Image:
    """Resize to MAX_IMAGE_PX longest side, convert to RGB JPEG."""
    img = Image.open(io.BytesIO(image_bytes)).convert("RGB")
    w, h = img.size
    if max(w, h) > MAX_IMAGE_PX:
        ratio = MAX_IMAGE_PX / max(w, h)
        img = img.resize((int(w * ratio), int(h * ratio)), Image.Resampling.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=JPEG_QUALITY)
    buf.seek(0)
    return Image.open(buf)


def _build_prompt(num_images: int) -> str:
    return f"""You are an expert AI vehicle inspector for an EV taxi fleet.
I am providing {num_images} image(s). Analyse EACH image and return a JSON array.

For EACH image (1-indexed), determine:
1. Is it a clear photo of a vehicle? (Reject if blurry, pitch-black, or clearly not a car.)
2. Is the number plate visible? If so, extract it (uppercase, no spaces).
3. What is the dominant exterior colour of the vehicle? (lowercase, e.g. "white", "silver")
4. Is there any visible damage (dents, scratches, broken parts)?

Rules:
- Damage is a SOFT flag only — it NEVER makes valid=false.
- Return ONLY a raw JSON array. No markdown, no backticks, no explanations.
- The array must have exactly {num_images} object(s) in order.

Schema per object:
{{
  "index": <1-based int>,
  "valid": <bool>,
  "reason": <string or null>,
  "plate": <"UPPERCASE_PLATE" or null>,
  "color": <"lowercase colour" or null>,
  "damage_detected": <bool>,
  "damage_details": <string or null>
}}"""


def _strip_fences(text: str) -> str:
    """Remove markdown code-fences if the model includes them."""
    cleaned = re.sub(r"^```(?:json)?\s*\n?", "", text.strip(), flags=re.IGNORECASE)
    cleaned = re.sub(r"\n?```\s*$", "", cleaned.strip())
    return cleaned.strip()


def _call_with_retry(model: genai.GenerativeModel, contents: list[object]) -> str:  # type: ignore[name-defined]
    """Call model.generate_content with exponential back-off retries."""
    last_exc: Exception | None = None
    for attempt in range(MAX_RETRIES):
        try:
            with _semaphore:
                response = model.generate_content(contents)
            return str(response.text)
        except _RETRYABLE as exc:
            last_exc = exc
            wait = BASE_BACKOFF_S * (2**attempt)
            logger.warning(
                "Gemini call attempt %d/%d failed (%s). Retrying in %.1fs.",
                attempt + 1,
                MAX_RETRIES,
                type(exc).__name__,
                wait,
            )
            time.sleep(wait)
        except Exception:
            raise

    raise RuntimeError(f"Gemini call failed after {MAX_RETRIES} attempts") from last_exc


# ── Public API ────────────────────────────────────────────────────────────────


def _validate_images_google(image_bytes_list: list[bytes]) -> list[ImageValidationResult]:
    """Validate images using Google Generative AI SDK."""
    genai.configure(api_key=_get_api_key())
    model = genai.GenerativeModel(MODEL_NAME)

    pil_images = [_preprocess(b) for b in image_bytes_list]
    prompt = _build_prompt(len(pil_images))
    contents: list[object] = [*pil_images, prompt]

    raw_text = _call_with_retry(model, contents)
    cleaned = _strip_fences(raw_text)

    try:
        parsed: list[dict[str, object]] = json.loads(cleaned)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Gemini returned non-JSON response. Raw text: {raw_text!r}") from exc

    results: list[ImageValidationResult] = []
    for item in parsed:
        results.append(ImageValidationResult.model_validate(item))

    return results


def _validate_images_openrouter(
    image_bytes_list: list[bytes], api_key: str
) -> list[ImageValidationResult]:
    """Validate images using OpenRouter's OpenAI-compatible Chat Completions API."""
    import base64

    import httpx

    pil_images = [_preprocess(b) for b in image_bytes_list]
    prompt = _build_prompt(len(pil_images))

    content_list: list[dict[str, object]] = [{"type": "text", "text": prompt}]
    for img in pil_images:
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=JPEG_QUALITY)
        img_b64 = base64.b64encode(buf.getvalue()).decode("utf-8")
        content_list.append(
            {
                "type": "image_url",
                "image_url": {"url": f"data:image/jpeg;base64,{img_b64}"},
            }
        )

    payload = {
        "model": "google/gemini-2.5-flash",
        "messages": [
            {
                "role": "user",
                "content": content_list,
            }
        ],
    }

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "HTTP-Referer": "http://localhost:8080",
        "X-Title": "EV Taxi Validator",
    }

    raw_text = ""
    last_exc: Exception | None = None

    for attempt in range(MAX_RETRIES):
        try:
            with _semaphore:
                with httpx.Client(timeout=60.0) as client:
                    response = client.post(
                        "https://openrouter.ai/api/v1/chat/completions",
                        json=payload,
                        headers=headers,
                    )
                    response.raise_for_status()
                    res_json = response.json()
                    raw_text = str(res_json["choices"][0]["message"]["content"])
                    break
        except httpx.HTTPStatusError as exc:
            last_exc = exc
            status_code = exc.response.status_code
            if status_code in (429, 502, 503, 504):
                wait = BASE_BACKOFF_S * (2**attempt)
                logger.warning(
                    "OpenRouter call attempt %d/%d failed with status %d. Retrying in %.1fs.",
                    attempt + 1,
                    MAX_RETRIES,
                    status_code,
                    wait,
                )
                time.sleep(wait)
            else:
                raise
        except httpx.RequestError as exc:
            last_exc = exc
            wait = BASE_BACKOFF_S * (2**attempt)
            logger.warning(
                "OpenRouter call attempt %d/%d failed (request error). Retrying in %.1fs.",
                attempt + 1,
                MAX_RETRIES,
                wait,
            )
            time.sleep(wait)
    else:
        raise RuntimeError(f"OpenRouter call failed after {MAX_RETRIES} attempts") from last_exc

    cleaned = _strip_fences(raw_text)
    try:
        parsed: list[dict[str, object]] = json.loads(cleaned)
    except json.JSONDecodeError as exc:
        raise ValueError(f"OpenRouter returned non-JSON response. Raw text: {raw_text!r}") from exc

    results: list[ImageValidationResult] = []
    for item in parsed:
        results.append(ImageValidationResult.model_validate(item))

    return results


def validate_images(image_bytes_list: list[bytes]) -> list[ImageValidationResult]:
    """Validate a batch of images with a single model call.

    Args:
        image_bytes_list: Raw bytes for each uploaded image.

    Returns:
        List of ImageValidationResult objects (one per image, in order).

    Raises:
        ValueError: If the model response cannot be parsed as JSON.
        RuntimeError: If all retries are exhausted or configuration is missing.
    """
    from pathlib import Path

    from dotenv import load_dotenv

    dotenv_path = Path(__file__).resolve().parent.parent.parent / ".env"
    load_dotenv(dotenv_path=dotenv_path, override=True)

    openrouter_key = os.environ.get("OPENROUTER_API_KEY")
    if openrouter_key:
        return _validate_images_openrouter(image_bytes_list, openrouter_key)

    return _validate_images_google(image_bytes_list)


# ── Condition assessment (new — does NOT modify validate_images) ──────────────


def _build_condition_prompt(n: int) -> str:
    return f"""You are a vehicle damage inspection AI. You are given {n} images of this vehicle,
numbered Image 1 through Image {n} in the order provided. The images may show
different angles of the same vehicle — use all of them together to assess every part.

Assess each of the following 25 parts. You MUST return an entry for every single
part — even if undamaged, even if not visible in any image.

Parts to assess (use these exact names):
front_bumper, front_hood, front_windshield, front_left_headlight, front_right_headlight,
left_front_fender, left_front_door, left_rear_door, left_rear_fender, left_side_mirror,
right_front_fender, right_front_door, right_rear_door, right_rear_fender, right_side_mirror,
rear_bumper, rear_trunk, rear_windshield, left_tail_light, right_tail_light,
roof_panel, front_left_wheel, front_right_wheel, rear_left_wheel, rear_right_wheel

For each part return exactly this structure:
{{
  "part": "<exact name from list above>",
  "visible_in_image": true or false,
  "source_image_index": <integer 1 to {n}> or null,
  "damaged": true or false,
  "damage_types": [] or subset of ["dent","scratch","crack","missing_part",
                                    "discoloration","broken_glass","rust"],
  "severity": 0 (none) / 1 (minor) / 2 (moderate) / 3 (severe),
  "confidence": 0.0 to 1.0
}}

Rules:
- If a part is NOT visible in ANY image: visible_in_image=false,
  source_image_index=null, damaged=false, severity=0, confidence=0, damage_types=[]
- If a part IS visible in one or more images: visible_in_image=true, and
  source_image_index MUST be the number (1 to {n}) of the single image where
  this part is most clearly visible — pick exactly one, even if visible in
  several images
- If visible but undamaged: damaged=false, severity=0, damage_types=[],
  but source_image_index is still required
- severity MUST be 0 when damaged is false
- damage_types MUST be empty list when damaged is false
- confidence reflects how clearly the part is visible in the chosen source image
- source_image_index must never be a number outside the range 1 to {n}
- source_image_index must never be null when visible_in_image is true, and
  must always be null when visible_in_image is false

Return ONLY a raw JSON array of exactly 25 objects.
No markdown, no backticks, no explanation. Nothing else."""


def assess_vehicle_condition(image_bytes_list: list[bytes]) -> VehicleCondition:  # noqa: F821
    """Assess the structural condition of a vehicle across all provided images.

    Makes a SINGLE Gemini API call asking the model to evaluate all 25 standard
    vehicle parts holistically using every image in the batch.

    This is the second Gemini call made by validate_and_assess().
    It is deliberately kept separate from validate_images() because the two
    prompts serve fundamentally different purposes:
      - validate_images  → per-image gate check (is this a valid photo?)
      - assess_vehicle_condition → cross-image damage snapshot (part-by-part)
    Merging them would make the prompt too complex and the output unreliable.

    Args:
        image_bytes_list: Raw bytes for each uploaded image.

    Returns:
        VehicleCondition with overall_damage_score and exactly 25 PartCondition
        entries (one per VehiclePart enum member).

    Raises:
        ValueError: If Gemini returns != 25 parts or an unknown part name.
        RuntimeError: If all retries are exhausted or configuration is missing.
    """
    # Import here to avoid circular dependency at module load time
    from pathlib import Path

    from dotenv import load_dotenv

    from app.models.validation_models import (
        PartCondition,
        VehicleCondition,
        VehiclePart,
    )

    dotenv_path = Path(__file__).resolve().parent.parent.parent / ".env"
    load_dotenv(dotenv_path=dotenv_path, override=True)

    genai.configure(api_key=_get_api_key())
    model = genai.GenerativeModel(MODEL_NAME)

    pil_images = [_preprocess(b) for b in image_bytes_list]
    prompt = _build_condition_prompt(len(image_bytes_list))
    contents: list[object] = [*pil_images, prompt]

    raw_text = _call_with_retry(model, contents)
    cleaned = _strip_fences(raw_text)

    try:
        raw_parts: list[dict[str, object]] = json.loads(cleaned)
    except json.JSONDecodeError as exc:
        raise ValueError(
            f"assess_vehicle_condition: Gemini returned non-JSON. Raw: {raw_text!r}"
        ) from exc

    if len(raw_parts) != 25:
        raise ValueError(f"Gemini returned {len(raw_parts)} parts, expected 25")

    # Validate all part names against the enum before building models
    valid_part_names = {member.value for member in VehiclePart}
    n_images = len(image_bytes_list)
    for item in raw_parts:
        part_name = item.get("part")
        if part_name not in valid_part_names:
            raise ValueError(f"assess_vehicle_condition: unknown part name {part_name!r}")

        visible = item.get("visible_in_image")
        source_index = item.get("source_image_index")

        if visible is True:
            if source_index is None:
                raise ValueError(
                    f"Part {part_name} marked visible but source_image_index is missing"
                )
            if not isinstance(source_index, int) or not (1 <= source_index <= n_images):
                raise ValueError(
                    f"Part {part_name} has invalid index {source_index}, expected 1-{n_images}"
                )
        elif visible is False:
            if source_index is not None:
                logger.warning(
                    "Part %s marked not visible but has source_image_index %s. Coercing to None.",
                    part_name,
                    source_index,
                )
                item["source_image_index"] = None

    parts: list[PartCondition] = [PartCondition.model_validate(item) for item in raw_parts]
    overall_damage_score = sum(p.severity for p in parts)

    return VehicleCondition(overall_damage_score=overall_damage_score, parts=parts)


def validate_and_assess(
    image_bytes_list: list[bytes],
    filenames: list[str],
) -> AssessConditionResult:  # noqa: F821
    """Run both assessments and merge into a single AssessConditionResult.

    Makes EXACTLY TWO Gemini API calls:
      Call 1 — validate_images()           → per-image gate check
      Call 2 — assess_vehicle_condition()  → cross-image damage snapshot

    The two calls are deliberately kept separate (see assess_vehicle_condition
    docstring for rationale).

    If assess_vehicle_condition fails for any reason, the overall request does
    NOT fail — vehicle_condition is set to None and the error is logged.  The
    gate-check result (submission_summary, identity, results) is still returned
    and is fully usable on its own.

    Args:
        image_bytes_list: Raw bytes for each uploaded image.
        filenames: Corresponding filenames (same length as image_bytes_list).

    Returns:
        AssessConditionResult combining both assessments.
    """
    from app.models.validation_models import (
        AssessConditionResult,
        ImageResult,
        SubmissionSummary,
    )

    # ── Call 1: per-image gate check (identical logic to /api/v1/validate-images) ──
    validation_results = validate_images(image_bytes_list)
    metadata_results = [extract_metadata_status(b) for b in image_bytes_list]
    identity = check_vehicle_identity(validation_results)

    image_results: list[ImageResult] = [
        ImageResult(
            index=i,
            filename=fname,
            validation=val,
            metadata=meta,
        )
        for i, (val, meta, fname) in enumerate(
            zip(validation_results, metadata_results, filenames, strict=False), start=1
        )
    ]

    total = len(image_results)
    passed = sum(1 for r in validation_results if r.valid)
    summary = SubmissionSummary(
        total=total,
        passed=passed,
        failed=total - passed,
        damage_flagged=sum(1 for r in validation_results if r.damage_detected),
    )

    # ── Call 2: cross-image damage snapshot ──────────────────────────────────
    vehicle_condition: VehicleCondition | None = None
    try:
        vehicle_condition = assess_vehicle_condition(image_bytes_list)
    except Exception as exc:  # pragma: no cover — defensive, logged and swallowed
        logger.error(
            "assess_vehicle_condition failed — returning None for vehicle_condition: %s",
            exc,
            exc_info=True,
        )

    return AssessConditionResult(
        submission_summary=summary,
        identity=identity,
        results=image_results,
        vehicle_condition=vehicle_condition,
    )
