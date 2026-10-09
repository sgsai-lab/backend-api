---
applyTo: "app/**/*.py"
description: "FastAPI application code conventions: routers, schemas, services, models, errors, async DB access, logging."
---
# Python / FastAPI application code

## Module structure (`app/modules/<name>/`)

| File | Responsibility |
| --- | --- |
| `models.py` | SQLAlchemy 2 typed models (`Mapped[...]`, `mapped_column`) inheriting `app.db.base.Base` |
| `schemas.py` | Pydantic v2 models: `<X>Create`, `<X>Update` (all fields optional), `<X>Read` (`from_attributes=True`) |
| `service.py` | Business logic; async functions taking `session: AsyncSession` and the acting user. No FastAPI imports. |
| `router.py` | `APIRouter(prefix="/<plural>", tags=["<plural>"])`; parses input, calls service, returns schema |
| `deps.py` | Module-specific dependencies (e.g. load-and-authorise a resource) |

Register new routers in `app/api/v1/router.py`. Import new models in `migrations/env.py`.

## Routers

- Always declare `response_model` (or return annotation), `status_code` (201 create, 204 delete), `summary`, and `responses=` for error codes.
- Inject with `Annotated`: `session: Annotated[AsyncSession, Depends(get_session)]`, `user: Annotated[User, Depends(get_current_user)]`.
- No DB queries or business rules in routers.

## Schemas

- Request models: `model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)`.
- Constrain everything: `Field(min_length=, max_length=)`, `EmailStr`, `conint`/`Decimal` bounds, enums for statuses.
- PATCH: apply `payload.model_dump(exclude_unset=True)`.
- Money is `Decimal`, never `float`. Timestamps are timezone-aware UTC.

## Services & DB

- Async SQLAlchemy only (`await session.execute(select(...))`, `session.scalars`). No sync calls, no `requests` — use `httpx.AsyncClient`. Run CPU-heavy work (Argon2, Google cert verification) via `run_in_threadpool`.
- Owner-scoped resources: filter `Model.owner_id == user.id` and `Model.deleted_at.is_(None)` in **every** query; missing or foreign → `NotFoundError`.
- Handle unique violations by catching `IntegrityError` → `ConflictError`.
- Commit once per request in the service; use `with_for_update()` for token consumption / counters.
- Lists: paginate (`page`, `page_size` ≤ 100) and whitelist sort fields — never pass user input to `order_by` directly.

## Errors & logging

- Raise `app.core.errors` types; codes are `UPPER_SNAKE_CASE` and stable (clients depend on them).
- `log = structlog.get_logger(__name__)`; log events as snake_case names with key-value context: `log.info("project_created", project_id=str(p.id))`.
- Never log secrets, tokens, passwords, OTPs, emails in bulk, or request bodies.

## Style

- `from __future__` not needed (3.12). Use `X | None`, `list[str]`, `collections.abc` types.
- Keep functions small; no comments that restate code.
