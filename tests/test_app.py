from fastapi import APIRouter
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.core.observability import _trace_endpoint
from app.main import create_app


def test_hello_world() -> None:
    client = TestClient(create_app(_test_settings()))

    response = client.get("/")

    assert response.status_code == 200
    assert response.json() == {"message": "Hello, World!"}
    assert len(response.headers["x-trace-id"]) == 32


def test_healthz() -> None:
    client = TestClient(create_app(_test_settings()))

    response = client.get("/healthz")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_app_creation_without_observability_secrets() -> None:
    app = create_app(_test_settings())

    assert app.title == "test-service"


def test_traceparent_header_is_reused_for_response_trace_id() -> None:
    client = TestClient(create_app(_test_settings()))
    trace_id = "0af7651916cd43dd8448eb211c80319c"

    response = client.get("/", headers={"traceparent": f"00-{trace_id}-b7ad6b7169203331-01"})

    assert response.headers["x-trace-id"] == trace_id


def test_unhandled_exceptions_include_request_trace_id() -> None:
    app = create_app(_test_settings())
    router = APIRouter()
    trace_id = "0af7651916cd43dd8448eb211c80319c"

    @router.get("/boom")
    def boom() -> None:
        raise RuntimeError("boom")

    app.include_router(router)
    client = TestClient(app, raise_server_exceptions=False)

    response = client.get("/boom", headers={"traceparent": f"00-{trace_id}-b7ad6b7169203331-01"})

    assert response.status_code == 500
    assert response.text == "Internal Server Error"
    assert response.headers["x-trace-id"] == trace_id


def test_grafana_otlp_base_endpoint_is_normalized_to_trace_endpoint() -> None:
    endpoint = "https://otlp-gateway-prod-ap-south-1.grafana.net/otlp"

    assert _trace_endpoint(endpoint) == f"{endpoint}/v1/traces"


def test_trace_endpoint_is_not_double_appended() -> None:
    endpoint = "https://otlp-gateway-prod-ap-south-1.grafana.net/otlp/v1/traces/"

    assert _trace_endpoint(endpoint) == endpoint.rstrip("/")


def _test_settings() -> Settings:
    return Settings(
        APP_NAME="test-service",
        ENVIRONMENT="test",
        LOG_LEVEL="WARNING",
    )
