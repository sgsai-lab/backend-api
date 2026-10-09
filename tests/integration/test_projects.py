import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.projects.models import Project
from tests.integration.conftest import AuthHeaders

pytestmark = pytest.mark.integration

BASE = "/api/v1/projects"


async def _create(client: AsyncClient, headers: dict[str, str], **overrides: Any) -> Any:
    body = {"name": "Alpha", "tags": ["Blue"], **overrides}
    response = await client.post(BASE, json=body, headers=headers)
    assert response.status_code == 201, response.text
    return response.json()


async def test_create_project_sets_owner_from_token(
    client: AsyncClient, auth_headers: AuthHeaders
) -> None:
    headers = await auth_headers()

    response = await client.post(
        BASE, json={"name": "Alpha", "tags": ["Blue", "blue"]}, headers=headers
    )

    me = (await client.get("/api/v1/users/me", headers=headers)).json()
    body = response.json()
    assert response.status_code == 201
    assert response.headers["Location"] == f"{BASE}/{body['id']}"
    assert response.headers["ETag"]
    assert body["owner_id"] == me["id"]
    assert body["tags"] == ["blue"]
    assert body["status"] == "draft"
    assert body["metadata"] == {}


async def test_create_project_rejects_owner_id_in_body(
    client: AsyncClient, auth_headers: AuthHeaders
) -> None:
    headers = await auth_headers()

    response = await client.post(
        BASE, json={"name": "X", "owner_id": str(uuid.uuid4())}, headers=headers
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"


async def test_create_project_end_before_start_returns_422(
    client: AsyncClient, auth_headers: AuthHeaders
) -> None:
    headers = await auth_headers()

    response = await client.post(
        BASE,
        json={"name": "X", "start_date": "2026-05-02", "end_date": "2026-05-01"},
        headers=headers,
    )

    assert response.status_code == 422


async def test_create_project_oversized_metadata_returns_422(
    client: AsyncClient, auth_headers: AuthHeaders
) -> None:
    headers = await auth_headers()

    response = await client.post(
        BASE, json={"name": "X", "metadata": {"blob": "x" * 17_000}}, headers=headers
    )

    assert response.status_code == 422


async def test_create_project_duplicate_name_returns_409(
    client: AsyncClient, auth_headers: AuthHeaders
) -> None:
    headers = await auth_headers()
    await _create(client, headers)

    response = await client.post(BASE, json={"name": "Alpha"}, headers=headers)

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "CONFLICT"


async def test_same_name_allowed_for_different_owners(
    client: AsyncClient, auth_headers: AuthHeaders
) -> None:
    await _create(client, await auth_headers())

    await _create(client, await auth_headers())


async def test_create_project_unverified_email_returns_403(
    client: AsyncClient, auth_headers: AuthHeaders
) -> None:
    headers = await auth_headers(verified=False)

    response = await client.post(BASE, json={"name": "X"}, headers=headers)

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "EMAIL_NOT_VERIFIED"


async def test_project_endpoints_require_auth(client: AsyncClient) -> None:
    response = await client.get(BASE)

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "UNAUTHENTICATED"


@pytest.mark.parametrize("method", ["GET", "PATCH", "DELETE"])
async def test_other_users_project_returns_404(
    client: AsyncClient, auth_headers: AuthHeaders, method: str
) -> None:
    owner, intruder = await auth_headers(), await auth_headers()
    project = await _create(client, owner)

    response = await client.request(
        method,
        f"{BASE}/{project['id']}",
        headers=intruder,
        json={"name": "Hacked"} if method == "PATCH" else None,
    )

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "RESOURCE_NOT_FOUND"


async def test_list_projects_only_returns_mine_paginated(
    client: AsyncClient, auth_headers: AuthHeaders
) -> None:
    mine, other = await auth_headers(), await auth_headers()
    for i in range(3):
        await _create(client, mine, name=f"P{i}")
    await _create(client, other, name="Theirs")

    response = await client.get(f"{BASE}?page_size=2&sort=name", headers=mine)

    body = response.json()
    assert body["total"] == 3
    assert [p["name"] for p in body["items"]] == ["P0", "P1"]


async def test_list_projects_filters_by_status_tag_and_query(
    client: AsyncClient, auth_headers: AuthHeaders
) -> None:
    headers = await auth_headers()
    await _create(client, headers, name="Website", status="active", tags=["web", "ui"])
    await _create(client, headers, name="Mobile", status="active", tags=["ui"])
    await _create(client, headers, name="Data", description="website analytics", tags=["web"])

    by_status = await client.get(f"{BASE}?status=active&sort=name", headers=headers)
    by_tags = await client.get(f"{BASE}?tag=web&tag=ui", headers=headers)
    by_query = await client.get(f"{BASE}?q=website&sort=name", headers=headers)

    assert [p["name"] for p in by_status.json()["items"]] == ["Mobile", "Website"]
    assert [p["name"] for p in by_tags.json()["items"]] == ["Website"]
    assert [p["name"] for p in by_query.json()["items"]] == ["Data", "Website"]


async def test_list_projects_filters_by_created_range(
    client: AsyncClient, auth_headers: AuthHeaders
) -> None:
    headers = await auth_headers()
    await _create(client, headers)
    future = (datetime.now(UTC) + timedelta(days=1)).isoformat()

    response = await client.get(BASE, params={"created_from": future}, headers=headers)

    assert response.json()["total"] == 0


async def test_list_projects_invalid_sort_returns_422(
    client: AsyncClient, auth_headers: AuthHeaders
) -> None:
    headers = await auth_headers()

    response = await client.get(f"{BASE}?sort=owner_id", headers=headers)

    assert response.status_code == 422


async def test_list_projects_owner_id_forbidden_for_non_admin(
    client: AsyncClient, auth_headers: AuthHeaders
) -> None:
    headers = await auth_headers()

    response = await client.get(f"{BASE}?owner_id={uuid.uuid4()}", headers=headers)

    assert response.status_code == 403


async def test_admin_can_list_projects_by_owner(
    client: AsyncClient, auth_headers: AuthHeaders, admin_headers: Any
) -> None:
    owner = await auth_headers()
    project = await _create(client, owner)

    response = await client.get(
        f"{BASE}?owner_id={project['owner_id']}", headers=await admin_headers()
    )

    assert response.status_code == 200
    assert [p["id"] for p in response.json()["items"]] == [project["id"]]


async def test_patch_project_updates_only_sent_fields(
    client: AsyncClient, auth_headers: AuthHeaders
) -> None:
    headers = await auth_headers()
    project = await _create(client, headers, description="keep")

    response = await client.patch(
        f"{BASE}/{project['id']}", json={"name": "Beta", "status": "on_hold"}, headers=headers
    )

    body = response.json()
    assert response.status_code == 200
    assert body["name"] == "Beta"
    assert body["status"] == "on_hold"
    assert body["description"] == "keep"


async def test_patch_project_null_name_returns_422(
    client: AsyncClient, auth_headers: AuthHeaders
) -> None:
    headers = await auth_headers()
    project = await _create(client, headers)

    response = await client.patch(f"{BASE}/{project['id']}", json={"name": None}, headers=headers)

    assert response.status_code == 422


async def test_patch_project_end_before_existing_start_returns_422(
    client: AsyncClient, auth_headers: AuthHeaders
) -> None:
    headers = await auth_headers()
    project = await _create(client, headers, start_date="2026-05-10")

    response = await client.patch(
        f"{BASE}/{project['id']}", json={"end_date": "2026-05-01"}, headers=headers
    )

    assert response.status_code == 422
    assert response.json()["error"]["details"][0]["field"] == "end_date"


async def test_patch_project_with_matching_etag_succeeds(
    client: AsyncClient, auth_headers: AuthHeaders
) -> None:
    headers = await auth_headers()
    project = await _create(client, headers)
    etag = (await client.get(f"{BASE}/{project['id']}", headers=headers)).headers["ETag"]

    response = await client.patch(
        f"{BASE}/{project['id']}", json={"name": "Beta"}, headers={**headers, "If-Match": etag}
    )

    assert response.status_code == 200


async def test_patch_project_with_stale_etag_returns_412(
    client: AsyncClient, auth_headers: AuthHeaders
) -> None:
    headers = await auth_headers()
    project = await _create(client, headers)

    response = await client.patch(
        f"{BASE}/{project['id']}", json={"name": "Beta"}, headers={**headers, "If-Match": '"1"'}
    )

    assert response.status_code == 412
    assert response.json()["error"]["code"] == "PRECONDITION_FAILED"


async def test_deleted_project_is_not_found_and_can_be_restored(
    client: AsyncClient, auth_headers: AuthHeaders
) -> None:
    headers = await auth_headers()
    project = await _create(client, headers)

    delete = await client.delete(f"{BASE}/{project['id']}", headers=headers)
    get = await client.get(f"{BASE}/{project['id']}", headers=headers)
    restore = await client.post(f"{BASE}/{project['id']}/restore", headers=headers)

    assert delete.status_code == 204
    assert get.status_code == 404
    assert restore.status_code == 200
    assert restore.json()["id"] == project["id"]


async def test_deleted_name_can_be_reused(client: AsyncClient, auth_headers: AuthHeaders) -> None:
    headers = await auth_headers()
    project = await _create(client, headers)
    await client.delete(f"{BASE}/{project['id']}", headers=headers)

    await _create(client, headers)

    restore = await client.post(f"{BASE}/{project['id']}/restore", headers=headers)
    assert restore.status_code == 409


async def test_restore_after_window_returns_404(
    client: AsyncClient, auth_headers: AuthHeaders, session: AsyncSession
) -> None:
    headers = await auth_headers()
    project = await _create(client, headers)
    await session.execute(
        update(Project)
        .where(Project.id == uuid.UUID(project["id"]))
        .values(deleted_at=datetime.now(UTC) - timedelta(days=31))
    )

    response = await client.post(f"{BASE}/{project['id']}/restore", headers=headers)

    assert response.status_code == 404


async def test_restore_other_users_project_returns_404(
    client: AsyncClient, auth_headers: AuthHeaders
) -> None:
    owner, intruder = await auth_headers(), await auth_headers()
    project = await _create(client, owner)
    await client.delete(f"{BASE}/{project['id']}", headers=owner)

    response = await client.post(f"{BASE}/{project['id']}/restore", headers=intruder)

    assert response.status_code == 404
