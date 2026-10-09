from datetime import timedelta
from typing import Any

import time_machine
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.email import InMemoryEmailSender
from app.core.rate_limit import RateLimiter
from app.modules.auth.responses import REFRESH_COOKIE
from app.modules.users.models import UserStatus
from tests.integration.conftest import DEFAULT_PASSWORD, AuthHeaders, UserFactory

LOGIN = "/api/v1/auth/login"
REFRESH = "/api/v1/auth/token/refresh"
SESSIONS = "/api/v1/auth/sessions"
ME = "/api/v1/users/me"


async def _login(
    client: AsyncClient, email: str, password: str = DEFAULT_PASSWORD
) -> dict[str, Any]:
    response = await client.post(LOGIN, json={"email": email, "password": password})
    assert response.status_code == 200, response.text
    return dict(response.json())


def _bearer(tokens: dict[str, Any]) -> dict[str, str]:
    return {"Authorization": f"Bearer {tokens['access_token']}"}


async def test_login_returns_tokens_usable_for_me(
    client: AsyncClient, user_factory: UserFactory
) -> None:
    user = await user_factory()

    tokens = await _login(client, user.email.upper())

    assert tokens["token_type"] == "Bearer"
    assert tokens["expires_in"] == 900
    me = await client.get(ME, headers=_bearer(tokens))
    assert me.json()["id"] == str(user.id)


async def test_login_wrong_password_and_unknown_email_look_identical(
    client: AsyncClient, user_factory: UserFactory
) -> None:
    user = await user_factory()

    wrong = await client.post(LOGIN, json={"email": user.email, "password": "nope-nope-nope"})
    unknown = await client.post(LOGIN, json={"email": "ghost@example.com", "password": "x"})

    assert wrong.status_code == unknown.status_code == 401
    assert wrong.json()["error"]["code"] == unknown.json()["error"]["code"] == "INVALID_CREDENTIALS"
    assert wrong.json()["error"]["message"] == unknown.json()["error"]["message"]


async def test_login_disabled_user_is_forbidden(
    client: AsyncClient, user_factory: UserFactory, session: AsyncSession
) -> None:
    user = await user_factory()
    user.status = UserStatus.DISABLED
    await session.flush()

    response = await client.post(LOGIN, json={"email": user.email, "password": DEFAULT_PASSWORD})

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "ACCOUNT_DISABLED"


async def test_login_locks_account_after_repeated_failures(
    client: AsyncClient, user_factory: UserFactory, outbox: InMemoryEmailSender
) -> None:
    user = await user_factory()
    for _ in range(10):
        await client.post(LOGIN, json={"email": user.email, "password": "wrong-password"})

    locked = await client.post(LOGIN, json={"email": user.email, "password": DEFAULT_PASSWORD})

    assert locked.status_code == 401
    assert outbox.outbox[-1].template == "account_locked"
    with time_machine.travel(timedelta(minutes=16)):
        assert (
            await client.post(LOGIN, json={"email": user.email, "password": DEFAULT_PASSWORD})
        ).status_code == 200


async def test_login_is_rate_limited_per_email(
    client: AsyncClient, user_factory: UserFactory, limiter: RateLimiter
) -> None:
    user = await user_factory()
    limiter.enabled = True

    statuses = [
        (await client.post(LOGIN, json={"email": user.email, "password": "bad"})).status_code
        for _ in range(6)
    ]

    assert statuses[-1] == 429
    assert statuses[:5] == [401] * 5


async def test_refresh_rotates_token(client: AsyncClient, user_factory: UserFactory) -> None:
    user = await user_factory()
    tokens = await _login(client, user.email)

    response = await client.post(REFRESH, json={"refresh_token": tokens["refresh_token"]})

    assert response.status_code == 200
    rotated = response.json()
    assert rotated["refresh_token"] != tokens["refresh_token"]
    assert (await client.get(ME, headers=_bearer(rotated))).status_code == 200


async def test_refresh_reuse_revokes_whole_session(
    client: AsyncClient, user_factory: UserFactory
) -> None:
    user = await user_factory()
    tokens = await _login(client, user.email)
    rotated = (await client.post(REFRESH, json={"refresh_token": tokens["refresh_token"]})).json()

    reuse = await client.post(REFRESH, json={"refresh_token": tokens["refresh_token"]})

    assert reuse.status_code == 401
    assert reuse.json()["error"]["code"] == "REFRESH_TOKEN_REUSED"
    after = await client.post(REFRESH, json={"refresh_token": rotated["refresh_token"]})
    assert after.status_code == 401
    assert (await client.get(ME, headers=_bearer(rotated))).status_code == 401


