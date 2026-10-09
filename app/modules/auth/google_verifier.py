import time
from dataclasses import dataclass
from functools import lru_cache
from typing import Any

import httpx
import jwt
import structlog

from app.core.config import get_settings
from app.core.errors import AppError, UnauthenticatedError

log = structlog.get_logger(__name__)

GOOGLE_CERTS_URL = "https://www.googleapis.com/oauth2/v3/certs"
GOOGLE_ISSUERS = frozenset({"accounts.google.com", "https://accounts.google.com"})
_DEFAULT_CACHE_SECONDS = 3600


@dataclass(frozen=True)
class GoogleIdentity:
    subject: str
    email: str
    name: str | None
    picture: str | None


def _max_age(cache_control: str) -> int:
    for part in cache_control.split(","):
        name, _, value = part.strip().partition("=")
        if name == "max-age" and value.isdigit():
            return int(value)
    return _DEFAULT_CACHE_SECONDS


class GoogleTokenVerifier:
    """Verifies Google ID tokens against Google's published JWKS (cached per Cache-Control)."""

    def __init__(self, client_ids: list[str], jwks: dict[str, Any] | None = None) -> None:
        self._client_ids = client_ids
        self._jwks = jwks
        self._expires_at = float("inf") if jwks else 0.0

    async def _signing_key(self, kid: str) -> Any:
        if self._jwks is None or time.monotonic() >= self._expires_at:
            async with httpx.AsyncClient(timeout=5.0) as client:
                response = await client.get(GOOGLE_CERTS_URL)
                response.raise_for_status()
            self._jwks = response.json()
            self._expires_at = time.monotonic() + _max_age(
                response.headers.get("cache-control", "")
            )
        key_set = jwt.PyJWKSet.from_dict(self._jwks)
        for key in key_set.keys:
            if key.key_id == kid:
                return key.key
        raise jwt.InvalidTokenError("Unknown signing key")

    async def verify(self, id_token: str, nonce: str | None) -> GoogleIdentity:
        if not self._client_ids:
            raise AppError("Google sign-in is not configured", code="GOOGLE_SIGNIN_UNAVAILABLE")
        try:
            kid = str(jwt.get_unverified_header(id_token).get("kid"))
            claims: dict[str, Any] = jwt.decode(
                id_token,
                await self._signing_key(kid),
                algorithms=["RS256"],
                audience=self._client_ids,
                options={"require": ["exp", "iat", "iss", "aud", "sub"]},
            )
        except (jwt.PyJWTError, httpx.HTTPError) as exc:
            log.info("google_token_rejected", exc_type=type(exc).__name__)
            raise UnauthenticatedError("Invalid Google token", code="INVALID_GOOGLE_TOKEN") from exc
        if claims.get("iss") not in GOOGLE_ISSUERS or (nonce and claims.get("nonce") != nonce):
            raise UnauthenticatedError("Invalid Google token", code="INVALID_GOOGLE_TOKEN")
        if claims.get("email_verified") is not True or not claims.get("email"):
            raise AppError("Google email is not verified", code="GOOGLE_EMAIL_NOT_VERIFIED")
        return GoogleIdentity(
            subject=str(claims["sub"]),
            email=str(claims["email"]),
            name=claims.get("name"),
            picture=claims.get("picture"),
        )


@lru_cache
def get_google_verifier() -> GoogleTokenVerifier:
    return GoogleTokenVerifier(get_settings().google_oauth_client_ids)
