from functools import lru_cache

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = Field(default="fastapi-cloud-run-template", alias="APP_NAME")
    environment: str = Field(default="local", alias="ENVIRONMENT")
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")
    service_version: str = Field(default="0.1.0", alias="SERVICE_VERSION")
    slow_request_ms: int = Field(default=1000, alias="SLOW_REQUEST_MS")

    otel_exporter_otlp_endpoint: str | None = Field(
        default=None, alias="OTEL_EXPORTER_OTLP_ENDPOINT"
    )
    otel_exporter_otlp_headers: SecretStr | None = Field(
        default=None, alias="OTEL_EXPORTER_OTLP_HEADERS"
    )

    @property
    def observability_enabled(self) -> bool:
        return bool(self.otlp_endpoint and self.otlp_headers)

    @property
    def otlp_endpoint(self) -> str | None:
        return self.otel_exporter_otlp_endpoint

    @property
    def otlp_headers(self) -> str | None:
        if self.otel_exporter_otlp_headers:
            return self.otel_exporter_otlp_headers.get_secret_value()
        return None


@lru_cache
def get_settings() -> Settings:
    return Settings()
