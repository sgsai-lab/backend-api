from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response, status

from app.core.openapi import error_responses
from app.core.rate_limit import rate_limit
from app.db.session import DbSession
from app.modules.auth.deps import Client, CurrentUser
from app.modules.auth.google_verifier import GoogleTokenVerifier, get_google_verifier
from app.modules.auth.responses import login_response
from app.modules.auth.schemas import GoogleRequest, MfaChallengeResponse, TokenResponse
from app.modules.auth.services import google

router = APIRouter(prefix="/google")

Verifier = Annotated[GoogleTokenVerifier, Depends(get_google_verifier)]


@router.post(
    "",
    summary="Sign in or sign up with a Google ID token",
    response_model=TokenResponse | MfaChallengeResponse,
    responses={
        201: {"description": "Account created", "model": TokenResponse},
        **error_responses(400, 401, 403, 409, 422, 429),
    },
    dependencies=[Depends(rate_limit("google", 10, 60))],
)
async def google_sign_in(
    payload: GoogleRequest,
    request: Request,
    response: Response,
    session: DbSession,
    verifier: Verifier,
    client: Client,
) -> TokenResponse | MfaChallengeResponse:
    identity = await verifier.verify(payload.id_token, payload.nonce)
    result, created = await google.sign_in_with_google(session, identity, client)
    if created:
        response.status_code = status.HTTP_201_CREATED
    return login_response(request, response, result)


@router.post(
    "/link",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Link a Google account to the current user",
    responses=error_responses(400, 401, 409, 422),
)
async def link(
    payload: GoogleRequest, user: CurrentUser, session: DbSession, verifier: Verifier
) -> None:
    identity = await verifier.verify(payload.id_token, payload.nonce)
    await google.link_google(session, user, identity)


@router.delete(
    "/link",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Unlink Google from the current user",
    responses=error_responses(401, 404, 409),
)
async def unlink(user: CurrentUser, session: DbSession) -> None:
    await google.unlink_google(session, user)
