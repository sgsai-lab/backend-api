"""Loads the recorded home export into Postgres and reads the contract back out (API-19)."""

import json
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.core.config import get_settings
from app.modules.hub.load import upsert
from app.modules.hub.migration import (
    client_json,
    product_json,
    project_json,
    rows_from_firestore,
)
from app.modules.hub.models import HubClient, HubMembership, HubProduct, HubProject

# Fixtures share the session-scoped loop (pyproject), so the tests must run on it too.
pytestmark = [pytest.mark.integration, pytest.mark.asyncio(loop_scope="session")]

FIXTURE = Path(__file__).parent.parent / "fixtures" / "home_contract.json"


@pytest.fixture
async def session() -> AsyncIterator[AsyncSession]:
    engine = create_async_engine(str(get_settings().database_url))
    async with engine.connect() as connection:
        transaction = await connection.begin()
        async with AsyncSession(bind=connection, expire_on_commit=False) as db:
            yield db
        await transaction.rollback()
    await engine.dispose()


def _row(model: Any) -> dict[str, Any]:
    return {column.key: getattr(model, column.key) for column in model.__table__.columns}


async def test_load_is_idempotent_and_reproduces_home_json(session: AsyncSession) -> None:
    contract = json.loads(FIXTURE.read_text(encoding="utf-8"))
    rows = rows_from_firestore(contract["collections"])
    role = contract["viewer_role"]

    await upsert(session, rows)
    counts = await upsert(session, rows)

    assert counts == {"clients": 1, "memberships": 2, "projects": 1, "products": 1, "assets": 0}
    client = (await session.scalars(select(HubClient))).one()
    members = await session.scalar(
        select(func.count()).select_from(HubMembership).where(HubMembership.client_id == client.id)
    )
    project = (await session.scalars(select(HubProject))).one()
    products = (await session.scalars(select(HubProduct).order_by(HubProduct.sort_order))).all()

    assert (
        client_json(_row(client), role=role, member_count=members or 0)
        == contract["responses"]["client"]
    )
    assert project_json(_row(project), role=role) == contract["responses"]["project"]
    assert [product_json(_row(p), role=role) for p in products] == contract["responses"][
        "products"
    ]["items"]


async def test_deleting_a_client_cascades(session: AsyncSession) -> None:
    contract = json.loads(FIXTURE.read_text(encoding="utf-8"))
    await upsert(session, rows_from_firestore(contract["collections"]))

    await session.execute(delete(HubClient))

    for model in (HubMembership, HubProject, HubProduct):
        assert await session.scalar(select(func.count()).select_from(model)) == 0
