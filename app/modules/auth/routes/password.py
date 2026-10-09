from fastapi import APIRouter, Depends, status

from app.core.email import MailerDep
from app.core.openapi import error_responses
from app.core.rate_limit import Limiter, rate_limit
from app.db.session import DbSession
from app.modules.auth.deps import CurrentAuth, CurrentUser
from app.modules.auth.schemas import (
    ChangePasswordRequest,
    EmailRequest,
    ResetPasswordRequest,
    SetPasswordRequest,
)
from app.modules.auth.services import password

router = APIRouter(prefix="/password")


@router.post(
    "/forgot",
    status_code=status.HTTP_202_ACCEPTED,
    summary="Email a password reset link",
    responses=error_responses(422, 429),
    dependencies=[Depends(rate_limit("forgot", 10, 3600))],
)
async def forgot_password(
    payload: EmailRequest, session: DbSession, mailer: MailerDep, limiter: Limiter
) -> dict[str, str]:
    await password.forgot_password(session, mailer, limiter, str(payload.email))
    return {"status": "accepted"}


@router.post(
    "/reset",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Set a new password using a reset token",
    responses=error_responses(400, 422, 429),
    dependencies=[Depends(rate_limit("reset", 10, 3600))],
)
async def reset_password(
    payload: ResetPasswordRequest, session: DbSession, mailer: MailerDep
) -> None:
    await password.reset_password(
        session,
        mailer,
        payload.token,
        payload.new_password,
        payload.mfa_code,
        payload.recovery_code,
    )


@router.post(
    "/change",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Change my password",
    responses=error_responses(400, 401, 409, 422),
    dependencies=[Depends(rate_limit("password-change", 10, 3600))],
)
async def change_password(
    payload: ChangePasswordRequest, auth: CurrentAuth, session: DbSession, mailer: MailerDep
) -> None:
    await password.change_password(
        session,
        mailer,
        auth.user,
        auth.claims.session_id,
        payload.current_password,
        payload.new_password,
    )


@router.post(
    "/set",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Set a first password for an account created with Google",
    responses=error_responses(401, 409, 422),
)
async def set_password(payload: SetPasswordRequest, user: CurrentUser, session: DbSession) -> None:
    await password.set_initial_password(session, user, payload.new_password)
