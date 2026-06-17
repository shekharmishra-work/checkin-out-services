# EV Taxi Image Validation Service

A production-ready FastAPI service for validating and assessing EV taxi images during vehicle check-in and checkout workflows. It uses Google Gemini 2.5 Flash (or OpenRouter) to visually inspect vehicles, combined with strict EXIF metadata extraction to prevent image spoofing.

## Features

- **Gate-Check Validation** (`POST /api/v1/validate-images`): Fast validation of vehicle images. Checks for visual clarity, reads license plates, verifies the vehicle color, and detects obvious damage.
- **Full Damage Inspection** (`POST /api/v1/assess-condition`): A comprehensive dual-call workflow designed for the check-in/checkout lifecycle. In addition to the gate-check, it outputs a strict 25-part structural condition assessment with severity tracking.
- **EXIF Spoof Protection**: Extracts `DateTimeOriginal` from raw image bytes to verify the photos were taken today and are not screenshots or old uploads.
- **Identity Consensus**: Correlates license plates across multiple images to build a consensus identity for the vehicle.
- **Stateless Execution**: The service strictly performs inference and validation without persisting data locally, returning a structured JSON payload for upstream backend systems to store.

## Endpoints

```text
POST /api/v1/validate-images   -> Fast image validation & gate-check
POST /api/v1/assess-condition  -> Full 25-part damage snapshot & gate-check
GET /                          -> {"message": "Image Validation Service Running"}
GET /healthz                   -> {"status": "ok"}
GET /docs                      -> FastAPI OpenAPI UI
```

## Local Development

Built with `uv`.

```bash
# Sync dependencies
uv sync

# Run the local server
uv run uvicorn app.main:app --reload --port 8080 --no-access-log
```

Run tests and linting:

```bash
uv run ruff check .
uv run mypy app tests
uv run pytest
```

### Environment Variables

| Variable | Required | Purpose |
| --- | --- | --- |
| `GOOGLE_API_KEY` | Yes* | Used by Google GenAI SDK for Gemini access. |
| `OPENROUTER_API_KEY` | No | Used for OpenAI-compatible Chat Completions API. |
| `APP_NAME` | No | OpenTelemetry Service name. |
| `ENVIRONMENT` | No | Runtime environment (e.g., `local`, `prd`). |

*\* Note: The app supports OpenRouter natively. Configure the router in `app/services/gemini_service.py` to switch between Google SDK and OpenRouter HTTP requests.*

## Deployment & Cloud Run Assumptions

This service is deployed as a Docker container to Google Cloud Run via GitHub Actions.

- `platform-infra` should manage the Artifact Registry, Cloud Run services, IAM, Secret Manager, and GitHub OIDC bindings.
- OpenTelemetry instrumentation is natively integrated. Enable it by providing `OTEL_EXPORTER_OTLP_ENDPOINT` and `OTEL_EXPORTER_OTLP_HEADERS` in your GCP Secret Manager.

Build the image locally:

```bash
docker build --tag ev-image-validation:test .
```

Run the container locally:

```bash
docker run --rm -p 8080:8080 -e GOOGLE_API_KEY=your_key ev-image-validation:test
```

## Release & Rollback

- **Deployments**: Pushes to `main` auto-deploy to the `nprd` environment. `workflow_dispatch` is required for `prd`.
- **Releases**: Managed by `release-please-action` using Conventional Commits.
- **Rollbacks**: Handled natively by a manual GitHub Action Workflow (`Rollback`), referencing specific Artifact Registry image digests.
