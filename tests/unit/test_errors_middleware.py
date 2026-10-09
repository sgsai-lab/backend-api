from typing import Any

import pytest
from fastapi import APIRouter, FastAPI
from httpx import ASGITransport, AsyncClient

from app.core.errors import (
    ConflictError,
    ForbiddenError,
    NotFoundError,
    RateLimitedError,
    ValidationFailedError,
)
from app.main import create_app

_router = APIRouter()


@_router.get("/boom/{kind}")
async def boom(kind: str) -> None:
    errors: dict[str, Exception] = {
        "conflict": ConflictError("Already exists"),
        "forbidden": ForbiddenError("Nope", code="CUSTOM_CODE"),
        "notfound": NotFoundError("Missing"),
        "ratelimit": RateLimitedError(7),
        "validation": ValidationFailedError("body.x", "Bad x"),
        "crash": RuntimeError("secret internal detail"),
    }
    raise errors[kind]


@_router.post("/echo")
async def echo(payload: dict[str, Any]) -> dict[str, Any]:
    return payload


@pytest.fixture
def app() -> FastAPI:
    application = create_app()
    application.include_router(_router)
    return application


@pytest.fixture
async def client(app: FastAPI) -> Any:
    transport = ASGITransport(app=app, raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


@pytest.mark.parametrize(
    ("kind", "status", "code"),
    [
        ("conflict", 409, "CONFLICT"),
        ("forbidden", 403, "CUSTOM_CODE"),
        ("notfound", 404, "RESOURCE_NOT_FOUND"),
        ("ratelimit", 429, "RATE_LIMITED"),
        ("validation", 422, "VALIDATION_ERROR"),
    ],
)
async def test_app_errors_map_to_envelope(
    client: AsyncClient, kind: str, status: int, code: str
) -> None:
    response = await client.get(f"/boom/{kind}")

    assert response.status_code == status
    assert response.json()["error"]["code"] == code
    assert response.json()["error"]["requestId"] == response.headers["X-Request-ID"]


async def test_rate_limited_sets_retry_after(client: AsyncClient) -> None:
    response = await client.get("/boom/ratelimit")

    assert response.headers["Retry-After"] == "7"


async def test_unhandled_error_hides_internal_detail(client: AsyncClient) -> None:
    response = await client.get("/boom/crash")

    assert response.status_code == 500
    assert response.json()["error"]["code"] == "INTERNAL_ERROR"
    assert "secret internal detail" not in response.text


async def test_method_not_allowed_uses_envelope(client: AsyncClient) -> None:
    response = await client.delete("/healthz")

    assert response.status_code == 405
    assert response.json()["error"]["code"] == "METHOD_NOT_ALLOWED"


async def test_security_headers_are_set(client: AsyncClient) -> None:
    response = await client.get("/healthz")

    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert response.headers["X-Frame-Options"] == "DENY"
    assert "max-age" in response.headers["Strict-Transport-Security"]
    assert "Cache-Control" not in response.headers


async def test_body_larger_than_limit_is_rejected(client: AsyncClient) -> None:
    response = await client.post(
        "/echo",
        content=b"{" + b" " * 1_100_000 + b"}",
        headers={"Content-Type": "application/json"},
    )

    assert response.status_code == 413
    assert response.json()["error"]["code"] == "PAYLOAD_TOO_LARGE"


async def test_streamed_body_larger_than_limit_is_rejected(client: AsyncClient) -> None:
    async def chunks() -> Any:
        for _ in range(20):
            yield b" " * 100_000

    response = await client.post(
        "/echo", content=chunks(), headers={"Content-Type": "application/json"}
    )

    assert response.status_code == 413


async def test_small_body_passes_size_limit(client: AsyncClient) -> None:
    response = await client.post("/echo", json={"a": 1})

    assert response.status_code == 200
    assert response.json() == {"a": 1}
