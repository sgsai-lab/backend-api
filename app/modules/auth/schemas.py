import uuid
from datetime import datetime
from typing import Annotated, Literal, Self

from pydantic import (
    BaseModel,
    ConfigDict,
    EmailStr,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
)

Password = Annotated[str, Field(min_length=1, max_length=128)]
NewPassword = Annotated[str, Field(min_length=10, max_length=128)]
OpaqueToken = Annotated[str, Field(min_length=16, max_length=256)]
TotpCode = Annotated[str, Field(pattern=r"^\d{6}$")]
RecoveryCode = Annotated[str, Field(min_length=10, max_length=20)]
FullName = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=120)]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SignupRequest(StrictModel):
    email: EmailStr
    password: NewPassword
    full_name: FullName
    accept_terms: bool

    @field_validator("accept_terms")
    @classmethod
    def _terms_accepted(cls, value: bool) -> bool:
        if not value:
            raise ValueError("Terms must be accepted")
        return value


class SignupResponse(BaseModel):
    id: uuid.UUID
    email: str
    full_name: str
    email_verified: bool


class TokenRequest(StrictModel):
    token: OpaqueToken


class EmailRequest(StrictModel):
    email: EmailStr


class LoginRequest(StrictModel):
    email: EmailStr
    password: Password


class TokenResponse(BaseModel):
    access_token: str
    token_type: Literal["Bearer"] = "Bearer"  # noqa: S105 - OAuth token type, not a secret
    expires_in: int
    refresh_token: str | None = Field(
        default=None, description="Omitted for web clients, which receive an HttpOnly cookie"
    )


class MfaChallengeResponse(BaseModel):
    mfa_required: Literal[True] = True
    mfa_token: str
    methods: list[str] = ["totp", "recovery_code"]


class RefreshRequest(StrictModel):
    refresh_token: OpaqueToken | None = None


class SessionRead(BaseModel):
    id: uuid.UUID
    started_at: datetime
    last_used_at: datetime
    expires_at: datetime
    ip: str | None
    user_agent: str | None
    current: bool


class GoogleRequest(StrictModel):
    id_token: Annotated[str, Field(min_length=20, max_length=4096)]
    nonce: Annotated[str, Field(max_length=256)] | None = None


class ResetPasswordRequest(StrictModel):
    token: OpaqueToken
    new_password: NewPassword
    mfa_code: TotpCode | None = None
    recovery_code: RecoveryCode | None = None


class ChangePasswordRequest(StrictModel):
    current_password: Password
    new_password: NewPassword


class SetPasswordRequest(StrictModel):
    new_password: NewPassword


class MfaStatusResponse(BaseModel):
    available: bool = Field(description="Whether new MFA enrolment is enabled on this server")
    enabled: bool
    methods: list[str]
    recovery_codes_remaining: int


class TotpSetupResponse(BaseModel):
    secret: str
    otpauth_uri: str


class TotpCodeRequest(StrictModel):
    code: TotpCode


class RecoveryCodesResponse(BaseModel):
    recovery_codes: list[str]


class MfaVerifyRequest(StrictModel):
    mfa_token: OpaqueToken
    code: TotpCode | None = None
    recovery_code: RecoveryCode | None = None

    @model_validator(mode="after")
    def _exactly_one_factor(self) -> Self:
        if (self.code is None) == (self.recovery_code is None):
            raise ValueError("Provide exactly one of code or recovery_code")
        return self


class ReauthRequest(StrictModel):
    password: Password | None = None
    code: TotpCode | None = None
