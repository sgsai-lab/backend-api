import os
from collections.abc import AsyncIterator

# Must be set before the app (and its cached settings) is imported.
os.environ["ENVIRONMENT"] = "test"
os.environ["LOG_JSON"] = "false"
os.environ["EMAIL_BACKEND"] = "memory"
os.environ["RATE_LIMIT_ENABLED"] = "false"
os.environ["ADMIN_REQUIRE_MFA"] = "true"
os.environ["GOOGLE_OAUTH_CLIENT_IDS"] = '["test-client-id"]'
os.environ["FRONTEND_BASE_URL"] = "https://app.example.com"
os.environ["CORS_ALLOW_ORIGINS"] = '["https://app.example.com"]'
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://app:app@127.0.0.1:5433/app")

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.main import create_app


@pytest.fixture
def app() -> FastAPI:
    return create_app()


@pytest.fixture
async def client(app: FastAPI) -> AsyncIterator[AsyncClient]:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c
