from datetime import timedelta
from urllib.parse import parse_qs, urlparse

import time_machine
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.email import InMemoryEmailSender
from app.core.rate_limit import RateLimiter
from app.modules.users.models import User
from tests.integration.conftest import UserFactory

SIGNUP = "/api/v1/auth/signup"
VERIFY = "/api/v1/auth/verify-email"
RESEND = "/api/v1/auth/verify-email/resend"
STRONG_PASSWORD = "Sunlit-Orchard-42-Kite"


def _signup_body(**overrides: object) -> dict[str, object]:
    return {
        "email": "new.user@example.com",
        "password": STRONG_PASSWORD,
        "full_name": "New User",
        "accept_terms": True,
        **overrides,
    }


def _token_from(outbox: InMemoryEmailSender) -> str:
    link = next(line for line in outbox.outbox[-1].text.splitlines() if "token=" in line)
    return parse_qs(urlparse(link.strip()).query)["token"][0]


async def test_signup_creates_unverified_user_and_sends_email(
    client: AsyncClient, outbox: InMemoryEmailSender
) -> None:
    response = await client.post(SIGNUP, json=_signup_body())

    assert response.status_code == 201
    assert response.json()["email_verified"] is False
    assert outbox.outbox[-1].template == "verify_email"
    assert outbox.outbox[-1].to == "new.user@example.com"
    assert "https://app.example.com/verify-email?token=" in outbox.outbox[-1].text


async def test_signup_duplicate_email_is_indistinguishable(
    client: AsyncClient,
    outbox: InMemoryEmailSender,
    user_factory: UserFactory,
    session: AsyncSession,
) -> None:
    existing = await user_factory(email="taken@example.com")

    response = await client.post(SIGNUP, json=_signup_body(email="taken@example.com"))

    assert response.status_code == 201
    assert response.json()["id"] != str(existing.id)
    assert outbox.outbox[-1].template == "signup_existing"
    count = await session.scalar(select(func.count()).where(User.email == "taken@example.com"))
    assert count == 1


async def test_signup_rejects_common_password(client: AsyncClient) -> None:
    response = await client.post(SIGNUP, json=_signup_body(password="1234567890"))

    assert response.status_code == 422
    assert response.json()["error"]["details"][0]["field"] == "body.password"


async def test_signup_rejects_password_containing_email(client: AsyncClient) -> None:
    response = await client.post(
        SIGNUP, json=_signup_body(email="kingfisher@example.com", password="kingfisher-2026!")
    )

    assert response.status_code == 422


async def test_signup_requires_terms_and_forbids_extra_fields(client: AsyncClient) -> None:
    no_terms = await client.post(SIGNUP, json=_signup_body(accept_terms=False))
    extra = await client.post(SIGNUP, json=_signup_body(role="admin"))

    assert no_terms.status_code == 422
    assert extra.status_code == 422


async def test_validation_error_does_not_echo_password(client: AsyncClient) -> None:
    response = await client.post(SIGNUP, json=_signup_body(email="not-an-email"))

    assert STRONG_PASSWORD not in response.text


async def test_verify_email_marks_user_verified_once(
    client: AsyncClient, outbox: InMemoryEmailSender, session: AsyncSession
) -> None:
    await client.post(SIGNUP, json=_signup_body())
    token = _token_from(outbox)

    first = await client.post(VERIFY, json={"token": token})
    second = await client.post(VERIFY, json={"token": token})

    assert first.status_code == 204
    assert second.status_code == 400
    assert second.json()["error"]["code"] == "INVALID_TOKEN"
    user = await session.scalar(select(User).where(User.email == "new.user@example.com"))
    assert user is not None
    assert user.email_verified_at is not None


async def test_verify_email_expired_token_is_rejected(
    client: AsyncClient, outbox: InMemoryEmailSender
) -> None:
    await client.post(SIGNUP, json=_signup_body())
    token = _token_from(outbox)

    with time_machine.travel(timedelta(hours=25)):
        response = await client.post(VERIFY, json={"token": token})

    assert response.status_code == 400


async def test_resend_invalidates_previous_token(
    client: AsyncClient, outbox: InMemoryEmailSender
) -> None:
    await client.post(SIGNUP, json=_signup_body())
    old_token = _token_from(outbox)

    resend = await client.post(RESEND, json={"email": "new.user@example.com"})
    new_token = _token_from(outbox)

    assert resend.status_code == 202
    assert (await client.post(VERIFY, json={"token": old_token})).status_code == 400
    assert (await client.post(VERIFY, json={"token": new_token})).status_code == 204


async def test_resend_for_unknown_email_returns_202_without_email(
    client: AsyncClient, outbox: InMemoryEmailSender
) -> None:
    response = await client.post(RESEND, json={"email": "nobody@example.com"})

    assert response.status_code == 202
    assert outbox.outbox == []


async def test_resend_is_rate_limited_per_email(client: AsyncClient, limiter: RateLimiter) -> None:
    limiter.enabled = True
    body = {"email": "someone@example.com"}

    statuses = [(await client.post(RESEND, json=body)).status_code for _ in range(4)]

    assert statuses == [202, 202, 202, 429]
