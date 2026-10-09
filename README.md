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

Or run everything in containers: `docker compose up --build` (a one-shot `migrate` service runs
`alembic upgrade head` before the API starts).

Create the first administrator: `make admin email=you@example.com` (prompts for a password).

| URL | Purpose |
| --- | --- |
| `GET /healthz` | Liveness (no dependencies) |
| `GET /readyz` | Readiness (checks DB, 503 when unreachable) |
| `GET /.well-known/jwks.json` | Public keys for verifying access tokens |
| `/docs` | OpenAPI UI (disabled in production) |
| http://localhost:8025 | Mailpit — local email inbox |

## API overview (`/api/v1`)

| Area | Endpoints |
| --- | --- |
| Sign-up | `POST auth/signup`, `POST auth/verify-email`, `POST auth/verify-email/resend` |
| Sign-in & sessions | `POST auth/login`, `POST auth/token/refresh`, `POST auth/logout`, `POST auth/logout-all`, `GET auth/sessions`, `DELETE auth/sessions/{id}` |
| Google | `POST auth/google`, `POST auth/google/link`, `DELETE auth/google/link` |
| Password | `POST auth/password/forgot`, `.../reset`, `.../change`, `.../set` |
| MFA (TOTP) | `GET auth/mfa`, `POST auth/mfa/totp/setup`, `.../totp/confirm`, `POST auth/mfa/verify`, `POST auth/mfa/recovery-codes`, `DELETE auth/mfa/totp` |
| Users | `GET/PATCH/DELETE users/me`; admin: `POST/GET users`, `GET/PATCH/DELETE users/{id}` |

Auth model (ADR-001): ES256 access JWT (15 min) + opaque rotating refresh token (30 days,
reuse detection). Web clients send `X-Client: web` and receive the refresh token in an
`HttpOnly` `__Host-refresh` cookie instead of the response body. Admin endpoints require a
session that completed MFA.

## Commands

| Command | Description |
| --- | --- |
| `make check` | Lint + typecheck + tests (same as CI) |
| `make cov` | Tests with coverage (fails under 80%) |
| `make audit` | Dependency vulnerability audit (pip-audit) |
| `make format` | Auto-fix lint and format |
| `make revision m="add users"` | Autogenerate a migration |
| `make scan` | Build image and Trivy-scan it |

## Layout

```
app/
  core/        config, logging, errors, middleware, tokens, passwords, email, rate limit
  db/          SQLAlchemy base, mixins, async session
  api/         health routes, /api/v1 router
  modules/     feature modules: auth, users, projects, products
               (router.py, schemas.py, service.py, models.py; auth splits routes/ and services/)
  templates/   email templates (text + HTML)
migrations/    Alembic migrations
tests/         unit/ (no DB) and integration/ (real Postgres)
```

## Quality gates

CI (`.github/workflows/ci.yml`) runs on every PR: ruff + mypy `--strict` (`lint`),
migrations up/down/up + pytest with coverage ≥ 80% (`test`), SonarQube Cloud quality gate
(`sonar`, needs the `SONAR_TOKEN` secret), pip-audit + Trivy (`security`), and Docker build +
image scan (`build`). PR titles must follow Conventional Commits. Merges to `develop` deploy
to Cloud Run via `.github/workflows/deploy-dev.yml` (Workload Identity Federation).

## Branching and environments

`feature/*` → PR into `develop` → auto-deploy to **development** (GitHub environment restricted
to `develop`) → PR `develop` → `main` for release. Never PR features straight into `main`.

## Conventions

- All business routes are versioned under `/api/v1`.
- Errors use one envelope: `{"error": {"code", "message", "requestId", "details"}}`.
- Logs are structured JSON on stdout with Cloud Logging `severity`; never log secrets, tokens, passwords or OTPs.
- Migrations follow expand → migrate → contract and must be backwards compatible with the deployed version.
- Conventional commits; PRs need green CI.

## AI coding assistants

Context loads automatically for GitHub Copilot (VS Code / github.com) and Claude Code:

| File | Purpose |
| --- | --- |
| [AGENTS.md](AGENTS.md) | Always-on project rules (Copilot reads it directly; Claude via [CLAUDE.md](CLAUDE.md)) |
| [.github/copilot-instructions.md](.github/copilot-instructions.md) | Pointer for Copilot code review |
| [.github/instructions/](.github/instructions/) | Path-specific rules (`applyTo` globs) |
| [.claude/skills/](.claude/skills/) | On-demand workflows shared by Copilot and Claude: `implement-github-issue`, `fastapi-crud-module`, `alembic-migration`, `api-integration-tests`, `auth-security-review`, `cloud-run-deploy` |

Invoke a skill explicitly with `/<skill-name>` in chat, or let the agent pick it from its description.
