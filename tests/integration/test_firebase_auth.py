from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.auth.models import OAuthAccount
from app.modules.users.models import User
from tests.integration.conftest import FakeFirebaseVerifier, UserFactory

FIREBASE_SIGN_IN = "/api/v1/auth/firebase"
FIREBASE_TOKEN = "firebase-test-id-token-000000000000"


async def test_firebase_sign_in_provisions_verified_user(
    client: AsyncClient,
    firebase_verifier: FakeFirebaseVerifier,
    session: AsyncSession,
) -> None:
    response = await client.post(FIREBASE_SIGN_IN, json={"id_token": FIREBASE_TOKEN})

    assert response.status_code == 200
    assert response.json()["email"] == "firebase.user@example.com"
    user = await session.scalar(select(User).where(User.email == "firebase.user@example.com"))
    assert user is not None
    assert user.email_verified_at is not None
    account = await session.scalar(
        select(OAuthAccount).where(
            OAuthAccount.provider == "firebase",
            OAuthAccount.provider_subject == "firebase-uid-1",
        )
    )
    assert account is not None
    assert firebase_verifier.revoked_uids == []


async def test_firebase_bearer_token_authenticates_linked_user(
    client: AsyncClient,
) -> None:
    await client.post(FIREBASE_SIGN_IN, json={"id_token": FIREBASE_TOKEN})

    response = await client.get(
        "/api/v1/users/me",
        headers={"Authorization": f"Bearer {FIREBASE_TOKEN}"},
    )

    assert response.status_code == 200
    assert response.json()["email"] == "firebase.user@example.com"


async def test_firebase_bearer_token_requires_bootstrapped_account(
    client: AsyncClient,
    firebase_verifier: FakeFirebaseVerifier,
) -> None:
    firebase_verifier.identities["unlinked-firebase-id-token-000000"] = (
        firebase_verifier.identities[FIREBASE_TOKEN]
    )

    response = await client.get(
        "/api/v1/users/me",
        headers={"Authorization": "Bearer unlinked-firebase-id-token-000000"},
    )

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "FIREBASE_ACCOUNT_NOT_LINKED"


async def test_firebase_sign_in_refuses_unverified_local_account_link(
    client: AsyncClient,
    user_factory: UserFactory,
) -> None:
    await user_factory(email="firebase.user@example.com", verified=False)

    response = await client.post(FIREBASE_SIGN_IN, json={"id_token": FIREBASE_TOKEN})

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "ACCOUNT_LINK_REQUIRED"


async def test_firebase_logout_revokes_refresh_tokens_for_the_user(
    client: AsyncClient,
    firebase_verifier: FakeFirebaseVerifier,
) -> None:
    await client.post(FIREBASE_SIGN_IN, json={"id_token": FIREBASE_TOKEN})

    response = await client.post(
        "/api/v1/auth/logout",
        headers={"Authorization": f"Bearer {FIREBASE_TOKEN}"},
    )

    assert response.status_code == 204
    assert firebase_verifier.revoked_uids == ["firebase-uid-1"]

    profile = await client.get(
        "/api/v1/users/me",
        headers={"Authorization": f"Bearer {FIREBASE_TOKEN}"},
    )

    assert profile.status_code == 401
