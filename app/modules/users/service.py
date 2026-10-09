import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import Select, delete, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.email import Mailer
from app.core.errors import ConflictError, ForbiddenError, NotFoundError
from app.core.pagination import escape_like, paginate
from app.modules.auth.models import OAuthAccount
from app.modules.auth.services.mfa import reauthenticate, remove_mfa
from app.modules.auth.services.password import INVITE_TTL, send_password_link
from app.modules.auth.services.sessions import revoke_all_sessions
from app.modules.users.models import User, UserRole, UserStatus
from app.modules.users.repository import get_user_by_email
from app.modules.users.schemas import AdminUserCreate, AdminUserUpdate, UserListParams, UserUpdateMe

_SORT_COLUMNS = {"created_at": User.created_at, "email": User.email, "full_name": User.full_name}


def _not_deleted() -> Select[User]:
    return select(User).where(User.deleted_at.is_(None))


async def update_me(session: AsyncSession, user: User, payload: UserUpdateMe) -> User:
    changes = payload.model_dump(exclude_unset=True)
    if changes.get("full_name") is not None:
        user.full_name = changes["full_name"]
    if "avatar_url" in changes:
        user.avatar_url = str(payload.avatar_url) if payload.avatar_url else None
    await session.commit()
    return user


async def soft_delete_user(session: AsyncSession, user: User) -> None:
    """Disable, anonymise and sign out a user. Caller commits."""
    user.deleted_at = datetime.now(UTC)
    user.status = UserStatus.DISABLED
    user.email = f"deleted+{user.id}@deleted.invalid"
    user.password_hash = None
    await remove_mfa(session, user)
    await session.execute(delete(OAuthAccount).where(OAuthAccount.user_id == user.id))
    await revoke_all_sessions(session, user.id)


async def delete_me(
    session: AsyncSession, user: User, password: str | None, code: str | None
) -> None:
    await reauthenticate(session, user, password, code)
    await soft_delete_user(session, user)
    await session.commit()


async def list_users(session: AsyncSession, params: UserListParams) -> tuple[list[Any], int]:
    stmt = _not_deleted()
    if params.status:
        stmt = stmt.where(User.status == params.status)
    if params.role:
        stmt = stmt.where(User.role == params.role)
    if params.q:
        pattern = f"%{escape_like(params.q)}%"
        stmt = stmt.where(
            or_(User.email.ilike(pattern, escape="\\"), User.full_name.ilike(pattern, escape="\\"))
        )
    column = _SORT_COLUMNS[params.sort.lstrip("-")]
    stmt = stmt.order_by(column.desc() if params.sort.startswith("-") else column.asc(), User.id)
    return await paginate(session, stmt, params)


async def get_user(session: AsyncSession, user_id: uuid.UUID) -> User:
    user = await session.scalar(_not_deleted().where(User.id == user_id))
    if user is None:
        raise NotFoundError("User not found")
    return user


async def create_user(session: AsyncSession, mailer: Mailer, payload: AdminUserCreate) -> User:
    if await get_user_by_email(session, str(payload.email)) is not None:
        raise ConflictError("A user with this email already exists", code="EMAIL_TAKEN")
    user = User(email=str(payload.email), full_name=payload.full_name, role=payload.role)
    session.add(user)
    await session.flush()
    await send_password_link(session, mailer, user, "invite", INVITE_TTL)
    return user


async def _ensure_not_last_admin(session: AsyncSession, target: User) -> None:
    if target.role != UserRole.ADMIN:
        return
    admins = await session.scalar(
        select(func.count())
        .select_from(User)
        .where(
            User.role == UserRole.ADMIN,
            User.status == UserStatus.ACTIVE,
            User.deleted_at.is_(None),
        )
    )
    if (admins or 0) <= 1:
        raise ConflictError("The last administrator cannot be removed", code="LAST_ADMIN")


def _ensure_not_self(actor: User, target: User) -> None:
    if actor.id == target.id:
        raise ForbiddenError("You cannot change your own role or status", code="CANNOT_MODIFY_SELF")


async def admin_update_user(
    session: AsyncSession, actor: User, user_id: uuid.UUID, payload: AdminUserUpdate
) -> User:
    target = await get_user(session, user_id)
    demoting = payload.role is not None and payload.role != target.role
    disabling = payload.status == UserStatus.DISABLED and target.status != UserStatus.DISABLED
    if payload.role is not None or payload.status is not None:
        _ensure_not_self(actor, target)
    if demoting or disabling:
        await _ensure_not_last_admin(session, target)

    if payload.full_name is not None:
        target.full_name = payload.full_name
    if payload.role is not None:
        target.role = payload.role
    if payload.status is not None:
        target.status = payload.status
    if disabling:
        await revoke_all_sessions(session, target.id)
    await session.commit()
    return target


async def admin_delete_user(session: AsyncSession, actor: User, user_id: uuid.UUID) -> None:
    target = await get_user(session, user_id)
    _ensure_not_self(actor, target)
    await _ensure_not_last_admin(session, target)
    await soft_delete_user(session, target)
    await session.commit()
