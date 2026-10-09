# Zero-downtime patterns

Cloud Run keeps the old revision serving while the migration job runs and the new revision starts, so every migration must work with **both** the old and new code.

## Add a NOT NULL column

1. Release 1: add column nullable (or with `server_default`); code writes it.
2. Release 2: backfill in batches; then `ALTER COLUMN ... SET NOT NULL`.

## Rename a column

1. Release 1: add new column; code writes both, reads old.
2. Release 2: backfill; code reads new.
3. Release 3: stop writing old; drop old column.

## Drop a column / table

1. Release 1: remove all code usage (models included).
2. Release 2: drop it in a migration.

## Change a column type

Add new column → dual write → backfill → switch reads → drop old (same as rename).

## Add a value to a Postgres enum

```python
def upgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute("ALTER TYPE project_status ADD VALUE IF NOT EXISTS 'on_hold'")
```

Downgrade cannot remove enum values easily — document it and make downgrade a no-op with a comment.

## Create an index concurrently

```python
def upgrade() -> None:
    with op.get_context().autocommit_block():
        op.create_index(
            "ix_products_project_id",
            "products",
            ["project_id"],
            postgresql_concurrently=True,
            if_not_exists=True,
        )
```

## Batched backfill

```python
conn = op.get_bind()
while True:
    result = conn.execute(
        sa.text(
            "UPDATE users SET full_name = '' WHERE id IN "
            "(SELECT id FROM users WHERE full_name IS NULL LIMIT 1000)"
        )
    )
    if result.rowcount == 0:
        break
```
