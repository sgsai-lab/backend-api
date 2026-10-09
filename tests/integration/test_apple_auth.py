from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.auth.models import OAuthAccount
from app.modules.users.models import User
from tests.integration.conftest import GoogleTokenFactory, UserFactory

APPLE = "/api/v1/auth/apple"
EMAIL = "a.user@privaterelay.appleid.com"


async def test_apple_sign_up_creates_verified_user_with_given_name(
    client: AsyncClient, apple_token: GoogleTokenFactory, session: AsyncSession
) -> None:
    response = await client.post(APPLE, json={"id_token": apple_token(), "full_name": "Ada Apple"})

    assert response.status_code == 201
    assert response.json()["access_token"]
    user = await session.scalar(select(User).where(User.email == EMAIL))
    assert user is not None
    assert user.full_name == "Ada Apple"
    assert user.email_verified_at is not None


async def test_apple_returning_user_signs_in_with_200(
    client: AsyncClient, apple_token: GoogleTokenFactory
) -> None:
    await client.post(APPLE, json={"id_token": apple_token()})

    response = await client.post(APPLE, json={"id_token": apple_token()})

    assert response.status_code == 200


async def test_apple_links_to_existing_verified_account(
    client: AsyncClient,
    apple_token: GoogleTokenFactory,
    user_factory: UserFactory,
    session: AsyncSession,
) -> None:
    user = await user_factory(email=EMAIL)

    response = await client.post(APPLE, json={"id_token": apple_token()})

    assert response.status_code == 200
    account = await session.scalar(select(OAuthAccount).where(OAuthAccount.user_id == user.id))
    assert account is not None
    assert account.provider == "apple"


async def test_apple_refuses_to_link_unverified_local_account(
    client: AsyncClient, apple_token: GoogleTokenFactory, user_factory: UserFactory
) -> None:
    await user_factory(email=EMAIL, verified=False)

    response = await client.post(APPLE, json={"id_token": apple_token()})

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "ACCOUNT_LINK_REQUIRED"


async def test_apple_rejects_google_issuer(
    client: AsyncClient, apple_token: GoogleTokenFactory
) -> None:
    response = await client.post(
        APPLE, json={"id_token": apple_token(iss="https://accounts.google.com")}
    )

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "INVALID_APPLE_TOKEN"


async def test_apple_rejects_wrong_audience(
    client: AsyncClient, apple_token: GoogleTokenFactory
) -> None:
    response = await client.post(APPLE, json={"id_token": apple_token(aud="other")})

    assert response.status_code == 401


async def test_apple_rejects_nonce_mismatch(
    client: AsyncClient, apple_token: GoogleTokenFactory
) -> None:
    response = await client.post(
        APPLE, json={"id_token": apple_token(nonce="expected"), "nonce": "different"}
    )

    assert response.status_code == 401


async def test_apple_rejects_unverified_email(
    client: AsyncClient, apple_token: GoogleTokenFactory
) -> None:
    response = await client.post(APPLE, json={"id_token": apple_token(email_verified="false")})

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "APPLE_EMAIL_NOT_VERIFIED"


async def test_apple_token_is_not_accepted_by_google_endpoint(
    client: AsyncClient, apple_token: GoogleTokenFactory
) -> None:
    response = await client.post("/api/v1/auth/google", json={"id_token": apple_token()})

    assert response.status_code == 401
