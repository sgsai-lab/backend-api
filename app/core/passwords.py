from functools import lru_cache
from pathlib import Path

from anyio import to_thread
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError

from app.core.errors import ValidationFailedError

MIN_LENGTH = 10
MAX_LENGTH = 128
# NCSC 100k most-used passwords (SecLists, MIT), filtered to MIN_LENGTH..MAX_LENGTH.
_COMMON_PASSWORDS_FILE = Path(__file__).resolve().parent.parent / "data" / "common_passwords.txt"

# OWASP Argon2id baseline: m=19 MiB, t=2, p=1.
_hasher = PasswordHasher(time_cost=2, memory_cost=19_456, parallelism=1)


@lru_cache
def _dummy_hash() -> str:
    return _hasher.hash("dummy-password-for-timing")


@lru_cache
def _common_passwords() -> frozenset[str]:
    return frozenset(_COMMON_PASSWORDS_FILE.read_text(encoding="utf-8").split())


def ensure_password_policy(
    password: str, email: str | None = None, field: str = "body.password"
) -> None:
    if not MIN_LENGTH <= len(password) <= MAX_LENGTH:
        raise ValidationFailedError(field, f"Must be {MIN_LENGTH}-{MAX_LENGTH} characters long")
    lowered = password.lower()
    if lowered in _common_passwords():
        raise ValidationFailedError(field, "This password is too common")
    local_part = email.split("@", 1)[0].lower() if email else ""
    if len(local_part) >= 3 and local_part in lowered:
        raise ValidationFailedError(field, "Password must not contain your email address")


async def hash_password(password: str) -> str:
    return await to_thread.run_sync(_hasher.hash, password)


def _verify(password_hash: str, password: str) -> bool:
    try:
        return _hasher.verify(password_hash, password)
    except (VerificationError, InvalidHashError):
        return False


async def verify_password(password_hash: str | None, password: str) -> bool:
    # Always run Argon2 so response time doesn't reveal whether the account exists.
    if password_hash is None:
        await to_thread.run_sync(_verify, _dummy_hash(), password)
        return False
    return await to_thread.run_sync(_verify, password_hash, password)


def needs_rehash(password_hash: str) -> bool:
    return _hasher.check_needs_rehash(password_hash)
