from fastapi import FastAPI
from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
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

    resource = Resource.create(
        {
            ResourceAttributes.SERVICE_NAME: settings.app_name,
            ResourceAttributes.SERVICE_VERSION: settings.service_version,
            ResourceAttributes.DEPLOYMENT_ENVIRONMENT: settings.environment,
        }
    )
    provider = TracerProvider(resource=resource)
    provider.add_span_processor(
        BatchSpanProcessor(
            OTLPSpanExporter(
                endpoint=_trace_endpoint(settings.otlp_endpoint),
                headers=_parse_otlp_headers(settings.otlp_headers),
            )
        )
    )
    trace.set_tracer_provider(provider)
    FastAPIInstrumentor.instrument_app(app, tracer_provider=provider)


def _parse_otlp_headers(raw_headers: str) -> dict[str, str]:
    headers: dict[str, str] = {}
    for item in raw_headers.split(","):
        key, separator, value = item.partition("=")
        if separator and key.strip() and value.strip():
            headers[key.strip()] = value.strip()
    return headers


def _trace_endpoint(endpoint: str) -> str:
    normalized = endpoint.rstrip("/")
    if normalized.endswith("/v1/traces"):
        return normalized
    return f"{normalized}/v1/traces"
