import logging
import time
from collections.abc import Awaitable, Callable
from uuid import uuid4

from fastapi import Request, Response

from app.core.logging import bind_request_trace_id, reset_request_trace_id

logger = logging.getLogger("app.request")


async def log_actionable_requests(
    request: Request,
    call_next: Callable[[Request], Awaitable[Response]],
    slow_request_ms: int,
) -> Response:
    trace_id = _trace_id_from_request(request)
    request.state.trace_id = trace_id
    request.state.request_started = time.perf_counter()
    token = bind_request_trace_id(trace_id)

    try:
        response = await call_next(request)
        duration_ms = get_request_duration_ms(request)
        response.headers.setdefault("x-trace-id", get_request_trace_id(request))

        if response.status_code >= 500 and not request_failure_logged(request):
            logger.error(
                "Request failed",
                extra={
                    "event": "request_failed",
                    "method": request.method,
                    "path": request.url.path,
                    "status_code": response.status_code,
                    "duration_ms": duration_ms,
                },
            )
        elif duration_ms >= slow_request_ms:
            logger.warning(
                "Slow request",
                extra={
                    "event": "request_slow",
                    "method": request.method,
                    "path": request.url.path,
                    "status_code": response.status_code,
                    "duration_ms": duration_ms,
                },
            )

        return response
    finally:
        reset_request_trace_id(token)


def get_request_trace_id(request: Request) -> str:
    trace_id = getattr(request.state, "trace_id", None)
    if isinstance(trace_id, str) and trace_id:
        return trace_id
    return _trace_id_from_request(request)


def get_request_duration_ms(request: Request) -> int:
    started = getattr(request.state, "request_started", None)
    if isinstance(started, float):
        return _duration_ms(started)
    return 0


def mark_request_failure_logged(request: Request) -> None:
    request.state.server_error_logged = True


def request_failure_logged(request: Request) -> bool:
    return bool(getattr(request.state, "server_error_logged", False))


def _trace_id_from_request(request: Request) -> str:
    traceparent = request.headers.get("traceparent")
    if traceparent:
        parts = traceparent.split("-")
        if len(parts) >= 2 and len(parts[1]) == 32:
            return parts[1]
    return uuid4().hex


def _duration_ms(started: float) -> int:
    return round((time.perf_counter() - started) * 1000)
