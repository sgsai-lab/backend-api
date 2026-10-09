import pytest

from app.core.crypto import decrypt_secret, encrypt_secret, generate_token, hash_token, keyed_hash
from app.core.errors import RateLimitedError, ValidationFailedError
from app.core.passwords import ensure_password_policy, hash_password, needs_rehash, verify_password
from app.core.rate_limit import RateLimiter


@pytest.mark.parametrize(
    ("password", "message"),
    [
        ("short", "characters long"),
        ("x" * 129, "characters long"),
        ("1234567890", "too common"),
        ("ada.lovelace-rocks", "email address"),
    ],
)
def test_password_policy_rejections(password: str, message: str) -> None:
    with pytest.raises(ValidationFailedError) as exc:
        ensure_password_policy(password, "ada.lovelace@example.com")

    assert message in exc.value.details[0]["message"]


def test_password_policy_accepts_strong_password() -> None:
    ensure_password_policy("Quiet-Harbor-Lamp-81", "ada@example.com")


async def test_hash_and_verify_password() -> None:
    hashed = await hash_password("Quiet-Harbor-Lamp-81")

    assert hashed.startswith("$argon2id$")
    assert await verify_password(hashed, "Quiet-Harbor-Lamp-81")
    assert not await verify_password(hashed, "wrong")
    assert not await verify_password("not-a-hash", "anything")
    assert not await verify_password(None, "anything")
    assert not needs_rehash(hashed)


def test_token_helpers() -> None:
    token = generate_token()

    assert len(token) >= 43
    assert hash_token(token) == hash_token(token)
    assert hash_token(token) != hash_token(generate_token())
    assert keyed_hash("abc") == keyed_hash("abc")
    assert keyed_hash("abc") != hash_token("abc")


def test_secret_encryption_round_trip() -> None:
    ciphertext = encrypt_secret("JBSWY3DPEHPK3PXP")

    assert ciphertext != "JBSWY3DPEHPK3PXP"
    assert decrypt_secret(ciphertext) == "JBSWY3DPEHPK3PXP"
    with pytest.raises(ValueError, match="decrypt"):
        decrypt_secret("tampered")


def test_rate_limiter_blocks_after_limit_and_resets() -> None:
    limiter = RateLimiter()
    for _ in range(3):
        limiter.hit("k", 3, 60)

    with pytest.raises(RateLimitedError) as exc:
        limiter.hit("k", 3, 60)

    assert 1 <= int(exc.value.headers["Retry-After"]) <= 61
    limiter.reset()
    limiter.hit("k", 3, 60)


def test_rate_limiter_window_expires(monkeypatch: pytest.MonkeyPatch) -> None:
    clock = [1000.0]
    monkeypatch.setattr("app.core.rate_limit.time.monotonic", lambda: clock[0])
    limiter = RateLimiter()
    limiter.hit("k", 1, 10)

    clock[0] += 11
    limiter.hit("k", 1, 10)


def test_rate_limiter_prunes_expired_entries(monkeypatch: pytest.MonkeyPatch) -> None:
    clock = [0.0]
    monkeypatch.setattr("app.core.rate_limit.time.monotonic", lambda: clock[0])
    monkeypatch.setattr("app.core.rate_limit._PRUNE_THRESHOLD", 2)
    limiter = RateLimiter()
    for key in ("a", "b", "c"):
        limiter.hit(key, 1, 1)

    clock[0] = 5.0
    limiter.hit("d", 1, 1)

    assert set(limiter._windows) == {"d"}


def test_disabled_rate_limiter_never_blocks() -> None:
    limiter = RateLimiter(enabled=False)
    for _ in range(10):
        limiter.hit("k", 1, 60)
