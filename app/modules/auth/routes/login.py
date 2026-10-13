import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response, status

from app.core.email import MailerDep
from app.core.errors import NotFoundError, UnauthenticatedError
from app.core.openapi import error_responses
from app.core.rate_limit import Limiter, rate_limit
from app.db.session import DbSession
from app.modules.auth.deps import Client, CurrentAuth
from app.modules.auth.firebase_verifier import FirebaseTokenVerifier, get_firebase_verifier
from app.modules.auth.responses import (
    clear_refresh_cookie,
    login_response,
    refresh_token_from_cookie,
    token_response,
)
from app.modules.auth.schemas import (
    LoginRequest,
    MfaChallengeResponse,
    RefreshRequest,
    SessionRead,
    TokenResponse,
)
from app.modules.auth.services import sessions
from app.modules.auth.services.login import login_with_password

router = APIRouter()


@router.post(
    "/login",
    summary="Sign in with email and password",
    response_model=TokenResponse | MfaChallengeResponse,
    responses=error_responses(401, 403, 422, 429),
    dependencies=[Depends(rate_limit("login", 10, 60))],
)
async def login(
    payload: LoginRequest,
    request: Request,
    response: Response,
    session: DbSession,
    mailer: MailerDep,
    limiter: Limiter,
    client: Client,
) -> TokenResponse | MfaChallengeResponse:
    limiter.hit(f"login:email:{str(payload.email).lower()}", 5, 60)
    result = await login_with_password(
        session, mailer, str(payload.email), payload.password, client
    )
    return login_response(request, response, result)


@router.post(
    "/token/refresh",
    summary="Rotate the refresh token and get a new access token",
    responses=error_responses(401, 403, 422, 429),
    dependencies=[Depends(rate_limit("refresh", 30, 60))],
)
async def refresh(
    request: Request,
    response: Response,
    session: DbSession,
    client: Client,
    payload: RefreshRequest | None = None,
) -> TokenResponse:
    raw = (payload.refresh_token if payload else None) or refresh_token_from_cookie(request)
    if raw is None:
        raise UnauthenticatedError("Refresh token required", code="INVALID_REFRESH_TOKEN")
    tokens = await sessions.rotate_refresh_token(session, raw, client)
    return token_response(request, response, tokens)


@router.post(
    "/logout",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Sign out the current session",
    responses=error_responses(401),
)
async def logout(
    auth: CurrentAuth,
    session: DbSession,
    response: Response,
    firebase_verifier: Annotated[FirebaseTokenVerifier, Depends(get_firebase_verifier)],
) -> None:
    if auth.firebase_uid is not None:
        await firebase_verifier.revoke(auth.firebase_uid)
    else:
        await sessions.revoke_session(session, auth.user.id, auth.claims.session_id)
    await session.commit()
    clear_refresh_cookie(response)


@router.post(
    "/logout-all",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Sign out every session",
    responses=error_responses(401),
)
async def logout_all(
    auth: CurrentAuth,
    session: DbSession,
    response: Response,
    firebase_verifier: Annotated[FirebaseTokenVerifier, Depends(get_firebase_verifier)],
) -> None:
    if auth.firebase_uid is not None:
        await firebase_verifier.revoke(auth.firebase_uid)
    else:
        await sessions.revoke_all_sessions(session, auth.user.id)
    await session.commit()
    clear_refresh_cookie(response)


@router.get("/sessions", summary="List my active sessions", responses=error_responses(401))
async def list_sessions(auth: CurrentAuth, session: DbSession) -> list[SessionRead]:
    if auth.firebase_uid is not None:
        return []
    rows = await sessions.list_active_sessions(session, auth.user.id)
    return [
        SessionRead(
            id=row.family_id,
            started_at=row.session_started_at,
            last_used_at=row.created_at,
            expires_at=row.expires_at,
            ip=row.ip,
            user_agent=row.user_agent,
            current=row.family_id == auth.claims.session_id,
        )
        for row in rows
    ]


@router.delete(
    "/sessions/{session_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Revoke one of my sessions",
    responses=error_responses(401, 404),
)
async def revoke_session(session_id: uuid.UUID, auth: CurrentAuth, session: DbSession) -> None:
    if not await sessions.is_session_active(session, auth.user.id, session_id):
        raise NotFoundError("Session not found")
    await sessions.revoke_session(session, auth.user.id, session_id)
    await session.commit()
