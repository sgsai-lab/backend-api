from typing import Any

from pydantic import BaseModel, Field


class ErrorDetail(BaseModel):
    field: str | None = None
    message: str


class ErrorBody(BaseModel):
    code: str = Field(examples=["RESOURCE_NOT_FOUND"])
    message: str
    request_id: str | None = Field(alias="requestId")
    details: list[ErrorDetail]


class ErrorEnvelope(BaseModel):
    error: ErrorBody


_DESCRIPTIONS = {
    400: "Bad request",
    401: "Missing, invalid or expired credentials",
    403: "Forbidden",
    404: "Resource not found",
    409: "Conflict",
    412: "Precondition failed (stale If-Match)",
    422: "Validation error",
    429: "Rate limited",
}


def error_responses(*status_codes: int) -> dict[int | str, dict[str, Any]]:
    return {
        code: {"model": ErrorEnvelope, "description": _DESCRIPTIONS[code]} for code in status_codes
    }
