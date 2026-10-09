import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from functools import lru_cache
from typing import Any

import jwt
import structlog
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.serialization import load_pem_private_key, load_pem_public_key
from jwt.algorithms import ECAlgorithm

from app.core.config import get_settings
from app.core.errors import UnauthenticatedError

log = structlog.get_logger(__name__)

ALGORITHM = "ES256"
ACCESS_TOKEN_TYPE = "access"  # noqa: S105 - token type claim, not a secret


@dataclass(frozen=True)
class SigningKeys:
    kid: str
    private_key: ec.EllipticCurvePrivateKey
    public_keys: dict[str, ec.EllipticCurvePublicKey]


@dataclass(frozen=True)
class AccessClaims:
    user_id: uuid.UUID
    session_id: uuid.UUID
    role: str
    amr: tuple[str, ...]


@lru_cache
def get_signing_keys() -> SigningKeys:
    settings = get_settings()
    if settings.jwt_private_key is not None:
        loaded = load_pem_private_key(settings.jwt_private_key.get_secret_value().encode(), None)
        if not isinstance(loaded, ec.EllipticCurvePrivateKey):
            raise TypeError("JWT_PRIVATE_KEY must be an EC P-256 private key")
        private_key = loaded
    else:
        log.warning("jwt_signing_key_ephemeral", reason="JWT_PRIVATE_KEY not set")
        private_key = ec.generate_private_key(ec.SECP256R1())

    public_keys = {settings.jwt_key_id: private_key.public_key()}
    if settings.jwt_previous_public_key and settings.jwt_previous_key_id:
        previous = load_pem_public_key(settings.jwt_previous_public_key.get_secret_value().encode())
        if isinstance(previous, ec.EllipticCurvePublicKey):
            public_keys[settings.jwt_previous_key_id] = previous
    return SigningKeys(settings.jwt_key_id, private_key, public_keys)


def issue_access_token(
    user_id: uuid.UUID, session_id: uuid.UUID, role: str, amr: list[str]
) -> tuple[str, int]:
    settings = get_settings()
    keys = get_signing_keys()
    now = datetime.now(UTC)
    claims: dict[str, Any] = {
        "sub": str(user_id),
        "sid": str(session_id),
        "iss": settings.jwt_issuer,
        "aud": settings.jwt_audience,
        "iat": now,
        "nbf": now,
        "exp": now + timedelta(seconds=settings.access_token_ttl_seconds),
        "jti": uuid.uuid4().hex,
        "typ": ACCESS_TOKEN_TYPE,
        "role": role,
        "amr": amr,
    }
    token = jwt.encode(claims, keys.private_key, algorithm=ALGORITHM, headers={"kid": keys.kid})
    return token, settings.access_token_ttl_seconds


def decode_access_token(token: str) -> AccessClaims:
    settings = get_settings()
    keys = get_signing_keys()
    try:
        kid = jwt.get_unverified_header(token).get("kid")
        key = keys.public_keys.get(str(kid))
        if key is None:
            raise UnauthenticatedError("Invalid access token")
        payload = jwt.decode(
            token,
            key,
            algorithms=[ALGORITHM],
            audience=settings.jwt_audience,
            issuer=settings.jwt_issuer,
            options={"require": ["exp", "iat", "sub", "sid", "jti", "aud", "iss"]},
        )
        if payload.get("typ") != ACCESS_TOKEN_TYPE:
            raise UnauthenticatedError("Invalid access token")
        return AccessClaims(
            user_id=uuid.UUID(payload["sub"]),
            session_id=uuid.UUID(payload["sid"]),
            role=str(payload.get("role", "")),
            amr=tuple(payload.get("amr", [])),
        )
    except jwt.ExpiredSignatureError as exc:
        raise UnauthenticatedError("Access token expired", code="TOKEN_EXPIRED") from exc
    except (jwt.PyJWTError, ValueError) as exc:
        raise UnauthenticatedError("Invalid access token") from exc


def jwks() -> dict[str, list[dict[str, Any]]]:
    keys = []
    for kid, public_key in get_signing_keys().public_keys.items():
        jwk = ECAlgorithm.to_jwk(public_key, as_dict=True)
        keys.append({**jwk, "kid": kid, "alg": ALGORITHM, "use": "sig"})
    return {"keys": keys}
