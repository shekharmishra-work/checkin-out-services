# FastAPI Cloud Run Template

API-only FastAPI template for GCP Cloud Run. It includes a hello-world route, health check, containerization, GitHub Actions deployment, rollback support, release tagging, quiet structured logging, and Grafana Cloud OpenTelemetry export.

Infrastructure is intentionally outside this repo. Create the Cloud Run service, Artifact Registry repository, IAM, Secret Manager secrets, and GitHub OIDC bindings from `platform-infra`, then point this template repo at those resources with GitHub repository variables.

## App

Routes:

```text
GET /        -> {"message": "Hello, World!"}
GET /healthz -> {"status": "ok"}
GET /docs    -> FastAPI OpenAPI UI
```

Runtime settings:

| Variable | Default | Purpose |
| --- | --- | --- |
| `APP_NAME` | `fastapi-cloud-run-template` | Service name used by FastAPI and OpenTelemetry. |
| `ENVIRONMENT` | `local` | Runtime environment such as `nprd` or `prd`. |
| `LOG_LEVEL` | `INFO` | Python logging level. |
| `SERVICE_VERSION` | `0.1.0` | Version attached to OpenTelemetry resource attributes. |
| `SLOW_REQUEST_MS` | `1000` | Logs a warning only when a request exceeds this duration. |
| `OTEL_EXPORTER_OTLP_ENDPOINT` | unset | Grafana Cloud OTLP HTTP endpoint from the OpenTelemetry connection tile. |
| `OTEL_EXPORTER_OTLP_HEADERS` | unset | Grafana Cloud OTLP auth headers from Secret Manager. |

OpenTelemetry instrumentation is enabled only when endpoint and auth headers are present. Logs are written as JSON to stdout for Cloud Run ingestion.

Logging is intentionally not request-verbose. The service:

- suppresses Uvicorn access logs
- logs unhandled failures and HTTP 5xx responses at `ERROR`
- logs slow requests at `WARNING`
- attaches `trace_id` to every log record
- returns `x-trace-id` on every response
- reuses inbound W3C `traceparent` trace IDs when present

## Local Development

```bash
uv sync
uv run uvicorn app.main:app --reload --port 8080 --no-access-log
```

Run checks:

```bash
uv run ruff check .
uv run mypy app tests
uv run pytest
```

Build the image:

```bash
docker build --tag fastapi-cloud-run-template:test .
```

Run the container:

```bash
docker run --rm -p 8080:8080 fastapi-cloud-run-template:test
```

## Cloud Run Assumptions

`platform-infra` should create and manage:

- Artifact Registry repository per environment or shared by convention.
- Cloud Run service per environment.
- GitHub Workload Identity Federation provider and deploy service account.
- Secret Manager secrets for Grafana Cloud values.
- Cloud Run secret injection into `OTEL_EXPORTER_OTLP_ENDPOINT` and `OTEL_EXPORTER_OTLP_HEADERS`.
- GitHub environments named `nprd` and `prd`, with required reviewers on `prd`.

Recommended Cloud Run scaling:

| Environment | Min instances | Max instances |
| --- | ---: | ---: |
| `nprd` | 0 | 1 |
| `prd` | 1 | 2 |

This repository deploys the image to an existing service. It does not mutate Cloud Run scaling settings; keep those in OpenTofu.

## GCP Setup From Scratch

Use OpenTofu in `platform-infra` for these resources. Keep resource names environment-specific unless a resource is deliberately shared.

1. Create or choose GCP projects for `nprd` and `prd`.
1. Enable required APIs:
   - Cloud Run
   - Artifact Registry
   - IAM Credentials
   - Security Token Service
   - Secret Manager
   - Cloud Logging and Cloud Monitoring
1. Create an Artifact Registry Docker repository in each project or environment.
1. Create a Cloud Run runtime service account per app environment, for example:
   - `fastapi-template-runtime-nprd`
   - `fastapi-template-runtime-prd`
1. Create a GitHub deploy service account per environment.
1. Grant the deploy service account only what deployment needs:
   - Artifact Registry writer on the target repository
   - Cloud Run developer on the target service/project
   - service account user on the Cloud Run runtime service account
1. Configure Workload Identity Federation for GitHub Actions.
   - Trust only the target GitHub organization/repository.
   - Prefer environment-specific conditions for `nprd` and `prd`.
   - Bind the GitHub principal set to the deploy service account.
1. Create the Cloud Run service from a placeholder image or after the first CI image exists.
   - Set ingress, invoker policy, CPU/memory, timeout, concurrency, and scaling in OpenTofu.
   - Use min/max instances from the table above.
   - Configure the container port as `8080`; Cloud Run injects `PORT`.
1. Create Secret Manager secrets and grant access as described below.
1. Add GitHub repository variables listed in the next section.
1. Create GitHub environments named `nprd` and `prd`.
   - Add required reviewers on `prd`.
   - Restrict deployment branches to `main` for both.

## Secret Model

