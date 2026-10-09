from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.auth.models import OAuthAccount
from app.modules.users.models import User
from tests.integration.conftest import AuthHeaders, GoogleTokenFactory, UserFactory

GOOGLE = "/api/v1/auth/google"
LINK = "/api/v1/auth/google/link"


async def test_google_sign_up_creates_verified_user(
    client: AsyncClient, google_token: GoogleTokenFactory, session: AsyncSession
) -> None:
    response = await client.post(GOOGLE, json={"id_token": google_token()})

    assert response.status_code == 201
    assert response.json()["access_token"]
    user = await session.scalar(select(User).where(User.email == "g.user@example.com"))
    assert user is not None
    assert user.email_verified_at is not None
    assert user.password_hash is None


async def test_google_returning_user_signs_in_with_200(
    client: AsyncClient, google_token: GoogleTokenFactory
) -> None:
    await client.post(GOOGLE, json={"id_token": google_token()})

    response = await client.post(GOOGLE, json={"id_token": google_token()})

    assert response.status_code == 200


async def test_google_links_to_existing_verified_account(
    client: AsyncClient,
    google_token: GoogleTokenFactory,
    user_factory: UserFactory,
    session: AsyncSession,
) -> None:
    user = await user_factory(email="g.user@example.com")

    response = await client.post(GOOGLE, json={"id_token": google_token()})

    assert response.status_code == 200
    account = await session.scalar(select(OAuthAccount).where(OAuthAccount.user_id == user.id))
    assert account is not None


async def test_google_refuses_to_link_unverified_local_account(
    client: AsyncClient, google_token: GoogleTokenFactory, user_factory: UserFactory
) -> None:
    await user_factory(email="g.user@example.com", verified=False)

    response = await client.post(GOOGLE, json={"id_token": google_token()})

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "ACCOUNT_LINK_REQUIRED"


async def test_google_rejects_wrong_audience(
    client: AsyncClient, google_token: GoogleTokenFactory
) -> None:
    response = await client.post(GOOGLE, json={"id_token": google_token(aud="other-app")})

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "INVALID_GOOGLE_TOKEN"


async def test_google_rejects_expired_token(
    client: AsyncClient, google_token: GoogleTokenFactory
) -> None:
    response = await client.post(GOOGLE, json={"id_token": google_token(exp=1, iat=0)})

    assert response.status_code == 401


async def test_google_rejects_unverified_email(
    client: AsyncClient, google_token: GoogleTokenFactory
) -> None:
    response = await client.post(GOOGLE, json={"id_token": google_token(email_verified=False)})

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "GOOGLE_EMAIL_NOT_VERIFIED"


async def test_google_nonce_must_match(
    client: AsyncClient, google_token: GoogleTokenFactory
) -> None:
    token = google_token(nonce="expected")

    bad = await client.post(GOOGLE, json={"id_token": token, "nonce": "other"})
    good = await client.post(GOOGLE, json={"id_token": token, "nonce": "expected"})

    assert bad.status_code == 401
    assert good.status_code == 201


async def test_link_and_unlink_google(
    client: AsyncClient, google_token: GoogleTokenFactory, auth_headers: AuthHeaders
) -> None:
    headers = await auth_headers()

    link = await client.post(LINK, json={"id_token": google_token(sub="sub-link")}, headers=headers)
    again = await client.post(
        LINK, json={"id_token": google_token(sub="sub-link")}, headers=headers
    )
    other = await client.post(LINK, json={"id_token": google_token(sub="sub-2")}, headers=headers)
    unlink = await client.delete(LINK, headers=headers)
    unlink_again = await client.delete(LINK, headers=headers)

    assert link.status_code == 204
    assert again.status_code == 204
    assert other.json()["error"]["code"] == "GOOGLE_ALREADY_LINKED"
    assert unlink.status_code == 204
    assert unlink_again.status_code == 404


async def test_link_google_account_owned_by_someone_else(
    client: AsyncClient, google_token: GoogleTokenFactory, auth_headers: AuthHeaders
) -> None:
    await client.post(GOOGLE, json={"id_token": google_token(sub="taken-sub")})
    headers = await auth_headers()

    response = await client.post(
        LINK, json={"id_token": google_token(sub="taken-sub")}, headers=headers
    )

    assert response.json()["error"]["code"] == "GOOGLE_ACCOUNT_IN_USE"


async def test_cannot_unlink_last_sign_in_method(
    client: AsyncClient, google_token: GoogleTokenFactory
) -> None:
    tokens = (await client.post(GOOGLE, json={"id_token": google_token()})).json()

    response = await client.delete(
        LINK, headers={"Authorization": f"Bearer {tokens['access_token']}"}
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "LAST_SIGN_IN_METHOD"
