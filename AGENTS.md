# AGENTS.md — backend-api

Instructions for AI coding agents (GitHub Copilot, Claude Code, Cursor, Codex). Humans: see [README.md](README.md).

## Project

SGS AI backend API. Python 3.12 · FastAPI · SQLAlchemy 2 (async, asyncpg) · Alembic · PostgreSQL 16 · structlog · Docker · Cloud Run (GCP). Package manager: **uv** (never pip/poetry). Work is tracked in GitHub issues `API-xx`; the 2-week plan is pinned issue #19. Auth design: issue #7 (ADR-001 — backend-owned auth, not Firebase).

## Commands

```bash
uv sync                         # install (uses uv.lock)
uv add <pkg> / uv add --dev <pkg>
docker compose up -d db mailpit # Postgres on localhost:5433, Mailpit UI :8025
make dev                        # uvicorn --reload on :8080, docs at /docs
make check                      # ruff + mypy --strict + pytest — run before finishing any task
make format                     # autofix lint + format
make migrate                    # alembic upgrade head
make revision m="msg"           # autogenerate migration
```

## Layout

```text
app/core/        config (pydantic-settings), logging, errors (AppError + envelope), middleware
app/db/          Base (naming convention), async engine/session (get_session)
app/api/         health routes, /api/v1 router aggregating modules
app/modules/<m>/ router.py · schemas.py · service.py · models.py · deps.py
app/modules/auth/ routes/*.py + services/*.py (split by flow); deps.py has CurrentUser, AdminUser, VerifiedUser
migrations/      Alembic (async env); import new models in migrations/env.py
tests/unit/      no DB;  tests/integration/  real Postgres, marked `integration`
```

## Non-negotiable rules

- Routes live under `/api/v1`; routers stay thin — business logic in `service.py`, DB access via the injected `AsyncSession`.
- Raise `AppError` subclasses (`NotFoundError`, `ConflictError`, `ForbiddenError`, `UnauthenticatedError`) — never return ad-hoc error dicts or raise bare `HTTPException` in services.
- The current user comes **only** from the verified access token (`get_current_user`). Never accept `owner_id`/`user_id` from the request body. Scope every query by owner; return **404** for other users' resources.
- Pydantic request schemas use `extra="forbid"`; never expose `password_hash`, secrets or token hashes in response models.
- Never log or return passwords, tokens, OTPs, recovery codes, secrets or `Authorization` headers.
- Parameterised SQL only (SQLAlchemy). No f-string SQL.
- Every schema change ships an Alembic migration with a working `downgrade()`; follow expand → migrate → contract.
- Config via `app/core/config.py` `Settings` + `.env.example` entry; secrets come from Secret Manager in GCP — never hardcode.
- Fully typed code that passes `mypy --strict`; no bare `# type: ignore`.
- New behaviour needs tests; endpoints need integration tests against Postgres, including auth-failure and cross-user cases.
- Conventional commits (`feat(auth): …`, `fix(projects): …`), reference the issue (`Refs #14`).

## Detailed guidance

- Path-specific rules: [.github/instructions/](.github/instructions/) (python, tests, migrations, docker/CI). Read the matching file before editing those paths.
- Reusable workflows (skills): [.claude/skills/](.claude/skills/) — `implement-github-issue`, `fastapi-crud-module`, `alembic-migration`, `api-integration-tests`, `auth-security-review`, `cloud-run-deploy`.