GCP Secret Manager does not have a separate "secret store" resource like some clouds. Model two stores using either separate GCP projects or strict naming prefixes plus per-secret IAM. For this template, prefer prefixes first because it is simpler and still gives per-secret access control.

Recommended prefixes:

```text
platform/<env>/<name>
apps/<app>/<env>/<name>
```

Examples:

```text
platform/prd/grafana-otlp-endpoint
platform/prd/grafana-otlp-headers
apps/fastapi-template/prd/external-api-key
```

Access pattern:

- Terraform creates all secret resources and IAM bindings.
- Platform/shared secrets are owned by the platform admin group or CI identity.
- App-specific secrets are writable only by the email/principal you pass to Terraform plus the platform admin group.
- Cloud Run runtime service accounts get `roles/secretmanager.secretAccessor` only on the exact secrets they need.
- Humans who only rotate app secret values get `roles/secretmanager.secretVersionAdder`; add `roles/secretmanager.secretAccessor` only if they must read values back.
- Avoid project-wide Secret Manager Admin for app developers.

For Grafana Cloud, the app usually only needs platform/shared secrets:

```text
OTEL_EXPORTER_OTLP_ENDPOINT <- platform/<env>/grafana-otlp-endpoint
OTEL_EXPORTER_OTLP_HEADERS  <- platform/<env>/grafana-otlp-headers
```

For Python, Grafana documents that `Basic ` in the OTLP header value may need to be encoded as `Basic%20`. Store the exact value from the Grafana OpenTelemetry connection tile.

## Grafana Cloud Setup From Scratch

1. Create or open your Grafana Cloud stack.
1. In Grafana Cloud, open the OpenTelemetry connection tile.
1. Generate the OTLP endpoint and auth header values.
1. Store those values in Secret Manager:
   - `platform/<env>/grafana-otlp-endpoint`
   - `platform/<env>/grafana-otlp-headers`
1. Inject the values into Cloud Run as:
   - `OTEL_EXPORTER_OTLP_ENDPOINT`
   - `OTEL_EXPORTER_OTLP_HEADERS`
1. Keep these OpenTelemetry resource attributes consistent:
   - `service.name`: `APP_NAME`
   - `service.version`: `SERVICE_VERSION`
   - `deployment.environment`: `ENVIRONMENT`
1. For production-grade telemetry, route through Grafana Alloy or an OpenTelemetry Collector when possible. Direct OTLP export is fine for a template and lower environments, but a collector is better for retry buffering, enrichment, sampling, redaction, and multi-destination routing.
1. In Grafana Application Observability, set `deployment.environment` as the environment attribute if it is not already the default.

## GitHub Repository Variables

Set these variables before enabling deployment workflows:

```text
GCP_PROJECT_ID_NPRD
GCP_PROJECT_ID_PRD
GCP_REGION_NPRD
GCP_REGION_PRD
GCP_WORKLOAD_IDENTITY_PROVIDER_NPRD
GCP_WORKLOAD_IDENTITY_PROVIDER_PRD
GCP_SERVICE_ACCOUNT_NPRD
GCP_SERVICE_ACCOUNT_PRD
ARTIFACT_REGISTRY_REPOSITORY_NPRD
ARTIFACT_REGISTRY_REPOSITORY_PRD
CLOUD_RUN_SERVICE_NPRD
CLOUD_RUN_SERVICE_PRD
```

No long-lived GCP keys are required. GitHub Actions authenticates through OIDC.

## Dependabot

Dependabot is configured for GitHub Actions and `uv`. Cooldown delays normal version updates to reduce exposure to just-published compromised packages:

- GitHub Actions: 7-day default cooldown
- Python `uv`: 30 days for major, 14 days for minor, 7 days for patch

Security updates are not delayed by cooldown.

## Deployment

`deploy.yml` behavior:

- Push to `main`: deploys `nprd`.
- Manual `workflow_dispatch`: deploys selected `nprd` or `prd`.
- Production should be protected by the `prd` GitHub environment approval gate.
- Images are pushed as:
  - `REGION-docker.pkg.dev/PROJECT/REPOSITORY/REPO_NAME:sha-<short_sha>`
  - `REGION-docker.pkg.dev/PROJECT/REPOSITORY/REPO_NAME:<environment>`

## Rollback

Use the `Rollback` workflow manually. Provide:

- `environment`: `nprd` or `prd`
- `image`: full Artifact Registry image tag or digest

Example image:

```text
asia-south1-docker.pkg.dev/example-project/apps/my-service:sha-abc1234
```

Rollback uses the same OIDC auth, environment gates, and deployment concurrency as normal deploys.

## Releases

`release.yml` uses `googleapis/release-please-action@v4` with:

```yaml
release-type: simple
skip-github-pull-request: true
```

This creates GitHub releases and tags from Conventional Commits without maintaining package version files or changelog files in the repo. To force a specific version, run the workflow manually and set `release_as`, for example `1.2.3`.
