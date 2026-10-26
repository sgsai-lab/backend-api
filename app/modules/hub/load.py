"""Loads a Firestore export of the client hub into PostgreSQL (API-19 spike).

    uv run python -m app.modules.hub.load export.json [--dry-run]

``export.json`` is ``{"collections": {"clients": [...], "memberships": [...], ...}}``, one list of
documents (with ``id``) per collection, e.g. produced by ``gcloud firestore export`` + conversion
or by ``scripts/record_home_contract.mjs``. Rows are upserted in one transaction, so the load is
idempotent and can be re-run right before cut-over.
"""

import argparse
import asyncio
import json
import sys
from pathlib import Path
from typing import Any

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.base import Base
from app.db.session import get_sessionmaker
from app.modules.hub.migration import HubRows, Row, rows_from_firestore
from app.modules.hub.models import HubAsset, HubClient, HubMembership, HubProduct, HubProject

# Parents first so foreign keys resolve inside the transaction.
TABLES: list[tuple[str, type[Base], tuple[str, ...]]] = [
    ("clients", HubClient, ("id",)),
    ("memberships", HubMembership, ("client_id", "user_id")),
    ("projects", HubProject, ("id",)),
    ("products", HubProduct, ("id",)),
    ("assets", HubAsset, ("id",)),
]


async def upsert(session: AsyncSession, rows: HubRows) -> dict[str, int]:
    counts: dict[str, int] = {}
    for name, model, keys in TABLES:
        batch: list[Row] = getattr(rows, name)
        counts[name] = len(batch)
        if not batch:
            continue
        statement = insert(model).values(batch)
        updates = {column: statement.excluded[column] for column in batch[0] if column not in keys}
        await session.execute(statement.on_conflict_do_update(index_elements=keys, set_=updates))
    return counts


def read_export(path: Path) -> dict[str, list[dict[str, Any]]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    collections = data.get("collections", data)
    if not isinstance(collections, dict):
        raise ValueError("export must contain a 'collections' object")
    return collections


async def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else None)
    parser.add_argument("export", type=Path)
    parser.add_argument("--dry-run", action="store_true", help="map and report without writing")
    args = parser.parse_args(argv)

    rows = rows_from_firestore(read_export(args.export))
    if args.dry_run:
        counts = {name: len(getattr(rows, name)) for name, _, _ in TABLES}
    else:
        async with get_sessionmaker()() as session, session.begin():
            counts = await upsert(session, rows)
    print(json.dumps({"dry_run": args.dry_run, "rows": counts, "skipped": rows.skipped}))
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main(sys.argv[1:])))
