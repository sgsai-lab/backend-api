from datetime import timedelta

import time_machine
from httpx import AsyncClient

from app.core.email import InMemoryEmailSender
from tests.integration.conftest import (
    DEFAULT_PASSWORD,
    AuthHeaders,
    GoogleTokenFactory,
    UserFactory,
    totp_code,
)

LOGIN = "/api/v1/auth/login"
MFA = "/api/v1/auth/mfa"
SETUP = f"{MFA}/totp/setup"
CONFIRM = f"{MFA}/totp/confirm"
VERIFY = f"{MFA}/verify"
ME = "/api/v1/users/me"


async def _enable_mfa(client: AsyncClient, headers: dict[str, str]) -> tuple[str, list[str]]:
    secret = (await client.post(SETUP, headers=headers)).json()["secret"]
    confirm = await client.post(CONFIRM, json={"code": totp_code(secret)}, headers=headers)
    assert confirm.status_code == 200, confirm.text
    return secret, confirm.json()["recovery_codes"]


async def _mfa_token(client: AsyncClient, email: str) -> str:
    response = await client.post(LOGIN, json={"email": email, "password": DEFAULT_PASSWORD})
    body = response.json()
    assert body["mfa_required"] is True
    return str(body["mfa_token"])


async def test_setup_returns_otpauth_uri_and_is_idempotent(
    client: AsyncClient, auth_headers: AuthHeaders
) -> None:
    headers = await auth_headers()

    first = (await client.post(SETUP, headers=headers)).json()
    second = (await client.post(SETUP, headers=headers)).json()

    assert first["otpauth_uri"].startswith("otpauth://totp/")
    assert first["secret"] == second["secret"]


async def test_confirm_with_wrong_code_fails(
    client: AsyncClient, auth_headers: AuthHeaders
) -> None:
    headers = await auth_headers()
    await client.post(SETUP, headers=headers)

    response = await client.post(CONFIRM, json={"code": "000000"}, headers=headers)

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "INVALID_MFA_CODE"


async def test_confirm_without_setup_fails(client: AsyncClient, auth_headers: AuthHeaders) -> None:
    headers = await auth_headers()

    response = await client.post(CONFIRM, json={"code": "123456"}, headers=headers)

    assert response.json()["error"]["code"] == "MFA_SETUP_REQUIRED"


async def test_enable_mfa_then_login_requires_second_factor(
    client: AsyncClient,
    auth_headers: AuthHeaders,
    user_factory: UserFactory,
    outbox: InMemoryEmailSender,
) -> None:
    user = await user_factory()
    secret, codes = await _enable_mfa(client, await auth_headers(user))

    status = (await client.get(MFA, headers=await auth_headers(user))).json()
    mfa_token = await _mfa_token(client, user.email)
    with time_machine.travel(timedelta(seconds=30)):
        verify = await client.post(VERIFY, json={"mfa_token": mfa_token, "code": totp_code(secret)})
        token = verify.json()["access_token"]
        me = await client.get(ME, headers={"Authorization": f"Bearer {token}"})

    assert outbox.outbox[-1].template == "mfa_enabled"
    assert len(codes) == 10
    assert status == {
        "enabled": True,
        "methods": ["totp", "recovery_code"],
        "recovery_codes_remaining": 10,
    }
    assert verify.status_code == 200
    assert me.json()["mfa_enabled"] is True


async def test_mfa_code_cannot_be_replayed(
    client: AsyncClient, auth_headers: AuthHeaders, user_factory: UserFactory
) -> None:
    user = await user_factory()
    secret, _ = await _enable_mfa(client, await auth_headers(user))
    code = totp_code(secret)

    replay = await client.post(
        VERIFY, json={"mfa_token": await _mfa_token(client, user.email), "code": code}
    )

    assert replay.status_code == 400
    assert replay.json()["error"]["code"] == "INVALID_MFA_CODE"


async def test_recovery_code_is_single_use(
    client: AsyncClient, auth_headers: AuthHeaders, user_factory: UserFactory
) -> None:
    user = await user_factory()
    _, codes = await _enable_mfa(client, await auth_headers(user))

    first = await client.post(
        VERIFY, json={"mfa_token": await _mfa_token(client, user.email), "recovery_code": codes[0]}
    )
    second = await client.post(
        VERIFY,
        json={"mfa_token": await _mfa_token(client, user.email), "recovery_code": codes[0].lower()},
    )

    assert first.status_code == 200
    assert second.status_code == 400


