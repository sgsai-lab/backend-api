import asyncio
import time
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from datetime import UTC, datetime
from typing import Any, Protocol

import jwt
import pyotp
import pytest
from alembic import command
from alembic.config import Config
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import FastAPI
from jwt.algorithms import RSAAlgorithm
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

from app.core.config import get_settings
from app.core.email import InMemoryEmailSender, get_email_sender
from app.core.passwords import hash_password
from app.core.rate_limit import RateLimiter, get_rate_limiter
from app.db.session import get_session
from app.main import create_app
from app.modules.auth.google_verifier import GoogleTokenVerifier, get_google_verifier
from app.modules.auth.services.sessions import ClientContext, start_session
from app.modules.users.models import User, UserRole

DEFAULT_PASSWORD = "Correct-Horse-Battery-9"
GOOGLE_CLIENT_ID = "test-client-id"
GOOGLE_KID = "test-kid"


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    for item in items:
        if "/integration/" in str(item.fspath):
            item.add_marker(pytest.mark.integration)


def _upgrade_head() -> None:
    command.upgrade(Config("alembic.ini"), "head")


@pytest.fixture(scope="session")
async def engine() -> AsyncIterator[AsyncEngine]:
    await asyncio.to_thread(_upgrade_head)
    engine = create_async_engine(str(get_settings().database_url), poolclass=NullPool)
    yield engine
    await engine.dispose()


@pytest.fixture
async def session(engine: AsyncEngine) -> AsyncIterator[AsyncSession]:
    # Each test runs inside a transaction that is rolled back; service commits become savepoints.
    async with engine.connect() as connection:
        transaction = await connection.begin()
        db = AsyncSession(
            bind=connection, join_transaction_mode="create_savepoint", expire_on_commit=False
        )
        yield db
        await db.close()
        await transaction.rollback()


@pytest.fixture
def outbox() -> InMemoryEmailSender:
    return InMemoryEmailSender()


@pytest.fixture
def limiter() -> RateLimiter:
    return RateLimiter(enabled=False)


@pytest.fixture(scope="session")
def google_key() -> rsa.RSAPrivateKey:
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


@pytest.fixture
def google_verifier(google_key: rsa.RSAPrivateKey) -> GoogleTokenVerifier:
    jwk = RSAAlgorithm.to_jwk(google_key.public_key(), as_dict=True)
    jwks = {"keys": [{**jwk, "kid": GOOGLE_KID, "alg": "RS256", "use": "sig"}]}
    return GoogleTokenVerifier([GOOGLE_CLIENT_ID], jwks=jwks)


class GoogleTokenFactory(Protocol):
    def __call__(self, **overrides: Any) -> str: ...


@pytest.fixture
def google_token(google_key: rsa.RSAPrivateKey) -> GoogleTokenFactory:
    def make(**overrides: Any) -> str:
        now = int(time.time())
        claims = {
            "iss": "https://accounts.google.com",
            "aud": GOOGLE_CLIENT_ID,
            "sub": "google-sub-1",
            "email": "g.user@example.com",
            "email_verified": True,
            "name": "Google User",
            "picture": "https://example.com/avatar.png",
            "iat": now,
            "exp": now + 3600,
            **overrides,
        }
        return jwt.encode(claims, google_key, algorithm="RS256", headers={"kid": GOOGLE_KID})

    return make


@pytest.fixture
def app(
    session: AsyncSession,
    outbox: InMemoryEmailSender,
    limiter: RateLimiter,
    google_verifier: GoogleTokenVerifier,
) -> FastAPI:
    async def _session() -> AsyncIterator[AsyncSession]:
        yield session

    application = create_app()
    application.dependency_overrides[get_session] = _session
    application.dependency_overrides[get_email_sender] = lambda: outbox
    application.dependency_overrides[get_rate_limiter] = lambda: limiter
    application.dependency_overrides[get_google_verifier] = lambda: google_verifier
    return application


UserFactory = Callable[..., Awaitable[User]]
AuthHeaders = Callable[..., Awaitable[dict[str, str]]]


@pytest.fixture
def user_factory(session: AsyncSession) -> UserFactory:
    async def make(
        *,
        email: str | None = None,
        password: str | None = DEFAULT_PASSWORD,
        verified: bool = True,
        role: UserRole = UserRole.USER,
        full_name: str = "Test User",
    ) -> User:
        user = User(
            email=email or f"user-{uuid.uuid4().hex[:10]}@example.com",
            full_name=full_name,
            password_hash=await hash_password(password) if password else None,
            email_verified_at=datetime.now(UTC) if verified else None,
            role=role,
        )
        session.add(user)
        await session.flush()
        return user

    return make


@pytest.fixture
def auth_headers(session: AsyncSession, user_factory: UserFactory) -> AuthHeaders:
    async def make(
        user: User | None = None, amr: tuple[str, ...] = ("pwd",), **kw: Any
    ) -> dict[str, str]:
        user = user or await user_factory(**kw)
        tokens = start_session(session, user, list(amr), ClientContext("127.0.0.1", "pytest"))
        await session.flush()
        return {"Authorization": f"Bearer {tokens.access_token}"}

    return make


@pytest.fixture
def admin_headers(auth_headers: AuthHeaders) -> Callable[[], Awaitable[dict[str, str]]]:
    async def make() -> dict[str, str]:
        return await auth_headers(role=UserRole.ADMIN, amr=("pwd", "mfa"))

    return make


def totp_code(secret: str, offset_steps: int = 0) -> str:
    return pyotp.TOTP(secret).at(int(time.time()) + offset_steps * 30)
