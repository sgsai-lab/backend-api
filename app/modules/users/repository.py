import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.users.models import User, UserStatus


async def get_active_user(session: AsyncSession, user_id: uuid.UUID) -> User | None:
    return await session.scalar(
        select(User).where(
            User.id == user_id, User.deleted_at.is_(None), User.status == UserStatus.ACTIVE
        )
    )


async def get_user_by_email(session: AsyncSession, email: str) -> User | None:
    return await session.scalar(
        select(User).where(User.email == email.strip(), User.deleted_at.is_(None))
    )
