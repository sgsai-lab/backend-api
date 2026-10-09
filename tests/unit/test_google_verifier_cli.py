import time
from typing import Any

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from jwt.algorithms import RSAAlgorithm

from app import cli
from app.core.errors import AppError, UnauthenticatedError
from app.modules.auth import google_verifier as gv

_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
_JWKS = {"keys": [{**RSAAlgorithm.to_jwk(_KEY.public_key(), as_dict=True), "kid": "k1"}]}


def _token(kid: str = "k1", **overrides: Any) -> str:
    now = int(time.time())
    claims = {
        "iss": "accounts.google.com",
        "aud": "cid",
        "sub": "s1",
        "email": "a@example.com",
        "email_verified": True,
        "iat": now,
        "exp": now + 600,
        **overrides,
    }
    return jwt.encode(claims, _KEY, algorithm="RS256", headers={"kid": kid})


async def test_verify_returns_identity() -> None:
    identity = await gv.GoogleTokenVerifier(["cid"], jwks=_JWKS).verify(_token(), None)

    assert identity.subject == "s1"
    assert identity.email == "a@example.com"


@pytest.mark.parametrize(
    "token",
    [_token(kid="unknown"), _token(iss="evil.example.com"), _token(aud="other"), "garbage"],
)
async def test_verify_rejects_invalid_tokens(token: str) -> None:
    with pytest.raises(UnauthenticatedError):
        await gv.GoogleTokenVerifier(["cid"], jwks=_JWKS).verify(token, None)


async def test_verify_requires_configuration() -> None:
    with pytest.raises(AppError) as exc:
        await gv.GoogleTokenVerifier([]).verify(_token(), None)

    assert exc.value.code == "GOOGLE_SIGNIN_UNAVAILABLE"


async def test_keys_are_fetched_and_cached(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url)
        return httpx.Response(200, json=_JWKS, headers={"Cache-Control": "public, max-age=120"})

    real_client = httpx.AsyncClient
    monkeypatch.setattr(
        "app.modules.auth.google_verifier.httpx.AsyncClient",
        lambda **kw: real_client(transport=httpx.MockTransport(handler), **kw),
    )
    verifier = gv.GoogleTokenVerifier(["cid"])

    await verifier.verify(_token(), None)
    await verifier.verify(_token(), None)

    assert len(calls) == 1


async def test_key_fetch_failure_is_unauthenticated(monkeypatch: pytest.MonkeyPatch) -> None:
    real_client = httpx.AsyncClient
    monkeypatch.setattr(
        "app.modules.auth.google_verifier.httpx.AsyncClient",
        lambda **kw: real_client(
            transport=httpx.MockTransport(lambda _: httpx.Response(500)), **kw
        ),
    )

    with pytest.raises(UnauthenticatedError):
        await gv.GoogleTokenVerifier(["cid"]).verify(_token(), None)


@pytest.mark.parametrize(
    ("header", "expected"), [("public, max-age=300", 300), ("no-cache", 3600), ("", 3600)]
)
def test_max_age_parsing(header: str, expected: int) -> None:
    assert gv._max_age(header) == expected


def test_cli_create_admin(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    created: dict[str, str] = {}

    async def fake_create_admin(email: str, full_name: str, password: str) -> str:
        created.update(email=email, name=full_name)
        return "created"

    monkeypatch.setattr("app.cli.getpass.getpass", lambda _: "Quiet-Harbor-Lamp-81")
    monkeypatch.setattr(cli, "create_admin", fake_create_admin)

    exit_code = cli.main(["create-admin", "--email", "root@example.com", "--name", "Root"])

    assert exit_code == 0
    assert created == {"email": "root@example.com", "name": "Root"}
    assert "Administrator created" in capsys.readouterr().out


def test_cli_rejects_weak_password(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.cli.getpass.getpass", lambda _: "short")

    assert cli.main(["create-admin", "--email", "root@example.com"]) == 1
