# Integration fixtures (reference implementation)

`tests/integration/conftest.py` — adapt names once API-06 lands (`User`, `issue_access_token`).

```python
from collections.abc import AsyncIterator, Awaitable, Callable
import uuid

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncSession, create_async_engine

from app.core.config import get_settings
from app.core.security import issue_access_token
from app.db.session import get_session
from app.main import create_app
from app.modules.users.models import User


@pytest.fixture(scope="session")
async def connection() -> AsyncIterator[AsyncConnection]:
    engine = create_async_engine(str(get_settings().database_url))
    async with engine.connect() as conn:
        yield conn
    await engine.dispose()


@pytest.fixture
async def session(connection: AsyncConnection) -> AsyncIterator[AsyncSession]:
    # Each test runs in an outer transaction that is rolled back; service commits become savepoints.
    trans = await connection.begin()
    async with AsyncSession(bind=connection, join_transaction_mode="create_savepoint",
                            expire_on_commit=False) as s:
        yield s
    await trans.rollback()


@pytest.fixture
def app(session: AsyncSession) -> FastAPI:
    app = create_app()
    app.dependency_overrides[get_session] = lambda: session
    return app


@pytest.fixture
async def client(app: FastAPI) -> AsyncIterator[AsyncClient]:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c


@pytest.fixture
def user_factory(session: AsyncSession) -> Callable[..., Awaitable[User]]:
    async def make(**kw: object) -> User:
        user = User(email=f"{uuid.uuid4().hex[:8]}@example.test", full_name="Test User",
                    email_verified_at=None, **kw)
        session.add(user)
        await session.flush()
        return user
    return make


@pytest.fixture
def auth_headers(user_factory: Callable[..., Awaitable[User]]) -> Callable[..., Awaitable[dict[str, str]]]:
    async def make(user: User | None = None, **kw: object) -> dict[str, str]:
        user = user or await user_factory(**kw)
        return {"Authorization": f"Bearer {issue_access_token(user, amr=['pwd'])}"}
    return make
```

Notes

- The DB must be migrated (`make migrate`) before tests; CI runs `alembic upgrade head` first.
- Override the email sender dependency with `InMemoryEmailSender` and expose it as a fixture to assert sent mail.