async def test_refresh_with_expired_token_fails(
    client: AsyncClient, user_factory: UserFactory
) -> None:
    user = await user_factory()
    tokens = await _login(client, user.email)

    with time_machine.travel(timedelta(days=31)):
        response = await client.post(REFRESH, json={"refresh_token": tokens["refresh_token"]})

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "TOKEN_EXPIRED"


async def test_refresh_without_token_is_unauthenticated(client: AsyncClient) -> None:
    response = await client.post(REFRESH)

    assert response.status_code == 401


async def test_web_client_gets_refresh_cookie_and_can_refresh_from_origin(
    client: AsyncClient, user_factory: UserFactory
) -> None:
    user = await user_factory()
    login = await client.post(
        LOGIN,
        json={"email": user.email, "password": DEFAULT_PASSWORD},
        headers={"X-Client": "web"},
    )
    cookie = login.cookies.get(REFRESH_COOKIE)

    assert login.json()["refresh_token"] is None
    assert cookie
    assert "httponly" in login.headers["set-cookie"].lower()
    cookie_header = f"{REFRESH_COOKIE}={cookie}"
    bad_origin = await client.post(
        REFRESH,
        headers={"Cookie": cookie_header, "Origin": "https://evil.example.com", "X-Client": "web"},
    )
    good_origin = await client.post(
        REFRESH,
        headers={"Cookie": cookie_header, "Origin": "https://app.example.com", "X-Client": "web"},
    )
    assert bad_origin.status_code == 403
    assert good_origin.status_code == 200
    assert good_origin.cookies.get(REFRESH_COOKIE) not in (None, cookie)


async def test_logout_revokes_current_session(
    client: AsyncClient, user_factory: UserFactory
) -> None:
    user = await user_factory()
    tokens = await _login(client, user.email)

    response = await client.post("/api/v1/auth/logout", headers=_bearer(tokens))

    assert response.status_code == 204
    assert (await client.get(ME, headers=_bearer(tokens))).status_code == 401
    refresh = await client.post(REFRESH, json={"refresh_token": tokens["refresh_token"]})
    assert refresh.json()["error"]["code"] == "INVALID_REFRESH_TOKEN"


async def test_logout_all_revokes_every_session(
    client: AsyncClient, user_factory: UserFactory
) -> None:
    user = await user_factory()
    first = await _login(client, user.email)
    second = await _login(client, user.email)

    await client.post("/api/v1/auth/logout-all", headers=_bearer(first))

    assert (await client.get(ME, headers=_bearer(second))).status_code == 401


async def test_list_and_revoke_sessions(client: AsyncClient, user_factory: UserFactory) -> None:
    user = await user_factory()
    first = await _login(client, user.email)
    second = await _login(client, user.email)

    sessions = (await client.get(SESSIONS, headers=_bearer(first))).json()
    other = next(s for s in sessions if not s["current"])
    revoke = await client.delete(f"{SESSIONS}/{other['id']}", headers=_bearer(first))

    assert len(sessions) == 2
    assert revoke.status_code == 204
    assert (await client.get(ME, headers=_bearer(second))).status_code == 401
    assert (await client.get(ME, headers=_bearer(first))).status_code == 200


async def test_cannot_revoke_another_users_session(
    client: AsyncClient, user_factory: UserFactory, auth_headers: AuthHeaders
) -> None:
    victim = await user_factory()
    victim_tokens = await _login(client, victim.email)
    victim_session = (await client.get(SESSIONS, headers=_bearer(victim_tokens))).json()[0]["id"]
    attacker = await auth_headers()

    response = await client.delete(f"{SESSIONS}/{victim_session}", headers=attacker)

    assert response.status_code == 404
    assert (await client.get(ME, headers=_bearer(victim_tokens))).status_code == 200


async def test_jwks_exposes_public_signing_key(client: AsyncClient) -> None:
    response = await client.get("/.well-known/jwks.json")

    key = response.json()["keys"][0]
    assert key["kty"] == "EC"
    assert key["alg"] == "ES256"
    assert "d" not in key
