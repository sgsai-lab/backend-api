import dataclasses
from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response, status

from app.core.openapi import error_responses
from app.core.rate_limit import rate_limit
from app.db.session import DbSession
from app.modules.auth.apple_verifier import AppleTokenVerifier, get_apple_verifier
from app.modules.auth.deps import Client
from app.modules.auth.responses import login_response
from app.modules.auth.schemas import AppleRequest, MfaChallengeResponse, TokenResponse
from app.modules.auth.services.google import sign_in_with_provider

router = APIRouter(prefix="/apple")

Verifier = Annotated[AppleTokenVerifier, Depends(get_apple_verifier)]


@router.post(
    "",
    summary="Sign in or sign up with an Apple ID token",
    response_model=TokenResponse | MfaChallengeResponse,
    responses={
        201: {"description": "Account created", "model": TokenResponse},
        **error_responses(400, 401, 403, 409, 422, 429),
    },
    dependencies=[Depends(rate_limit("apple", 10, 60))],
)
async def apple_sign_in(
    payload: AppleRequest,
    request: Request,
    response: Response,
    session: DbSession,
    verifier: Verifier,
    client: Client,
) -> TokenResponse | MfaChallengeResponse:
    identity = await verifier.verify(payload.id_token, payload.nonce)
    if identity.name is None and payload.full_name:
        identity = dataclasses.replace(identity, name=payload.full_name)
    result, created = await sign_in_with_provider(session, "apple", identity, client)
    if created:
        response.status_code = status.HTTP_201_CREATED
    return login_response(request, response, result)
