import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ConflictError, UnauthenticatedError
from app.modules.auth.firebase_verifier import FirebaseIdentity
from app.modules.auth.models import OAuthAccount
from app.modules.users.models import User
from app.modules.users.repository import get_user_by_email

PROVIDER = "firebase"
_FULL_NAME_MAX = 120


async def get_linked_user(session: AsyncSession, uid: str) -> User:
    account = await session.scalar(
        select(OAuthAccount).where(
            OAuthAccount.provider == PROVIDER,
            OAuthAccount.provider_subject == uid,
        )
    )
    if account is None:
        raise UnauthenticatedError(
            "Firebase account has not been linked",
            code="FIREBASE_ACCOUNT_NOT_LINKED",
        )
    user = await session.get(User, account.user_id)
    if user is None or not user.is_active:
        raise UnauthenticatedError("Account is no longer active")
    return user


async def sign_in_with_firebase(session: AsyncSession, identity: FirebaseIdentity) -> User:
    account = await session.scalar(
        select(OAuthAccount).where(
            OAuthAccount.provider == PROVIDER,
            OAuthAccount.provider_subject == identity.uid,
        )
    )
    if account is not None:
        user = await session.get(User, account.user_id)
        if user is None or not user.is_active:
            raise UnauthenticatedError("Account is no longer active")
    else:
        user = await get_user_by_email(session, identity.email)
        if user is not None:
            if user.email_verified_at is None:
                raise ConflictError(
                    "Sign in with your current method and verify your email "
                    "before linking Firebase",
                    code="ACCOUNT_LINK_REQUIRED",
                )
            session.add(
                OAuthAccount(
                    user_id=user.id,
                    provider=PROVIDER,
                    provider_subject=identity.uid,
                    email=identity.email,
                )
            )
        else:
            user = User(
                email=identity.email,
                full_name=(identity.name or identity.email.split("@", 1)[0])[:_FULL_NAME_MAX],
                avatar_url=identity.picture,
                email_verified_at=datetime.now(UTC),
            )
            session.add(user)
            await session.flush()
            session.add(
                OAuthAccount(
                    user_id=user.id,
                    provider=PROVIDER,
                    provider_subject=identity.uid,
                    email=identity.email,
                )
            )

    user.last_login_at = datetime.now(UTC)
    await session.commit()
    return user


def firebase_session_id(uid: str, auth_time: int) -> uuid.UUID:
    return uuid.uuid5(uuid.NAMESPACE_URL, f"firebase:{uid}:{auth_time}")
