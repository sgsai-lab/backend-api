---
applyTo: "**/Dockerfile,**/docker-compose.yml,**/.dockerignore,.github/workflows/**,**/Makefile"
description: "Container, Compose, Makefile and GitHub Actions conventions for Cloud Run deployment."
---
# Docker, CI/CD

## Dockerfile

- Multi-stage: builder runs `uv sync --locked --no-dev --no-install-project`; runtime copies only `.venv`, `app/`, `migrations/`, `alembic.ini`.
- Runtime runs as non-root `uid 10001`; listens on `$PORT` via `python -m app`.
- Pin base images (by digest in release builds). Never `COPY .env` or credentials; keep `.dockerignore` in sync.
- Keep final image < 200 MB and free of build tools.

## docker-compose

- Local only. Postgres published on host `5433`; Mailpit on `1025`/`8025`. No production secrets.

## GitHub Actions

- `permissions: contents: read` at workflow level; grant `id-token: write` only on deploy jobs (Workload Identity Federation — never service-account keys).
- Use `concurrency` with `cancel-in-progress` for PR workflows; `timeout-minutes` on every job.
- Pin third-party actions to a full commit SHA with a version comment.
- Use `astral-sh/setup-uv` with cache and `uv sync --locked`.
- Build the image once, tag with `${{ github.sha }}`, promote the same digest across environments.
- Run `alembic upgrade head` as a Cloud Run Job **before** deploying the service.
- Deploy with `--set-secrets` (Secret Manager) — never plain env vars for secrets.
- Keep PR pipeline under 10 minutes.