async def test_mfa_challenge_locks_after_max_attempts(
    client: AsyncClient, auth_headers: AuthHeaders, user_factory: UserFactory
) -> None:
    user = await user_factory()
    secret, _ = await _enable_mfa(client, await auth_headers(user))
    mfa_token = await _mfa_token(client, user.email)
    for _ in range(5):
        await client.post(VERIFY, json={"mfa_token": mfa_token, "code": "000000"})

    with time_machine.travel(timedelta(seconds=30)):
        response = await client.post(
            VERIFY, json={"mfa_token": mfa_token, "code": totp_code(secret)}
        )

    assert response.json()["error"]["code"] == "INVALID_TOKEN"


async def test_verify_requires_exactly_one_factor(client: AsyncClient) -> None:
    response = await client.post(VERIFY, json={"mfa_token": "x" * 32})

    assert response.status_code == 422


async def test_google_login_also_requires_mfa(
    client: AsyncClient, google_token: GoogleTokenFactory
) -> None:
    tokens = (await client.post("/api/v1/auth/google", json={"id_token": google_token()})).json()
    await _enable_mfa(client, {"Authorization": f"Bearer {tokens['access_token']}"})

    response = await client.post("/api/v1/auth/google", json={"id_token": google_token()})

    assert response.json()["mfa_required"] is True


async def test_regenerate_recovery_codes(
    client: AsyncClient, auth_headers: AuthHeaders, user_factory: UserFactory
) -> None:
    user = await user_factory()
    headers = await auth_headers(user)
    secret, old_codes = await _enable_mfa(client, headers)

    with time_machine.travel(timedelta(seconds=30)):
        response = await client.post(
            f"{MFA}/recovery-codes", json={"code": totp_code(secret)}, headers=headers
        )

    new_codes = response.json()["recovery_codes"]
    assert response.status_code == 200
    assert set(new_codes).isdisjoint(old_codes)


async def test_disable_mfa_requires_password_and_code(
    client: AsyncClient,
    auth_headers: AuthHeaders,
    user_factory: UserFactory,
    outbox: InMemoryEmailSender,
) -> None:
    user = await user_factory()
    headers = await auth_headers(user)
    secret, _ = await _enable_mfa(client, headers)

    without_code = await client.request(
        "DELETE", f"{MFA}/totp", json={"password": DEFAULT_PASSWORD}, headers=headers
    )
    with time_machine.travel(timedelta(seconds=30)):
        disabled = await client.request(
            "DELETE",
            f"{MFA}/totp",
            json={"password": DEFAULT_PASSWORD, "code": totp_code(secret)},
            headers=headers,
        )

    assert without_code.status_code == 403
    assert disabled.status_code == 204
    assert outbox.outbox[-1].template == "mfa_disabled"
    login = await client.post(LOGIN, json={"email": user.email, "password": DEFAULT_PASSWORD})
    assert "access_token" in login.json()


async def test_setup_when_already_enabled_conflicts(
    client: AsyncClient, auth_headers: AuthHeaders
) -> None:
    headers = await auth_headers()
    await _enable_mfa(client, headers)

    response = await client.post(SETUP, headers=headers)

    assert response.json()["error"]["code"] == "MFA_ALREADY_ENABLED"


async def test_reset_password_requires_mfa_when_enabled(
    client: AsyncClient,
    auth_headers: AuthHeaders,
    user_factory: UserFactory,
    outbox: InMemoryEmailSender,
) -> None:
    from tests.integration.test_password import NEW_PASSWORD, _reset_token

    user = await user_factory()
    secret, _ = await _enable_mfa(client, await auth_headers(user))
    await client.post("/api/v1/auth/password/forgot", json={"email": user.email})
    token = _reset_token(outbox)
    reset = "/api/v1/auth/password/reset"

    missing = await client.post(reset, json={"token": token, "new_password": NEW_PASSWORD})
    wrong = await client.post(
        reset, json={"token": token, "new_password": NEW_PASSWORD, "mfa_code": "000000"}
    )
    with time_machine.travel(timedelta(seconds=30)):
        ok = await client.post(
            reset,
            json={"token": token, "new_password": NEW_PASSWORD, "mfa_code": totp_code(secret)},
        )

    assert missing.json()["error"]["code"] == "MFA_REQUIRED"
    assert wrong.json()["error"]["code"] == "INVALID_MFA_CODE"
    assert ok.status_code == 204
