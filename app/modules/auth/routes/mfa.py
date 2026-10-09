from fastapi import APIRouter, Depends, Request, Response, status

from app.core.email import MailerDep
from app.core.openapi import error_responses
from app.core.rate_limit import rate_limit
from app.db.session import DbSession
from app.modules.auth.deps import Client, CurrentAuth, CurrentUser
from app.modules.auth.responses import token_response
from app.modules.auth.schemas import (
    MfaStatusResponse,
    MfaVerifyRequest,
    ReauthRequest,
    RecoveryCodesResponse,
    TokenResponse,
    TotpCodeRequest,
    TotpSetupResponse,
)
from app.modules.auth.services import mfa

router = APIRouter(prefix="/mfa")


@router.get("", summary="Get my two-factor status", responses=error_responses(401))
async def mfa_status(user: CurrentUser, session: DbSession) -> MfaStatusResponse:
    remaining = await mfa.remaining_recovery_codes(session, user) if user.mfa_enabled else 0
    return MfaStatusResponse(
        enabled=user.mfa_enabled,
        methods=["totp", "recovery_code"] if user.mfa_enabled else [],
        recovery_codes_remaining=remaining,
    )


@router.post(
    "/totp/setup",
    summary="Start TOTP enrolment (returns the secret and otpauth URI)",
    responses=error_responses(401, 409),
)
async def setup_totp(user: CurrentUser, session: DbSession) -> TotpSetupResponse:
    secret, uri = await mfa.setup_totp(session, user)
    return TotpSetupResponse(secret=secret, otpauth_uri=uri)


@router.post(
    "/totp/confirm",
    summary="Confirm TOTP enrolment and receive recovery codes (shown once)",
    responses=error_responses(400, 401, 409, 422),
    dependencies=[Depends(rate_limit("mfa-confirm", 10, 60))],
)
async def confirm_totp(
    payload: TotpCodeRequest, user: CurrentUser, session: DbSession, mailer: MailerDep
) -> RecoveryCodesResponse:
    codes = await mfa.confirm_totp(session, mailer, user, payload.code)
    return RecoveryCodesResponse(recovery_codes=codes)


@router.post(
    "/verify",
    summary="Complete sign-in with a TOTP or recovery code",
    responses=error_responses(400, 422, 429),
    dependencies=[Depends(rate_limit("mfa-verify", 10, 60))],
)
async def verify_mfa(
    payload: MfaVerifyRequest,
    request: Request,
    response: Response,
    session: DbSession,
    client: Client,
) -> TokenResponse:
    tokens = await mfa.verify_mfa_login(
        session, payload.mfa_token, payload.code, payload.recovery_code, client
    )
    return token_response(request, response, tokens)


@router.post(
    "/recovery-codes",
    summary="Regenerate recovery codes (requires a current TOTP code)",
    responses=error_responses(400, 401, 409, 422),
    dependencies=[Depends(rate_limit("mfa-recovery", 10, 60))],
)
async def regenerate_recovery_codes(
    payload: TotpCodeRequest, user: CurrentUser, session: DbSession
) -> RecoveryCodesResponse:
    codes = await mfa.regenerate_recovery_codes(session, user, payload.code)
    return RecoveryCodesResponse(recovery_codes=codes)


@router.delete(
    "/totp",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Disable two-factor authentication",
    responses=error_responses(401, 403, 409, 422),
    dependencies=[Depends(rate_limit("mfa-disable", 10, 60))],
)
async def disable_totp(
    payload: ReauthRequest, auth: CurrentAuth, session: DbSession, mailer: MailerDep
) -> None:
    await mfa.disable_mfa(
        session, mailer, auth.user, auth.claims.session_id, payload.password, payload.code
    )
