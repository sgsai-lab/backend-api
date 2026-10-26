"""Replays the recorded home responses against this service's spike endpoints (API-19)."""

import json
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import delete

from app.db.session import get_sessionmaker
from app.modules.hub.load import upsert
from app.modules.hub.migration import rows_from_firestore
from app.modules.hub.models import HubClient

pytestmark = [pytest.mark.integration, pytest.mark.asyncio(loop_scope="session")]

FIXTURE = Path(__file__).parent.parent / "fixtures" / "home_contract.json"


@pytest.fixture
async def contract() -> AsyncIterator[dict[str, Any]]:
    data: dict[str, Any] = json.loads(FIXTURE.read_text(encoding="utf-8"))
    rows = rows_from_firestore(data["collections"])
    async with get_sessionmaker()() as session, session.begin():
        await upsert(session, rows)
    yield data
    async with get_sessionmaker()() as session, session.begin():
        await session.execute(
            delete(HubClient).where(HubClient.id.in_([c["id"] for c in rows.clients]))
        )


def lead(data: dict[str, Any]) -> dict[str, str]:
    user = next(u for u in data["collections"]["users"] if u["email"].startswith("lead@"))
    return {"X-Spike-User-Id": user["id"]}


async def test_reads_match_home_byte_for_byte(
    client: AsyncClient, contract: dict[str, Any]
) -> None:
    headers = lead(contract)
    expected = contract["responses"]
    client_id = expected["client"]["id"]

    client_response = await client.get(f"/api/v1/clients/{client_id}", headers=headers)
    project_response = await client.get(
        f"/api/v1/projects/{expected['project']['id']}", headers=headers
    )
    products_response = await client.get(f"/api/v1/products?client_id={client_id}", headers=headers)

    assert client_response.json() == expected["client"]
    assert project_response.json() == expected["project"]
    assert project_response.headers["etag"] == '"v1"'
    assert products_response.json() == expected["products"]


async def test_requires_identity(client: AsyncClient, contract: dict[str, Any]) -> None:
    response = await client.get(f"/api/v1/clients/{contract['responses']['client']['id']}")

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "UNAUTHORIZED"


async def test_other_tenants_get_404_not_data(
    client: AsyncClient, contract: dict[str, Any]
) -> None:
    outsider = {"X-Spike-User-Id": "someone-else"}
    expected = contract["responses"]

    by_client = await client.get(f"/api/v1/clients/{expected['client']['id']}", headers=outsider)
    by_project = await client.get(f"/api/v1/projects/{expected['project']['id']}", headers=outsider)
    listing = await client.get("/api/v1/products", headers=outsider)

    assert by_client.status_code == by_project.status_code == 404
    assert by_client.json()["error"]["code"] == "NOT_FOUND"
    assert listing.json() == {"items": [], "total": 0, "page": 1, "page_size": 20}


async def test_validation_errors_use_home_envelope(
    client: AsyncClient, contract: dict[str, Any]
) -> None:
    response = await client.get("/api/v1/products?page=0", headers=lead(contract))

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"
    assert response.json()["error"]["details"][0]["field"] == "query.page"
