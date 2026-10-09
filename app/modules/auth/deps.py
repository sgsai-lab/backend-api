from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.core.config import get_settings
from app.core.errors import ForbiddenError, UnauthenticatedError
from app.core.rate_limit import client_ip
from app.core.tokens import AccessClaims, decode_access_token
from app.db.session import DbSession
from app.modules.auth.services.sessions import ClientContext, is_session_active
from app.modules.users.models import User, UserRole
from app.modules.users.repository import get_active_user

_bearer = HTTPBearer(auto_error=False, description="Access token from /api/v1/auth/login")


@dataclass(frozen=True)
class AuthContext:
    user: User
    claims: AccessClaims


async def get_auth_context(
    session: DbSession,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
) -> AuthContext:
    if credentials is None:
        raise UnauthenticatedError()
    claims = decode_access_token(credentials.credentials)
    user = await get_active_user(session, claims.user_id)
    # Checking the session makes logout, password reset and disabling take effect immediately.
    if user is None or not await is_session_active(session, user.id, claims.session_id):
        raise UnauthenticatedError("Session is no longer valid")
    return AuthContext(user, claims)


CurrentAuth = Annotated[AuthContext, Depends(get_auth_context)]


async def get_current_user(auth: CurrentAuth) -> User:
    return auth.user


CurrentUser = Annotated[User, Depends(get_current_user)]


async def require_admin(auth: CurrentAuth) -> User:
    if auth.user.role != UserRole.ADMIN:
        raise ForbiddenError("Administrator role required")
    if get_settings().admin_require_mfa and "mfa" not in auth.claims.amr:
        raise ForbiddenError(
            "Sign in with two-factor authentication to continue", code="MFA_REQUIRED"
        )
    return auth.user


AdminUser = Annotated[User, Depends(require_admin)]


async def require_mfa_feature() -> None:
    if not get_settings().mfa_enabled:
        raise ForbiddenError("Two-factor enrolment is not enabled", code="FEATURE_DISABLED")


async def require_verified_email(user: CurrentUser) -> User:
    if user.email_verified_at is None:
        raise ForbiddenError("Verify your email address first", code="EMAIL_NOT_VERIFIED")
    return user


VerifiedUser = Annotated[User, Depends(require_verified_email)]


def get_client_context(request: Request) -> ClientContext:
    return ClientContext(ip=client_ip(request), user_agent=request.headers.get("user-agent"))


Client = Annotated[ClientContext, Depends(get_client_context)]
