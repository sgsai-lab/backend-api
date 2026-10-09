from fastapi import APIRouter, Depends, status

from app.core.email import MailerDep
from app.core.openapi import error_responses
from app.core.rate_limit import Limiter, rate_limit
from app.db.session import DbSession
from app.modules.auth.schemas import EmailRequest, SignupRequest, SignupResponse, TokenRequest
from app.modules.auth.services import registration

router = APIRouter()


@router.post(
    "/signup",
    status_code=status.HTTP_201_CREATED,
    summary="Create an account with email and password",
    responses=error_responses(422, 429),
    dependencies=[Depends(rate_limit("signup", 5, 3600))],
)
async def signup(payload: SignupRequest, session: DbSession, mailer: MailerDep) -> SignupResponse:
    result = await registration.signup(
        session, mailer, str(payload.email), payload.password, payload.full_name
    )
    return SignupResponse(
        id=result.id,
        email=result.email,
        full_name=result.full_name,
        email_verified=result.email_verified,
    )


@router.post(
    "/verify-email",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Verify an email address with the emailed token",
    responses=error_responses(400, 422, 429),
    dependencies=[Depends(rate_limit("verify-email", 20, 3600))],
)
async def verify_email(payload: TokenRequest, session: DbSession) -> None:
    await registration.verify_email(session, payload.token)


@router.post(
    "/verify-email/resend",
    status_code=status.HTTP_202_ACCEPTED,
    summary="Resend the verification email",
    responses=error_responses(422, 429),
    dependencies=[Depends(rate_limit("verify-resend", 10, 3600))],
)
async def resend_verification(
    payload: EmailRequest, session: DbSession, mailer: MailerDep, limiter: Limiter
) -> dict[str, str]:
    await registration.resend_verification(session, mailer, limiter, str(payload.email))
    return {"status": "accepted"}
