import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.email import Mailer
from app.core.errors import InvalidTokenError
from app.core.passwords import ensure_password_policy, hash_password
from app.core.rate_limit import RateLimiter
from app.modules.auth.models import TokenPurpose
from app.modules.auth.services.one_time_tokens import consume_token, issue_token
from app.modules.users.models import User
from app.modules.users.repository import get_active_user, get_user_by_email

EMAIL_VERIFICATION_TTL = timedelta(hours=24)
VERIFY_PATH = "/verify-email"


@dataclass(frozen=True)
class SignupResult:
    id: uuid.UUID
    email: str
    full_name: str
    email_verified: bool


async def _send_verification(session: AsyncSession, mailer: Mailer, user: User) -> None:
    raw = await issue_token(
        session, user.id, TokenPurpose.EMAIL_VERIFICATION, EMAIL_VERIFICATION_TTL
    )
    await session.commit()
    await mailer.send(
        user.email, "verify_email", name=user.full_name, link=mailer.link(VERIFY_PATH, raw)
    )


async def signup(
    session: AsyncSession, mailer: Mailer, email: str, password: str, full_name: str
) -> SignupResult:
    ensure_password_policy(password, email)
    # Hash before the existence check so both paths take the same time.
    password_hash = await hash_password(password)
    decoy = SignupResult(uuid.uuid4(), email, full_name, email_verified=False)

    existing = await get_user_by_email(session, email)
    if existing is not None:
        await mailer.send(existing.email, "signup_existing", name=existing.full_name)
        return decoy

    user = User(email=email, password_hash=password_hash, full_name=full_name)
    session.add(user)
    try:
        await session.flush()
    except IntegrityError:
        await session.rollback()
        return decoy
    await _send_verification(session, mailer, user)
    return SignupResult(user.id, user.email, user.full_name, email_verified=False)


async def verify_email(session: AsyncSession, raw_token: str) -> None:
    token = await consume_token(session, raw_token, TokenPurpose.EMAIL_VERIFICATION)
    user = await get_active_user(session, token.user_id)
    if user is None:
        raise InvalidTokenError()
    if user.email_verified_at is None:
        user.email_verified_at = datetime.now(UTC)
    await session.commit()


async def resend_verification(
    session: AsyncSession, mailer: Mailer, limiter: RateLimiter, email: str
) -> None:
    limiter.hit(f"verify-resend:email:{email.lower()}", 3, 3600)
    user = await get_user_by_email(session, email)
    if user is not None and user.is_active and user.email_verified_at is None:
        await _send_verification(session, mailer, user)
