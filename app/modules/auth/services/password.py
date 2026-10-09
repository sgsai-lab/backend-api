import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.email import Mailer
from app.core.errors import AppError, ConflictError, InvalidTokenError, ValidationFailedError
from app.core.passwords import ensure_password_policy, hash_password, verify_password
from app.core.rate_limit import RateLimiter
from app.modules.auth.models import TokenPurpose
from app.modules.auth.services.mfa import InvalidMfaCodeError, verify_second_factor
from app.modules.auth.services.one_time_tokens import find_valid_token, issue_token
from app.modules.auth.services.sessions import revoke_all_sessions
from app.modules.users.models import User
from app.modules.users.repository import get_active_user, get_user_by_email

PASSWORD_RESET_TTL = timedelta(minutes=30)
INVITE_TTL = timedelta(hours=72)
RESET_PATH = "/reset-password"
_NEW_PASSWORD_FIELD = "body.new_password"  # noqa: S105 - field name, not a secret


async def send_password_link(
    session: AsyncSession, mailer: Mailer, user: User, template: str, ttl: timedelta
) -> None:
    raw = await issue_token(session, user.id, TokenPurpose.PASSWORD_RESET, ttl)
    await session.commit()
    await mailer.send(user.email, template, name=user.full_name, link=mailer.link(RESET_PATH, raw))


async def forgot_password(
    session: AsyncSession, mailer: Mailer, limiter: RateLimiter, email: str
) -> None:
    limiter.hit(f"forgot:email:{email.lower()}", 3, 3600)
    user = await get_user_by_email(session, email)
    if user is not None and user.is_active:
        await send_password_link(session, mailer, user, "password_reset", PASSWORD_RESET_TTL)


async def _set_password(user: User, new_password: str) -> None:
    ensure_password_policy(new_password, user.email, _NEW_PASSWORD_FIELD)
    user.password_hash = await hash_password(new_password)


async def reset_password(
    session: AsyncSession,
    mailer: Mailer,
    raw_token: str,
    new_password: str,
    mfa_code: str | None,
    recovery_code: str | None,
) -> None:
    token = await find_valid_token(session, raw_token, TokenPurpose.PASSWORD_RESET)
    user = await get_active_user(session, token.user_id)
    if user is None:
        raise InvalidTokenError()
    if user.mfa_enabled and not await verify_second_factor(session, user, mfa_code, recovery_code):
        if mfa_code or recovery_code:
            raise InvalidMfaCodeError()
        raise AppError("A two-factor code is required", code="MFA_REQUIRED")

    await _set_password(user, new_password)
    now = datetime.now(UTC)
    token.used_at = now
    # Following the emailed link proves mailbox ownership (also used by admin invites).
    user.email_verified_at = user.email_verified_at or now
    user.failed_login_count = 0
    user.locked_until = None
    await revoke_all_sessions(session, user.id)
    await session.commit()
    await mailer.send(user.email, "password_changed", name=user.full_name)


async def change_password(
    session: AsyncSession,
    mailer: Mailer,
    user: User,
    current_session_id: uuid.UUID,
    current_password: str,
    new_password: str,
) -> None:
    if user.password_hash is None:
        raise ConflictError("No password is set for this account", code="PASSWORD_NOT_SET")
    if not await verify_password(user.password_hash, current_password):
        raise AppError("Current password is incorrect", code="INVALID_CURRENT_PASSWORD")
    if current_password == new_password:
        raise ValidationFailedError(_NEW_PASSWORD_FIELD, "Must differ from the current password")
    await _set_password(user, new_password)
    await revoke_all_sessions(session, user.id, except_family=current_session_id)
    await session.commit()
    await mailer.send(user.email, "password_changed", name=user.full_name)


async def set_initial_password(session: AsyncSession, user: User, new_password: str) -> None:
    if user.password_hash is not None:
        raise ConflictError("A password is already set", code="PASSWORD_ALREADY_SET")
    await _set_password(user, new_password)
    await session.commit()
