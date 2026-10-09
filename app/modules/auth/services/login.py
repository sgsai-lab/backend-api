from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.email import Mailer
from app.core.errors import ForbiddenError, InvalidCredentialsError
from app.core.passwords import hash_password, needs_rehash, verify_password
from app.modules.auth.models import TokenPurpose
from app.modules.auth.services.mfa import MFA_CHALLENGE_TTL
from app.modules.auth.services.one_time_tokens import issue_token
from app.modules.auth.services.sessions import ClientContext, IssuedTokens, start_session
from app.modules.users.models import User, UserStatus
from app.modules.users.repository import get_user_by_email

LOCKOUT_THRESHOLD = 10
FAILURE_WINDOW = timedelta(minutes=15)
LOCKOUT_DURATION = timedelta(minutes=15)


@dataclass(frozen=True)
class MfaChallenge:
    mfa_token: str


LoginResult = IssuedTokens | MfaChallenge


async def complete_login(
    session: AsyncSession, user: User, amr: list[str], ctx: ClientContext
) -> LoginResult:
    """Issue tokens, or an MFA challenge when the user has two-factor enabled. Caller commits."""
    if user.status != UserStatus.ACTIVE:
        raise ForbiddenError("This account is disabled", code="ACCOUNT_DISABLED")
    if user.mfa_enabled:
        raw = await issue_token(
            session, user.id, TokenPurpose.MFA_CHALLENGE, MFA_CHALLENGE_TTL, data={"amr": amr}
        )
        return MfaChallenge(raw)
    return start_session(session, user, amr, ctx)


def _is_locked(user: User, now: datetime) -> bool:
    return user.locked_until is not None and user.locked_until > now


async def _record_failure(session: AsyncSession, mailer: Mailer, user: User) -> None:
    now = datetime.now(UTC)
    if user.last_failed_login_at is None or now - user.last_failed_login_at > FAILURE_WINDOW:
        user.failed_login_count = 0
    user.failed_login_count += 1
    user.last_failed_login_at = now
    locked = user.failed_login_count >= LOCKOUT_THRESHOLD
    if locked:
        user.locked_until = now + LOCKOUT_DURATION
        user.failed_login_count = 0
    await session.commit()
    if locked:
        minutes = int(LOCKOUT_DURATION.total_seconds() // 60)
        await mailer.send(user.email, "account_locked", name=user.full_name, minutes=minutes)


async def login_with_password(
    session: AsyncSession, mailer: Mailer, email: str, password: str, ctx: ClientContext
) -> LoginResult:
    user = await get_user_by_email(session, email)
    if user is None or _is_locked(user, datetime.now(UTC)):
        # Same work and same error whether the account is missing or locked: no enumeration.
        await verify_password(None, password)
        raise InvalidCredentialsError()
    if not await verify_password(user.password_hash, password):
        await _record_failure(session, mailer, user)
        raise InvalidCredentialsError()

    user.failed_login_count = 0
    user.locked_until = None
    if user.password_hash and needs_rehash(user.password_hash):
        user.password_hash = await hash_password(password)
    result = await complete_login(session, user, ["pwd"], ctx)
    await session.commit()
    return result
