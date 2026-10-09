import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.crypto import generate_token, hash_token
from app.core.errors import InvalidTokenError
from app.modules.auth.models import OneTimeToken, TokenPurpose


async def issue_token(
    session: AsyncSession,
    user_id: uuid.UUID,
    purpose: TokenPurpose,
    ttl: timedelta,
    data: dict[str, Any] | None = None,
) -> str:
    """Create a single-use token, invalidating any earlier unused token of the same purpose."""
    now = datetime.now(UTC)
    await session.execute(
        update(OneTimeToken)
        .where(
            OneTimeToken.user_id == user_id,
            OneTimeToken.purpose == purpose,
            OneTimeToken.used_at.is_(None),
        )
        .values(used_at=now)
    )
    raw = generate_token()
    session.add(
        OneTimeToken(
            user_id=user_id,
            purpose=purpose,
            token_hash=hash_token(raw),
            expires_at=now + ttl,
            data=data or {},
        )
    )
    return raw


async def find_valid_token(session: AsyncSession, raw: str, purpose: TokenPurpose) -> OneTimeToken:
    row = await session.scalar(
        select(OneTimeToken)
        .where(OneTimeToken.token_hash == hash_token(raw), OneTimeToken.purpose == purpose)
        .with_for_update()
    )
    if row is None or row.used_at is not None or row.expires_at <= datetime.now(UTC):
        raise InvalidTokenError()
    return row


async def consume_token(session: AsyncSession, raw: str, purpose: TokenPurpose) -> OneTimeToken:
    row = await find_valid_token(session, raw, purpose)
    row.used_at = datetime.now(UTC)
    return row
