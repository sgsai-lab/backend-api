from fastapi import Request, Response

from app.core.config import get_settings
from app.core.errors import ForbiddenError
from app.modules.auth.schemas import MfaChallengeResponse, TokenResponse
from app.modules.auth.services.login import LoginResult, MfaChallenge
from app.modules.auth.services.sessions import IssuedTokens

REFRESH_COOKIE = "__Host-refresh"


def is_web_client(request: Request) -> bool:
    return request.headers.get("x-client", "").lower() == "web"


def token_response(request: Request, response: Response, tokens: IssuedTokens) -> TokenResponse:
    if not is_web_client(request):
        return TokenResponse(
            access_token=tokens.access_token,
            expires_in=tokens.expires_in,
            refresh_token=tokens.refresh_token,
        )
    response.set_cookie(
        REFRESH_COOKIE,
        tokens.refresh_token,
        max_age=get_settings().refresh_token_ttl_days * 86_400,
        httponly=True,
        secure=True,
        samesite="strict",
        path="/",
    )
    return TokenResponse(access_token=tokens.access_token, expires_in=tokens.expires_in)


def login_response(
    request: Request, response: Response, result: LoginResult
) -> TokenResponse | MfaChallengeResponse:
    if isinstance(result, MfaChallenge):
        return MfaChallengeResponse(mfa_token=result.mfa_token)
    return token_response(request, response, result)


def clear_refresh_cookie(response: Response) -> None:
    response.delete_cookie(REFRESH_COOKIE, path="/", secure=True, httponly=True, samesite="strict")


def refresh_token_from_cookie(request: Request) -> str | None:
    token = request.cookies.get(REFRESH_COOKIE)
    if token is None:
        return None
    # Cookie-based refresh is CSRF-sensitive: only accept it from our own web origins.
    if request.headers.get("origin") not in get_settings().cors_allow_origins:
        raise ForbiddenError("Origin not allowed", code="ORIGIN_NOT_ALLOWED")
    return token
