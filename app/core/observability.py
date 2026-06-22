from urllib.parse import unquote

from fastapi import FastAPI
from opentelemetry import metrics, trace
from opentelemetry._logs import set_logger_provider
from opentelemetry.exporter.otlp.proto.http._log_exporter import OTLPLogExporter
from opentelemetry.exporter.otlp.proto.http.metric_exporter import OTLPMetricExporter
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.logging import (  # type: ignore[import-not-found]
    LoggingInstrumentor,
)
from opentelemetry.sdk._logs import LoggerProvider
from opentelemetry.sdk._logs.export import BatchLogRecordProcessor
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.semconv.resource import ResourceAttributes

from app.core.config import Settings


def configure_observability(app: FastAPI, settings: Settings) -> None:
    if not settings.observability_enabled:
        return

    assert settings.otlp_endpoint is not None
    assert settings.otlp_headers is not None

    endpoint = settings.otlp_endpoint
    headers = _parse_otlp_headers(settings.otlp_headers)

    resource = Resource.create(
        {
            ResourceAttributes.SERVICE_NAME: settings.app_name,
            ResourceAttributes.SERVICE_VERSION: settings.service_version,
            ResourceAttributes.DEPLOYMENT_ENVIRONMENT: settings.environment,
        }
    )

    _configure_traces(app, resource, endpoint, headers)
    _configure_metrics(resource, endpoint, headers)
    _configure_logs(resource, endpoint, headers)


def _configure_traces(
    app: FastAPI, resource: Resource, endpoint: str, headers: dict[str, str]
) -> None:
    provider = TracerProvider(resource=resource)
    provider.add_span_processor(
        BatchSpanProcessor(
            OTLPSpanExporter(
                endpoint=_otlp_endpoint(endpoint, "traces"),
                headers=headers,
            )
        )
    )
    trace.set_tracer_provider(provider)
    FastAPIInstrumentor.instrument_app(app, tracer_provider=provider)


def _configure_metrics(resource: Resource, endpoint: str, headers: dict[str, str]) -> None:
    reader = PeriodicExportingMetricReader(
        OTLPMetricExporter(
            endpoint=_otlp_endpoint(endpoint, "metrics"),
            headers=headers,
        ),
        export_interval_millis=30_000,
    )
    meter_provider = MeterProvider(resource=resource, metric_readers=[reader])
    metrics.set_meter_provider(meter_provider)


def _configure_logs(resource: Resource, endpoint: str, headers: dict[str, str]) -> None:
    logger_provider = LoggerProvider(resource=resource)
    logger_provider.add_log_record_processor(
        BatchLogRecordProcessor(
            OTLPLogExporter(
                endpoint=_otlp_endpoint(endpoint, "logs"),
                headers=headers,
            )
        )
    )
    set_logger_provider(logger_provider)
    LoggingInstrumentor().instrument(set_logging_format=False)


def _parse_otlp_headers(raw_headers: str) -> dict[str, str]:
    headers: dict[str, str] = {}
    for item in raw_headers.split(","):
        key, separator, value = item.partition("=")
        if separator and key.strip() and value.strip():
            headers[key.strip()] = unquote(value.strip())
    return headers


def _otlp_endpoint(endpoint: str, signal: str) -> str:
    normalized = endpoint.rstrip("/")
    suffix = f"/v1/{signal}"
    if normalized.endswith(suffix):
        return normalized
    return f"{normalized}{suffix}"


def _trace_endpoint(endpoint: str) -> str:
    return _otlp_endpoint(endpoint, "traces")
