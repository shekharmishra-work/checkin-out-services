import logging
from collections.abc import Awaitable, Callable

from fastapi import FastAPI, Request, Response
from fastapi.responses import PlainTextResponse

from app.api.routes import router
from app.core.config import Settings, get_settings
from app.core.logging import configure_logging
from app.core.middleware import (
    get_request_duration_ms,
    get_request_trace_id,
    log_actionable_requests,
    mark_request_failure_logged,
)
from app.core.observability import configure_observability

logger = logging.getLogger(__name__)


def create_app(settings: Settings | None = None) -> FastAPI:
    app_settings = settings or get_settings()
    configure_logging(app_settings.log_level)

    app = FastAPI(title=app_settings.app_name)

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

    app.include_router(router)
    configure_observability(app, app_settings)

    logger.debug("Application configured")
    return app


app = create_app()
