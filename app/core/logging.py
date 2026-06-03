import json
import logging
import sys
from contextvars import ContextVar, Token
from datetime import UTC, datetime
from typing import Any

from opentelemetry import trace

request_trace_id: ContextVar[str | None] = ContextVar("request_trace_id", default=None)


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": datetime.fromtimestamp(record.created, tz=UTC).isoformat(),
            "severity": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "trace_id": _current_trace_id(),
        }

        if hasattr(record, "event"):
            payload["event"] = record.event

        for key in ("method", "path", "status_code", "duration_ms"):
            if hasattr(record, key):
                payload[key] = getattr(record, key)

        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)

        if record.stack_info:
            payload["stack"] = self.formatStack(record.stack_info)

        return json.dumps(payload, separators=(",", ":"))


def configure_logging(level: str) -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())

    root_logger = logging.getLogger()
    root_logger.handlers.clear()
    root_logger.addHandler(handler)
    root_logger.setLevel(level.upper())

    logging.getLogger("uvicorn.access").handlers.clear()
    logging.getLogger("uvicorn.error").handlers.clear()


def bind_request_trace_id(trace_id: str) -> Token[str | None]:
    return request_trace_id.set(trace_id)


def reset_request_trace_id(token: Token[str | None]) -> None:
    request_trace_id.reset(token)


def get_request_trace_id() -> str:
    return _current_trace_id()


def _current_trace_id() -> str:
    span_context = trace.get_current_span().get_span_context()
    if span_context.is_valid:
        return f"{span_context.trace_id:032x}"
    return request_trace_id.get() or "-"
