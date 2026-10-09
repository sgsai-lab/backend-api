from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ConflictError, NotFoundError
from app.modules.auth.google_verifier import GoogleIdentity
from app.modules.auth.models import OAuthAccount
from app.modules.auth.services.login import LoginResult, complete_login
from app.modules.auth.services.sessions import ClientContext
from app.modules.users.models import User
from app.modules.users.repository import get_user_by_email

PROVIDER = "google"
_LABELS = {"google": "Google", "apple": "Apple"}
_FULL_NAME_MAX = 120


async def _find_account(
    session: AsyncSession, subject: str, provider: str = PROVIDER
) -> OAuthAccount | None:
    return await session.scalar(
        select(OAuthAccount).where(
            OAuthAccount.provider == provider, OAuthAccount.provider_subject == subject
        )
    )


def _link(
    session: AsyncSession, user: User, identity: GoogleIdentity, provider: str = PROVIDER
) -> None:
    session.add(
        OAuthAccount(
            user_id=user.id,
            provider=provider,
            provider_subject=identity.subject,
            email=identity.email,
        )
    )


async def _resolve_user(
    session: AsyncSession, identity: GoogleIdentity, provider: str
) -> tuple[User, bool]:
    account = await _find_account(session, identity.subject, provider)
    if account is not None:
        user = await session.get(User, account.user_id)
        if user is None or user.deleted_at is not None:
            raise NotFoundError("Account not found")
        return user, False

    user = await get_user_by_email(session, identity.email)
    if user is not None:
        # Linking to an unverified local account would allow pre-registration account takeover.
        if user.email_verified_at is None:
            raise ConflictError(
                "Sign in with your password and verify your email before using "
                f"{_LABELS[provider]}",
                code="ACCOUNT_LINK_REQUIRED",
            )
        _link(session, user, identity, provider)
        return user, False

    user = User(
        email=identity.email,
        full_name=(identity.name or identity.email.split("@", 1)[0])[:_FULL_NAME_MAX],
        avatar_url=identity.picture,
        email_verified_at=datetime.now(UTC),
    )
    session.add(user)
    await session.flush()
    _link(session, user, identity, provider)
    return user, True


async def sign_in_with_provider(
    session: AsyncSession, provider: str, identity: GoogleIdentity, ctx: ClientContext
) -> tuple[LoginResult, bool]:
    user, created = await _resolve_user(session, identity, provider)
    result = await complete_login(session, user, [provider], ctx)
    await session.commit()
    return result, created


async def sign_in_with_google(
    session: AsyncSession, identity: GoogleIdentity, ctx: ClientContext
) -> tuple[LoginResult, bool]:
    return await sign_in_with_provider(session, PROVIDER, identity, ctx)


async def link_google(session: AsyncSession, user: User, identity: GoogleIdentity) -> None:
    account = await _find_account(session, identity.subject)
    if account is not None:
        if account.user_id != user.id:
            raise ConflictError(
                "This Google account is linked to another user", code="GOOGLE_ACCOUNT_IN_USE"
            )
        return
    existing = await session.scalar(
        select(OAuthAccount).where(
            OAuthAccount.user_id == user.id, OAuthAccount.provider == PROVIDER
        )
    )
    if existing is not None:
        raise ConflictError(
            "A different Google account is already linked", code="GOOGLE_ALREADY_LINKED"
        )
    _link(session, user, identity)
    await session.commit()


async def unlink_google(session: AsyncSession, user: User) -> None:
    account = await session.scalar(
        select(OAuthAccount).where(
            OAuthAccount.user_id == user.id, OAuthAccount.provider == PROVIDER
        )
    )
    if account is None:
        raise NotFoundError("No Google account is linked")
    if user.password_hash is None:
        raise ConflictError("Set a password before unlinking Google", code="LAST_SIGN_IN_METHOD")
    await session.delete(account)
    await session.commit()
