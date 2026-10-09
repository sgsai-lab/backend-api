---
name: alembic-migration
description: "Create, review and verify Alembic database migrations for Postgres with zero-downtime (expand/migrate/contract) rules. Use when adding/changing models, tables, columns, indexes, enums, constraints, backfilling data, or when asked to 'add a migration', 'change the schema', 'rename a column', 'drop a table'."
argument-hint: "Short description of the schema change"
---

# Alembic migration

## Procedure

1. Make the model change in `app/modules/<m>/models.py`; ensure the module is imported in `migrations/env.py`.
2. Start Postgres and bring the DB to head:

   ```bash
   docker compose up -d db && make migrate
   ```

3. Generate: `make revision m="<imperative summary>"` (e.g. `add products table`).
4. **Review the generated file** against the checklist below and edit by hand.
5. Verify reversibility:

   ```bash
   uv run alembic upgrade head && uv run alembic downgrade -1 && uv run alembic upgrade head
   uv run alembic check   # no pending model changes
   ```

6. Run `make check`. Mention the migration and any deploy ordering in the PR body.

## Review checklist

- [ ] `downgrade()` fully reverses `upgrade()` (drop indexes/enums/types created).
- [ ] New columns on existing tables are nullable or have a `server_default`.
- [ ] No rename/drop of anything the currently deployed code still reads → split into multiple releases (see [patterns](./references/zero-downtime-patterns.md)).
- [ ] Enum types: created explicitly; dropped in downgrade (`sa.Enum(name=...).drop(op.get_bind())`).
- [ ] Indexes for every FK and every filter/sort column used by list endpoints; partial unique indexes include `postgresql_where`.
- [ ] Large-table indexes use `postgresql_concurrently=True` in an `autocommit_block()`.
- [ ] Data backfills batch by primary key and do not import app models.
- [ ] Extensions (`citext`, `pgcrypto`) created with `CREATE EXTENSION IF NOT EXISTS`.
- [ ] Autogenerate noise removed (spurious `server_default` / type diffs).
