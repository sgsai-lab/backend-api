import uuid
from datetime import UTC, datetime, timedelta

import jwt
import pytest
import time_machine
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec, rsa
from pydantic import SecretStr

from app.core import tokens
from app.core.config import get_settings
from app.core.errors import UnauthenticatedError


def _token() -> str:
    token, _ = tokens.issue_access_token(uuid.uuid4(), uuid.uuid4(), "user", ["pwd"])
    return token


def test_issue_and_decode_round_trip() -> None:
    user_id, session_id = uuid.uuid4(), uuid.uuid4()
    token, expires_in = tokens.issue_access_token(user_id, session_id, "admin", ["pwd", "mfa"])

    claims = tokens.decode_access_token(token)

    assert expires_in == 900
    assert claims.user_id == user_id
    assert claims.session_id == session_id
    assert claims.role == "admin"
    assert claims.amr == ("pwd", "mfa")


def test_expired_token_raises_token_expired() -> None:
    token = _token()

    with (
        time_machine.travel(datetime.now(UTC) + timedelta(minutes=16)),
        pytest.raises(UnauthenticatedError) as exc,
    ):
        tokens.decode_access_token(token)

    assert exc.value.code == "TOKEN_EXPIRED"


@pytest.mark.parametrize("mutation", ["garbage", "kid", "typ", "alg_none"])
def test_invalid_tokens_are_rejected(mutation: str) -> None:
    keys = tokens.get_signing_keys()
    claims = jwt.decode(_token(), options={"verify_signature": False})
    forged = {
        "garbage": "not-a-jwt",
        "kid": jwt.encode(claims, keys.private_key, algorithm="ES256", headers={"kid": "unknown"}),
        "typ": jwt.encode(
            {**claims, "typ": "refresh"},
            keys.private_key,
            algorithm="ES256",
            headers={"kid": keys.kid},
        ),
        "alg_none": jwt.encode(claims, "", algorithm="none", headers={"kid": keys.kid}),
    }[mutation]

    with pytest.raises(UnauthenticatedError) as exc:
        tokens.decode_access_token(forged)

    assert exc.value.code == "UNAUTHENTICATED"


def test_jwks_contains_only_public_material() -> None:
    document = tokens.jwks()

    key = document["keys"][0]
    assert key["kid"] == get_settings().jwt_key_id
    assert key["crv"] == "P-256"
    assert "d" not in key


def test_configured_keys_and_previous_key_are_loaded(monkeypatch: pytest.MonkeyPatch) -> None:
    current = ec.generate_private_key(ec.SECP256R1())
    previous = ec.generate_private_key(ec.SECP256R1())
    current_pem = current.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
    ).decode()
    previous_pem = (
        previous.public_key()
        .public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)
        .decode()
    )
    settings = get_settings().model_copy(
        update={
            "jwt_private_key": SecretStr(current_pem),
            "jwt_previous_public_key": SecretStr(previous_pem),
            "jwt_previous_key_id": "old-1",
        }
    )
    monkeypatch.setattr(tokens, "get_settings", lambda: settings)
    tokens.get_signing_keys.cache_clear()
    try:
        keys = tokens.get_signing_keys()
    finally:
        tokens.get_signing_keys.cache_clear()

    assert set(keys.public_keys) == {settings.jwt_key_id, "old-1"}


def test_non_ec_private_key_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    rsa_pem = (
        rsa.generate_private_key(public_exponent=65537, key_size=2048)
        .private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
        .decode()
    )
    settings = get_settings().model_copy(update={"jwt_private_key": SecretStr(rsa_pem)})
    monkeypatch.setattr(tokens, "get_settings", lambda: settings)
    tokens.get_signing_keys.cache_clear()
    try:
        with pytest.raises(TypeError):
            tokens.get_signing_keys()
    finally:
        tokens.get_signing_keys.cache_clear()
