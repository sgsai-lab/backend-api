from datetime import timedelta

import jwt
import pytest
import time_machine
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ForbiddenError
from app.core.tokens import get_signing_keys
from app.modules.auth.deps import require_verified_email
from app.modules.users.models import UserStatus
from tests.integration.conftest import DEFAULT_PASSWORD, AuthHeaders, UserFactory

ME = "/api/v1/users/me"


async def test_get_me_returns_profile_without_secrets(
    client: AsyncClient, auth_headers: AuthHeaders, user_factory: UserFactory
) -> None:
    user = await user_factory(full_name="Ada Lovelace")
    headers = await auth_headers(user)

    response = await client.get(ME, headers=headers)

    assert response.status_code == 200
    body = response.json()
    assert body["id"] == str(user.id)
    assert body["full_name"] == "Ada Lovelace"
    assert body["email_verified"] is True
    assert "password_hash" not in body
    assert response.headers["Cache-Control"] == "no-store"


async def test_get_me_without_header_returns_401(client: AsyncClient) -> None:
    response = await client.get(ME)

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "UNAUTHENTICATED"
    assert response.headers["WWW-Authenticate"] == "Bearer"


async def test_get_me_with_tampered_token_returns_401(
    client: AsyncClient, auth_headers: AuthHeaders
) -> None:
    headers = await auth_headers()
    token = headers["Authorization"].removeprefix("Bearer ")

    response = await client.get(ME, headers={"Authorization": f"Bearer {token[:-4]}abcd"})

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "UNAUTHENTICATED"


async def test_get_me_with_expired_token_returns_token_expired(
    client: AsyncClient, auth_headers: AuthHeaders
) -> None:
    headers = await auth_headers()

    with time_machine.travel(timedelta(minutes=16)):
        response = await client.get(ME, headers=headers)

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "TOKEN_EXPIRED"


async def test_get_me_with_wrong_audience_returns_401(
    client: AsyncClient, auth_headers: AuthHeaders
) -> None:
    headers = await auth_headers()
    claims = jwt.decode(
        headers["Authorization"].removeprefix("Bearer "), options={"verify_signature": False}
    )
    keys = get_signing_keys()
    forged = jwt.encode(
        {**claims, "aud": "someone-else"},
        keys.private_key,
        algorithm="ES256",
        headers={"kid": keys.kid},
    )

    response = await client.get(ME, headers={"Authorization": f"Bearer {forged}"})

    assert response.status_code == 401


async def test_get_me_for_disabled_user_returns_401(
    client: AsyncClient, auth_headers: AuthHeaders, user_factory: UserFactory, session: AsyncSession
) -> None:
    user = await user_factory()
    headers = await auth_headers(user)
    user.status = UserStatus.DISABLED
    await session.flush()

    response = await client.get(ME, headers=headers)

    assert response.status_code == 401


async def test_update_me_changes_allowed_fields(
    client: AsyncClient, auth_headers: AuthHeaders
) -> None:
    headers = await auth_headers()

    response = await client.patch(
        ME,
        json={"full_name": "  New Name ", "avatar_url": "https://cdn.example.com/a.png"},
        headers=headers,
    )

    assert response.status_code == 200
    assert response.json()["full_name"] == "New Name"
    assert response.json()["avatar_url"] == "https://cdn.example.com/a.png"


async def test_update_me_clears_avatar_with_null(
    client: AsyncClient, auth_headers: AuthHeaders
) -> None:
    headers = await auth_headers()
    await client.patch(ME, json={"avatar_url": "https://cdn.example.com/a.png"}, headers=headers)

    response = await client.patch(ME, json={"avatar_url": None, "full_name": None}, headers=headers)

    assert response.json()["avatar_url"] is None
    assert response.json()["full_name"] == "Test User"


async def test_update_me_rejects_role_mass_assignment(
    client: AsyncClient, auth_headers: AuthHeaders
) -> None:
    headers = await auth_headers()

    response = await client.patch(ME, json={"role": "admin"}, headers=headers)

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"


async def test_delete_me_requires_password(client: AsyncClient, auth_headers: AuthHeaders) -> None:
    headers = await auth_headers()

    response = await client.request(
        "DELETE", ME, json={"password": "wrong-password"}, headers=headers
    )

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "REAUTHENTICATION_FAILED"


async def test_delete_me_soft_deletes_and_signs_out(
    client: AsyncClient, auth_headers: AuthHeaders, user_factory: UserFactory
) -> None:
    user = await user_factory()
    email = user.email
    headers = await auth_headers(user)

    response = await client.request(
        "DELETE", ME, json={"password": DEFAULT_PASSWORD}, headers=headers
    )

    assert response.status_code == 204
    assert (await client.get(ME, headers=headers)).status_code == 401
    login = await client.post(
        "/api/v1/auth/login", json={"email": email, "password": DEFAULT_PASSWORD}
    )
    assert login.status_code == 401


async def test_require_verified_email_blocks_unverified_users(user_factory: UserFactory) -> None:
    unverified = await user_factory(verified=False)
    verified = await user_factory()

    with pytest.raises(ForbiddenError) as exc:
        await require_verified_email(unverified)

    assert exc.value.code == "EMAIL_NOT_VERIFIED"
    assert await require_verified_email(verified) is verified


async def test_delete_me_google_only_user_without_mfa_is_forbidden(
    client: AsyncClient, auth_headers: AuthHeaders
) -> None:
    headers = await auth_headers(password=None)

    response = await client.request("DELETE", ME, json={}, headers=headers)

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "REAUTHENTICATION_UNAVAILABLE"
