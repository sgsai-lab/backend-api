import hmac
import secrets
import time
import uuid
from datetime import UTC, datetime, timedelta

import pyotp
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.crypto import decrypt_secret, encrypt_secret, keyed_hash
from app.core.email import Mailer
from app.core.errors import AppError, ConflictError, ForbiddenError, InvalidTokenError
from app.core.passwords import verify_password
from app.modules.auth.models import MfaRecoveryCode, MfaTotp, TokenPurpose
from app.modules.auth.services.one_time_tokens import find_valid_token
from app.modules.auth.services.sessions import (
    ClientContext,
    IssuedTokens,
    revoke_all_sessions,
    start_session,
)
from app.modules.users.models import User
from app.modules.users.repository import get_active_user

TOTP_PERIOD_SECONDS = 30
MAX_CHALLENGE_ATTEMPTS = 5
MFA_CHALLENGE_TTL = timedelta(minutes=5)
RECOVERY_CODE_COUNT = 10
_RECOVERY_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"


class InvalidMfaCodeError(AppError):
    code = "INVALID_MFA_CODE"

    def __init__(self) -> None:
        super().__init__("The verification code is invalid")


def _matching_step(secret: str, code: str) -> int | None:
    totp = pyotp.TOTP(secret)
    current = int(time.time()) // TOTP_PERIOD_SECONDS
    for step in (current - 1, current, current + 1):
        if hmac.compare_digest(totp.generate_otp(step), code):
            return step
    return None


def _normalize_recovery_code(code: str) -> str:
    return code.replace("-", "").replace(" ", "").upper()


def _new_recovery_code() -> str:
    raw = "".join(secrets.choice(_RECOVERY_ALPHABET) for _ in range(10))
    return f"{raw[:5]}-{raw[5:]}"


async def _replace_recovery_codes(session: AsyncSession, user: User) -> list[str]:
    await session.execute(delete(MfaRecoveryCode).where(MfaRecoveryCode.user_id == user.id))
    codes = [_new_recovery_code() for _ in range(RECOVERY_CODE_COUNT)]
    session.add_all(
        MfaRecoveryCode(user_id=user.id, code_hash=keyed_hash(_normalize_recovery_code(c)))
        for c in codes
    )
    return codes


async def _verify_totp(session: AsyncSession, user: User, code: str) -> bool:
    row = await session.scalar(
        select(MfaTotp)
        .where(MfaTotp.user_id == user.id, MfaTotp.confirmed_at.is_not(None))
        .with_for_update()
    )
    if row is None:
        return False
    step = _matching_step(decrypt_secret(row.secret_encrypted), code)
    # Reject replays: a time-step can only be used once.
    if step is None or (row.last_used_step is not None and step <= row.last_used_step):
        return False
    row.last_used_step = step
    return True


async def _consume_recovery_code(session: AsyncSession, user: User, code: str) -> bool:
    row = await session.scalar(
        select(MfaRecoveryCode)
        .where(
            MfaRecoveryCode.user_id == user.id,
            MfaRecoveryCode.code_hash == keyed_hash(_normalize_recovery_code(code)),
            MfaRecoveryCode.used_at.is_(None),
        )
        .with_for_update()
    )
    if row is None:
        return False
    row.used_at = datetime.now(UTC)
    return True


async def verify_second_factor(
    session: AsyncSession, user: User, code: str | None = None, recovery_code: str | None = None
) -> bool:
    if code:
        return await _verify_totp(session, user, code)
    if recovery_code:
        return await _consume_recovery_code(session, user, recovery_code)
    return False


async def remaining_recovery_codes(session: AsyncSession, user: User) -> int:
    count = await session.scalar(
        select(func.count())
        .select_from(MfaRecoveryCode)
        .where(MfaRecoveryCode.user_id == user.id, MfaRecoveryCode.used_at.is_(None))
    )
    return count or 0


async def remove_mfa(session: AsyncSession, user: User) -> None:
    await session.execute(delete(MfaRecoveryCode).where(MfaRecoveryCode.user_id == user.id))
    await session.execute(delete(MfaTotp).where(MfaTotp.user_id == user.id))
    user.mfa_enabled = False


def _pending_secret(row: MfaTotp | None) -> str | None:
    # An undecryptable pending secret (e.g. after MFA key rotation) is replaced, not fatal.
    if row is None:
        return None
    try:
        return decrypt_secret(row.secret_encrypted)
    except ValueError:
        return None


