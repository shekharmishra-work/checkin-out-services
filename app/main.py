import io
import json
import logging
import os
import re
from collections.abc import Awaitable, Callable
from typing import Any

import google.generativeai as genai
from fastapi import FastAPI, File, HTTPException, Request, Response, UploadFile, status
from fastapi.responses import PlainTextResponse
from google.api_core import exceptions as api_exceptions
from PIL import Image

from app.core.config import Settings, get_settings
from app.core.logging import configure_logging
from app.core.middleware import (
    get_request_duration_ms,
    get_request_trace_id,
    log_actionable_requests,
    mark_request_failure_logged,
)
from app.core.observability import configure_observability
from app.routers.image_validation import router as image_validation_router

logger = logging.getLogger(__name__)

# ─── Config ───────────────────────────────────────────────────────────────────
MODEL_NAME = "gemini-2.5-flash"
MAX_IMAGE_PX = 1024
JPEG_QUALITY = 85


def get_api_key() -> str:
    """Read API key from environment variables (Cloud Run will inject this)."""
    from pathlib import Path

    from dotenv import load_dotenv

    dotenv_path = Path(__file__).resolve().parent.parent / ".env"
    load_dotenv(dotenv_path=dotenv_path, override=True)
    key = os.environ.get("GOOGLE_API_KEY")
    if not key:
        raise RuntimeError("GOOGLE_API_KEY environment variable is not set")
    return key


def preprocess_image(file_bytes: bytes) -> Image.Image:
    """
    1. Open uploaded bytes as PIL Image
    2. Convert to RGB
    3. Resize so longest side <= MAX_IMAGE_PX
    4. Save as JPEG to BytesIO buffer and return Image
    """
    try:
        img = Image.open(io.BytesIO(file_bytes)).convert("RGB")
        w, h = img.size
        if max(w, h) > MAX_IMAGE_PX:
            ratio = MAX_IMAGE_PX / max(w, h)
            new_w, new_h = int(w * ratio), int(h * ratio)
            img = img.resize((new_w, new_h), Image.Resampling.LANCZOS)

        buffer = io.BytesIO()
        img.save(buffer, format="JPEG", quality=JPEG_QUALITY)
        buffer.seek(0)
        return Image.open(buffer)
    except Exception as e:
        logger.error(f"Image preprocessing failed: {e}")
        raise ValueError(f"Invalid image file: {e}") from e


def build_prompt(num_images: int) -> str:
    return f"""
    You are an expert AI vehicle inspector.
    I am providing {num_images} image(s) of an electric taxi fleet vehicle.

    For EACH image, determine:
    1. Is it a clear photo of a vehicle? (Reject if it's blurry, pitch black, or clearly not a car).
    2. If it is rejected, provide a very short reason.

    You MUST output your response as a strict JSON array of objects.
    Do not include markdown blocks like ```json.

    Example output format:
    [
      {{"index": 1, "valid": true, "reason": null}},
      {{"index": 2, "valid": false, "reason": "Too blurry to identify vehicle"}},
      {{"index": 3, "valid": false, "reason": "Not a vehicle (looks like a wall)"}}
    ]
    """


def create_app(settings: Settings | None = None) -> FastAPI:
    app_settings = settings or get_settings()
    configure_logging(app_settings.log_level)

    app = FastAPI(title=app_settings.app_name, version="0.1.0")

    @app.middleware("http")
    async def request_logging_middleware(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        return await log_actionable_requests(request, call_next, app_settings.slow_request_ms)

    @app.exception_handler(Exception)
    async def unhandled_exception_handler(request: Request, exc: Exception) -> PlainTextResponse:
        mark_request_failure_logged(request)
        logger.error(
            "Unhandled request failure",
            exc_info=(type(exc), exc, exc.__traceback__),
            extra={
                "event": "request_failed",
                "method": request.method,
                "path": request.url.path,
                "status_code": 500,
                "duration_ms": get_request_duration_ms(request),
            },
        )
        response = PlainTextResponse("Internal Server Error", status_code=500)
        response.headers["x-trace-id"] = get_request_trace_id(request)
        return response

    app.include_router(image_validation_router)
    configure_observability(app, app_settings)

    # ─── Routes ───────────────────────────────────────────────────────────────

    @app.get("/")
    async def root() -> dict[str, str]:
        return {"message": "Hello, World!"}

    @app.get("/healthz")
    async def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @app.post("/validate")
    async def validate_images(files: list[UploadFile] = File(...)) -> Any:
        """
        Validates a batch of uploaded EV taxi images using Gemini Vision.
        """
        if not files:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No files uploaded")

        # 1. Preprocess all images
        pil_images = []
        for f in files:
            file_bytes = await f.read()
            try:
                img = preprocess_image(file_bytes)
                pil_images.append(img)
            except ValueError as e:
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)) from e

        # 2. Configure Gemini
        try:
            genai.configure(api_key=get_api_key())
            model = genai.GenerativeModel(MODEL_NAME)
        except RuntimeError as e:
            logger.error("API configuration error: %s", e)
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Server configuration error",
            ) from e

        # 3. Call Gemini
        prompt = build_prompt(len(pil_images))
        contents = pil_images + [prompt]

        try:
            response = model.generate_content(contents)
        except api_exceptions.ResourceExhausted as e:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="API quota exceeded. Please try again later.",
            ) from e
        except api_exceptions.ServiceUnavailable as e:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Vision API is currently unavailable.",
            ) from e
        except Exception as e:
            logger.error(f"Gemini API error: {e}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Validation failed: {str(e)}",
            ) from e

        # 4. Parse JSON Response
        raw_text = response.text
        # Clean markdown fences if present
        cleaned = re.sub(r"^```(?:json)?\n", "", raw_text)
        cleaned = re.sub(r"\n```$", "", cleaned)

        try:
            result = json.loads(cleaned)
            return {"success": True, "results": result}
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse JSON. Raw response: {raw_text}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to parse AI response",
            ) from e

    logger.debug("Application configured")
    return app


app = create_app()
