import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import structlog
from sqlalchemy import ColumnElement, exists, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.crypto import generate_token, hash_token
from app.core.errors import UnauthenticatedError
from app.core.tokens import issue_access_token
from app.modules.auth.models import RefreshSession
from app.modules.users.models import User

log = structlog.get_logger(__name__)


@dataclass(frozen=True)
class ClientContext:
    ip: str | None
    user_agent: str | None


@dataclass(frozen=True)
class IssuedTokens:
    access_token: str
    expires_in: int
    refresh_token: str
    session_id: uuid.UUID


def _active_clause(now: datetime) -> list[ColumnElement[bool]]:
    return [RefreshSession.revoked_at.is_(None), RefreshSession.expires_at > now]


def _issue(
    session: AsyncSession,
    user: User,
    family_id: uuid.UUID,
    amr: list[str],
    ctx: ClientContext,
    started_at: datetime,
    absolute_expires_at: datetime,
) -> tuple[IssuedTokens, RefreshSession]:
    now = datetime.now(UTC)
    raw = generate_token()
    row = RefreshSession(
        id=uuid.uuid4(),
        user_id=user.id,
        family_id=family_id,
        token_hash=hash_token(raw),
        auth_methods=amr,
        user_agent=ctx.user_agent[:255] if ctx.user_agent else None,
        ip=ctx.ip,
        session_started_at=started_at,
        expires_at=min(
            now + timedelta(days=get_settings().refresh_token_ttl_days), absolute_expires_at
        ),
        absolute_expires_at=absolute_expires_at,
    )
    session.add(row)
    access_token, expires_in = issue_access_token(user.id, family_id, user.role.value, amr)
    return IssuedTokens(access_token, expires_in, raw, family_id), row


def start_session(
    session: AsyncSession, user: User, amr: list[str], ctx: ClientContext
) -> IssuedTokens:
    now = datetime.now(UTC)
    absolute = now + timedelta(days=get_settings().refresh_token_absolute_ttl_days)
    user.last_login_at = now
    tokens, _ = _issue(session, user, uuid.uuid4(), amr, ctx, now, absolute)
    return tokens


async def rotate_refresh_token(session: AsyncSession, raw: str, ctx: ClientContext) -> IssuedTokens:
    row = await session.scalar(
        select(RefreshSession).where(RefreshSession.token_hash == hash_token(raw)).with_for_update()
    )
    if row is None:
        raise UnauthenticatedError("Invalid refresh token", code="INVALID_REFRESH_TOKEN")
    if row.replaced_by_id is not None:
        await revoke_session(session, row.user_id, row.family_id)
        await session.commit()
        log.warning(
            "refresh_token_reuse_detected", user_id=str(row.user_id), session_id=str(row.family_id)
        )
        raise UnauthenticatedError("Refresh token reuse detected", code="REFRESH_TOKEN_REUSED")

    now = datetime.now(UTC)
    if row.revoked_at is not None:
        raise UnauthenticatedError("Invalid refresh token", code="INVALID_REFRESH_TOKEN")
    if row.expires_at <= now:
        raise UnauthenticatedError("Refresh token expired", code="TOKEN_EXPIRED")

    user = await session.get(User, row.user_id)
    if user is None or not user.is_active:
        await revoke_session(session, row.user_id, row.family_id)
        await session.commit()
        raise UnauthenticatedError("Invalid refresh token", code="INVALID_REFRESH_TOKEN")

    tokens, new_row = _issue(
        session,
        user,
        row.family_id,
        list(row.auth_methods),
        ctx,
        row.session_started_at,
        row.absolute_expires_at,
    )
    row.revoked_at = now
    row.replaced_by_id = new_row.id
    await session.commit()
    return tokens


async def revoke_session(session: AsyncSession, user_id: uuid.UUID, family_id: uuid.UUID) -> None:
    await session.execute(
        update(RefreshSession)
        .where(
            RefreshSession.user_id == user_id,
            RefreshSession.family_id == family_id,
            RefreshSession.revoked_at.is_(None),
        )
        .values(revoked_at=datetime.now(UTC))
    )


async def revoke_all_sessions(
    session: AsyncSession, user_id: uuid.UUID, except_family: uuid.UUID | None = None
) -> None:
    stmt = update(RefreshSession).where(
        RefreshSession.user_id == user_id, RefreshSession.revoked_at.is_(None)
    )
    if except_family is not None:
        stmt = stmt.where(RefreshSession.family_id != except_family)
    await session.execute(stmt.values(revoked_at=datetime.now(UTC)))


async def list_active_sessions(session: AsyncSession, user_id: uuid.UUID) -> list[RefreshSession]:
    rows = await session.scalars(
        select(RefreshSession)
        .where(RefreshSession.user_id == user_id, *_active_clause(datetime.now(UTC)))
        .order_by(RefreshSession.created_at.desc())
    )
    return list(rows.all())


async def is_session_active(
    session: AsyncSession, user_id: uuid.UUID, family_id: uuid.UUID
) -> bool:
    stmt = select(
        exists().where(
            RefreshSession.user_id == user_id,
            RefreshSession.family_id == family_id,
            *_active_clause(datetime.now(UTC)),
        )
    )
    return bool(await session.scalar(stmt))