async def setup_totp(session: AsyncSession, user: User) -> tuple[str, str]:
    if user.mfa_enabled:
        raise ConflictError(
            "Two-factor authentication is already enabled", code="MFA_ALREADY_ENABLED"
        )
    row = await session.get(MfaTotp, user.id)
    secret = _pending_secret(row)
    if secret is None:
        secret = pyotp.random_base32()
        if row is None:
            session.add(MfaTotp(user_id=user.id, secret_encrypted=encrypt_secret(secret)))
        else:
            row.secret_encrypted = encrypt_secret(secret)
        await session.commit()
    uri = pyotp.TOTP(secret).provisioning_uri(
        name=user.email, issuer_name=get_settings().mfa_issuer
    )
    return secret, uri


async def confirm_totp(session: AsyncSession, mailer: Mailer, user: User, code: str) -> list[str]:
    if user.mfa_enabled:
        raise ConflictError(
            "Two-factor authentication is already enabled", code="MFA_ALREADY_ENABLED"
        )
    row = await session.get(MfaTotp, user.id, with_for_update=True)
    if row is None:
        raise ConflictError("Start two-factor setup first", code="MFA_SETUP_REQUIRED")
    step = _matching_step(decrypt_secret(row.secret_encrypted), code)
    if step is None:
        raise InvalidMfaCodeError()
    row.confirmed_at = datetime.now(UTC)
    row.last_used_step = step
    user.mfa_enabled = True
    codes = await _replace_recovery_codes(session, user)
    await session.commit()
    await mailer.send(user.email, "mfa_enabled", name=user.full_name)
    return codes


async def verify_mfa_login(
    session: AsyncSession,
    raw_token: str,
    code: str | None,
    recovery_code: str | None,
    ctx: ClientContext,
) -> IssuedTokens:
    challenge = await find_valid_token(session, raw_token, TokenPurpose.MFA_CHALLENGE)
    user = await get_active_user(session, challenge.user_id)
    if user is None or challenge.attempts >= MAX_CHALLENGE_ATTEMPTS:
        challenge.used_at = datetime.now(UTC)
        await session.commit()
        raise InvalidTokenError()
    if not await verify_second_factor(session, user, code, recovery_code):
        challenge.attempts += 1
        await session.commit()
        raise InvalidMfaCodeError()

    challenge.used_at = datetime.now(UTC)
    amr = [*challenge.data.get("amr", []), "mfa"]
    tokens = start_session(session, user, amr, ctx)
    await session.commit()
    return tokens


async def regenerate_recovery_codes(session: AsyncSession, user: User, code: str) -> list[str]:
    if not user.mfa_enabled:
        raise ConflictError("Two-factor authentication is not enabled", code="MFA_NOT_ENABLED")
    if not await _verify_totp(session, user, code):
        raise InvalidMfaCodeError()
    codes = await _replace_recovery_codes(session, user)
    await session.commit()
    return codes


async def reauthenticate(
    session: AsyncSession, user: User, password: str | None, code: str | None
) -> None:
    """Require the password (if set) and a TOTP code (if MFA is on) before sensitive changes."""
    if user.password_hash is None and not user.mfa_enabled:
        raise ForbiddenError(
            "Set a password or enable two-factor authentication first",
            code="REAUTHENTICATION_UNAVAILABLE",
        )
    password_ok = user.password_hash is None or (
        password is not None and await verify_password(user.password_hash, password)
    )
    mfa_ok = not user.mfa_enabled or await verify_second_factor(session, user, code=code)
    if not (password_ok and mfa_ok):
        raise ForbiddenError("Re-authentication failed", code="REAUTHENTICATION_FAILED")


async def disable_mfa(
    session: AsyncSession,
    mailer: Mailer,
    user: User,
    current_session_id: uuid.UUID,
    password: str | None,
    code: str | None,
) -> None:
    if not user.mfa_enabled:
        raise ConflictError("Two-factor authentication is not enabled", code="MFA_NOT_ENABLED")
    await reauthenticate(session, user, password, code)
    await remove_mfa(session, user)
    await revoke_all_sessions(session, user.id, except_family=current_session_id)
    await session.commit()
    await mailer.send(user.email, "mfa_disabled", name=user.full_name)
