# backend-api

SGS AI Technology — backend API. Python 3.12 · FastAPI · SQLAlchemy 2 (async) · Alembic · PostgreSQL 16 · Docker · Cloud Run (GCP).

## Quick start

Prerequisites: [uv](https://docs.astral.sh/uv/), Docker.

```bash
cp .env.example .env
make install          # uv sync (creates .venv)
docker compose up -d db mailpit
make migrate          # alembic upgrade head
make dev              # http://localhost:8080/docs
```

Or run everything in containers: `docker compose up --build`.

| URL | Purpose |
| --- | --- |
| `GET /healthz` | Liveness (no dependencies) |
| `GET /readyz` | Readiness (checks DB, 503 when unreachable) |
| `/docs` | OpenAPI UI (disabled in production) |
| http://localhost:8025 | Mailpit — local email inbox |

## Commands

| Command | Description |
| --- | --- |
| `make check` | Lint + typecheck + tests (same as CI) |
| `make format` | Auto-fix lint and format |
| `make revision m="add users"` | Autogenerate a migration |
| `make scan` | Build image and Trivy-scan it |

## Layout

```
app/
  core/        config, logging, errors, middleware
  db/          SQLAlchemy base + async session
  api/         health routes, /api/v1 router
  modules/     feature modules: auth, users, projects, products
               (each: router.py, schemas.py, service.py, models.py)
migrations/    Alembic migrations
tests/         unit/ and integration/
```

## Conventions

- All business routes are versioned under `/api/v1`.
- Errors use one envelope: `{"error": {"code", "message", "requestId", "details"}}`.
- Logs are structured JSON on stdout with Cloud Logging `severity`; never log secrets, tokens, passwords or OTPs.
- Migrations follow expand → migrate → contract and must be backwards compatible with the deployed version.
- Conventional commits; PRs need green CI.
