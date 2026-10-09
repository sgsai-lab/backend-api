from datetime import timedelta
from urllib.parse import parse_qs, urlparse

import time_machine
from httpx import AsyncClient

from app.core.email import InMemoryEmailSender
from tests.integration.conftest import DEFAULT_PASSWORD, AuthHeaders, UserFactory

FORGOT = "/api/v1/auth/password/forgot"
RESET = "/api/v1/auth/password/reset"
CHANGE = "/api/v1/auth/password/change"
SET = "/api/v1/auth/password/set"
LOGIN = "/api/v1/auth/login"
ME = "/api/v1/users/me"
NEW_PASSWORD = "Granite-Lantern-77-Moss"


def _reset_token(outbox: InMemoryEmailSender) -> str:
    link = next(line for line in outbox.outbox[-1].text.splitlines() if "token=" in line)
    return parse_qs(urlparse(link.strip()).query)["token"][0]


async def test_forgot_password_unknown_email_sends_nothing(
    client: AsyncClient, outbox: InMemoryEmailSender
) -> None:
    response = await client.post(FORGOT, json={"email": "ghost@example.com"})

    assert response.status_code == 202
    assert outbox.outbox == []


async def test_reset_password_flow_revokes_sessions(
    client: AsyncClient,
    outbox: InMemoryEmailSender,
    user_factory: UserFactory,
    auth_headers: AuthHeaders,
) -> None:
    user = await user_factory()
    old_session = await auth_headers(user)
    await client.post(FORGOT, json={"email": user.email})
    token = _reset_token(outbox)

    response = await client.post(RESET, json={"token": token, "new_password": NEW_PASSWORD})

    assert response.status_code == 204
    assert outbox.outbox[-1].template == "password_changed"
    assert (await client.get(ME, headers=old_session)).status_code == 401
    login = await client.post(LOGIN, json={"email": user.email, "password": NEW_PASSWORD})
    assert login.status_code == 200
    reuse = await client.post(RESET, json={"token": token, "new_password": NEW_PASSWORD})
    assert reuse.status_code == 400


async def test_reset_token_expires_after_30_minutes(
    client: AsyncClient, outbox: InMemoryEmailSender, user_factory: UserFactory
) -> None:
    user = await user_factory()
    await client.post(FORGOT, json={"email": user.email})
    token = _reset_token(outbox)

    with time_machine.travel(timedelta(minutes=31)):
        response = await client.post(RESET, json={"token": token, "new_password": NEW_PASSWORD})

    assert response.status_code == 400


async def test_reset_rejects_weak_password(
    client: AsyncClient, outbox: InMemoryEmailSender, user_factory: UserFactory
) -> None:
    user = await user_factory()
    await client.post(FORGOT, json={"email": user.email})

    response = await client.post(
        RESET, json={"token": _reset_token(outbox), "new_password": "password123"}
    )

    assert response.status_code == 422
    assert response.json()["error"]["details"][0]["field"] == "body.new_password"


async def test_change_password_keeps_current_session_only(
    client: AsyncClient, user_factory: UserFactory, auth_headers: AuthHeaders
) -> None:
    user = await user_factory()
    current = await auth_headers(user)
    other = await auth_headers(user)

    response = await client.post(
        CHANGE,
        json={"current_password": DEFAULT_PASSWORD, "new_password": NEW_PASSWORD},
        headers=current,
    )

    assert response.status_code == 204
    assert (await client.get(ME, headers=current)).status_code == 200
    assert (await client.get(ME, headers=other)).status_code == 401


async def test_change_password_wrong_current(
    client: AsyncClient, auth_headers: AuthHeaders
) -> None:
    headers = await auth_headers()

    response = await client.post(
        CHANGE,
        json={"current_password": "wrong-password", "new_password": NEW_PASSWORD},
        headers=headers,
    )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "INVALID_CURRENT_PASSWORD"


async def test_change_password_must_differ(client: AsyncClient, auth_headers: AuthHeaders) -> None:
    headers = await auth_headers()

    response = await client.post(
        CHANGE,
        json={"current_password": DEFAULT_PASSWORD, "new_password": DEFAULT_PASSWORD},
        headers=headers,
    )

    assert response.status_code == 422


async def test_change_password_without_password_set(
    client: AsyncClient, auth_headers: AuthHeaders
) -> None:
    headers = await auth_headers(password=None)

    response = await client.post(
        CHANGE,
        json={"current_password": "anything-really", "new_password": NEW_PASSWORD},
        headers=headers,
    )

    assert response.json()["error"]["code"] == "PASSWORD_NOT_SET"


async def test_set_initial_password_only_once(
    client: AsyncClient, auth_headers: AuthHeaders
) -> None:
    headers = await auth_headers(password=None)

    first = await client.post(SET, json={"new_password": NEW_PASSWORD}, headers=headers)
    second = await client.post(SET, json={"new_password": NEW_PASSWORD}, headers=headers)

    assert first.status_code == 204
    assert second.status_code == 409
