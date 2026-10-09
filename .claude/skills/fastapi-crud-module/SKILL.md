---
name: fastapi-crud-module
description: "Scaffold or extend an owner-scoped CRUD resource (model, schemas, service, router, migration, tests) in the FastAPI backend. Use when adding a new entity/endpoint set such as projects, products, or any 'create/list/get/update/delete' API, or when asked to 'add CRUD', 'new module', 'new resource', 'new endpoints'."
argument-hint: "Entity name (singular), e.g. product"
---

# FastAPI CRUD module

Produces a resource with: `POST` (201), paginated/filterable `GET` list, `GET /{id}`, `PATCH /{id}`, soft `DELETE /{id}` (204) — all scoped to the authenticated owner.

## Prerequisites

Shared helpers used by the templates. If any are missing, create them first exactly as in [shared-helpers.md](./references/shared-helpers.md):

- `app/db/mixins.py` — `UUIDPrimaryKey`, `Timestamps`, `SoftDelete`
- `app/core/pagination.py` — `PageParams`, `Page[T]`, `paginate()`
- `app/modules/auth/deps.py` — `get_current_user` (issue API-06), `CurrentUser` alias
- `app/modules/users/models.py` — `User`

## Procedure

1. Copy the templates into `app/modules/<plural>/`, replacing `Widget`/`widget`/`widgets` with the entity names:
   - [models.py](./assets/models.py.tmpl)
   - [schemas.py](./assets/schemas.py.tmpl)
   - [service.py](./assets/service.py.tmpl)
   - [router.py](./assets/router.py.tmpl)
   - [test file](./assets/test_widgets.py.tmpl) → `tests/integration/test_<plural>.py`
2. Adapt fields to the issue's data model. Keep: `owner_id` from token, `extra="forbid"`, length/number bounds, partial unique index `WHERE deleted_at IS NULL`, sort whitelist.
3. Register the router in `app/api/v1/router.py`; import the model in `migrations/env.py`.
4. Create the migration with the `alembic-migration` skill; check indexes (owner_id, FKs, GIN for arrays/jsonb) and check constraints.
5. Extend tests for every filter, sort key, conflict and validation rule in the issue.
6. `make migrate && make check`.

## Rules enforced by the templates

- Owner taken from `CurrentUser`; any `owner_id` in the body → 422 (`extra="forbid"`).
- Foreign or soft-deleted rows → `NotFoundError` (404), never 403 (no existence leak).
- Duplicate unique key → `ConflictError` (409) via `IntegrityError`.
- PATCH applies `model_dump(exclude_unset=True)`; explicit `null` clears nullable fields.
- List: `page`/`page_size≤100`, sort only by whitelisted keys, ILIKE search with escaped wildcards.
