import uuid
from collections.abc import Awaitable, Callable

import pytest
from httpx import AsyncClient

from app.core.config import get_settings
from app.core.email import InMemoryEmailSender
from app.modules.users.models import UserRole
from tests.integration.conftest import AuthHeaders, UserFactory

USERS = "/api/v1/users"
AdminHeaders = Callable[[], Awaitable[dict[str, str]]]


async def test_admin_routes_reject_normal_users(
    client: AsyncClient, auth_headers: AuthHeaders
) -> None:
    headers = await auth_headers()

    response = await client.get(USERS, headers=headers)

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "FORBIDDEN"


async def test_admin_routes_require_mfa_session(
    client: AsyncClient, auth_headers: AuthHeaders
) -> None:
    headers = await auth_headers(role=UserRole.ADMIN, amr=("pwd",))

    response = await client.get(USERS, headers=headers)

    assert response.json()["error"]["code"] == "MFA_REQUIRED"


async def test_admin_routes_allow_password_session_when_mfa_not_required(
    client: AsyncClient, auth_headers: AuthHeaders, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(get_settings(), "admin_require_mfa", False)
    headers = await auth_headers(role=UserRole.ADMIN, amr=("pwd",))

    response = await client.get(USERS, headers=headers)

    assert response.status_code == 200


async def test_admin_lists_users_with_filters_and_pagination(
    client: AsyncClient, admin_headers: AdminHeaders, user_factory: UserFactory
) -> None:
    headers = await admin_headers()
    for i in range(3):
        await user_factory(email=f"zz-filter-{i}@example.com", full_name=f"Filter {i}")

    page = await client.get(
        USERS, params={"q": "zz-filter", "page_size": 2, "sort": "email"}, headers=headers
    )
    escaped = await client.get(USERS, params={"q": "%"}, headers=headers)

    body = page.json()
    assert body["total"] == 3
    assert [u["email"] for u in body["items"]] == [
        "zz-filter-0@example.com",
        "zz-filter-1@example.com",
    ]
    assert escaped.json()["total"] == 0


async def test_admin_list_rejects_oversized_page(
    client: AsyncClient, admin_headers: AdminHeaders
) -> None:
    response = await client.get(USERS, params={"page_size": 101}, headers=await admin_headers())

    assert response.status_code == 422


async def test_admin_creates_user_and_sends_invite(
    client: AsyncClient, admin_headers: AdminHeaders, outbox: InMemoryEmailSender
) -> None:
    headers = await admin_headers()

    response = await client.post(
        USERS, json={"email": "invitee@example.com", "full_name": "Invitee"}, headers=headers
    )
    duplicate = await client.post(
        USERS, json={"email": "invitee@example.com", "full_name": "Invitee"}, headers=headers
    )

    assert response.status_code == 201
    assert response.headers["Location"] == f"{USERS}/{response.json()['id']}"
    assert outbox.outbox[-1].template == "invite"
    assert duplicate.status_code == 409


async def test_admin_get_update_and_delete_user(
    client: AsyncClient,
    admin_headers: AdminHeaders,
    user_factory: UserFactory,
    auth_headers: AuthHeaders,
) -> None:
    headers = await admin_headers()
    target = await user_factory()
    target_email = target.email
    target_headers = await auth_headers(target)

    got = await client.get(f"{USERS}/{target.id}", headers=headers)
    updated = await client.patch(
        f"{USERS}/{target.id}", json={"full_name": "Renamed", "status": "disabled"}, headers=headers
    )
    deleted = await client.delete(f"{USERS}/{target.id}", headers=headers)
    after = await client.get(f"{USERS}/{target.id}", headers=headers)

    assert got.json()["email"] == target_email
    assert updated.json()["full_name"] == "Renamed"
    assert updated.json()["status"] == "disabled"
    assert (await client.get(f"{USERS}/me", headers=target_headers)).status_code == 401
    assert deleted.status_code == 204
    assert after.status_code == 404


async def test_admin_cannot_modify_or_delete_self(
    client: AsyncClient, auth_headers: AuthHeaders, user_factory: UserFactory
) -> None:
    admin = await user_factory(role=UserRole.ADMIN)
    headers = await auth_headers(admin, amr=("pwd", "mfa"))

    demote = await client.patch(f"{USERS}/{admin.id}", json={"role": "user"}, headers=headers)
    delete = await client.delete(f"{USERS}/{admin.id}", headers=headers)
    rename = await client.patch(f"{USERS}/{admin.id}", json={"full_name": "Me"}, headers=headers)

    assert demote.json()["error"]["code"] == "CANNOT_MODIFY_SELF"
    assert delete.json()["error"]["code"] == "CANNOT_MODIFY_SELF"
    assert rename.status_code == 200


async def test_admin_can_demote_another_admin(
    client: AsyncClient, admin_headers: AdminHeaders, user_factory: UserFactory
) -> None:
    headers = await admin_headers()
    other = await user_factory(role=UserRole.ADMIN)

    response = await client.patch(f"{USERS}/{other.id}", json={"role": "user"}, headers=headers)

    assert response.json()["role"] == "user"


async def test_admin_unknown_user_returns_404(
    client: AsyncClient, admin_headers: AdminHeaders
) -> None:
    response = await client.get(f"{USERS}/{uuid.uuid4()}", headers=await admin_headers())

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "RESOURCE_NOT_FOUND"
