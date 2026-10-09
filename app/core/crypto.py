import base64
import hashlib
import hmac
import secrets
from functools import lru_cache

import structlog
from cryptography.fernet import Fernet, InvalidToken

from app.core.config import get_settings

log = structlog.get_logger(__name__)


def generate_token() -> str:
    return secrets.token_urlsafe(32)


def hash_token(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


@lru_cache
def _fernet_key() -> bytes:
    configured = get_settings().mfa_encryption_key
    if configured is not None:
        return configured.get_secret_value().encode()
    log.warning("mfa_encryption_key_ephemeral", reason="MFA_ENCRYPTION_KEY not set")
    return Fernet.generate_key()


def encrypt_secret(plaintext: str) -> str:
    return Fernet(_fernet_key()).encrypt(plaintext.encode()).decode()


def decrypt_secret(ciphertext: str) -> str:
    try:
        return Fernet(_fernet_key()).decrypt(ciphertext.encode()).decode()
    except InvalidToken as exc:
        raise ValueError("Unable to decrypt secret") from exc


def keyed_hash(value: str) -> str:
    # Keyed so leaked hashes of low-entropy recovery codes can't be brute-forced offline.
    key = hashlib.sha256(b"recovery-codes:" + base64.urlsafe_b64decode(_fernet_key())).digest()
    return hmac.new(key, value.encode(), hashlib.sha256).hexdigest()
