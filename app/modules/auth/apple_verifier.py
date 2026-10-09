from functools import lru_cache

from app.core.config import get_settings
from app.modules.auth.google_verifier import GoogleTokenVerifier


class AppleTokenVerifier(GoogleTokenVerifier):
    """Sign in with Apple ID tokens; audience is the Services ID (web) or bundle ID (iOS)."""

    certs_url = "https://appleid.apple.com/auth/keys"
    issuers = frozenset({"https://appleid.apple.com"})
    label = "Apple"
    code = "APPLE"


@lru_cache
def get_apple_verifier() -> AppleTokenVerifier:
    return AppleTokenVerifier(get_settings().apple_client_ids)
