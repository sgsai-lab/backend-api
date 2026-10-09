from collections.abc import Mapping
from typing import Any, ClassVar

import structlog
from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

log = structlog.get_logger(__name__)


class AppError(Exception):
    status_code: ClassVar[int] = status.HTTP_400_BAD_REQUEST
    code: str = "BAD_REQUEST"

    def __init__(
        self,
        message: str,
        *,
        code: str | None = None,
        details: list[dict[str, Any]] | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        if code:
            self.code = code
        self.details = details or []
        self.headers = dict(headers or {})


class UnauthenticatedError(AppError):
    status_code = status.HTTP_401_UNAUTHORIZED
    code = "UNAUTHENTICATED"

    def __init__(
        self, message: str = "Authentication required", *, code: str | None = None
    ) -> None:
        super().__init__(message, code=code, headers={"WWW-Authenticate": "Bearer"})


class InvalidCredentialsError(UnauthenticatedError):
    def __init__(self) -> None:
        super().__init__("Invalid email or password", code="INVALID_CREDENTIALS")


class InvalidTokenError(AppError):
    code = "INVALID_TOKEN"

    def __init__(self, message: str = "The token is invalid or has expired") -> None:
        super().__init__(message)


class ForbiddenError(AppError):
    status_code = status.HTTP_403_FORBIDDEN
    code = "FORBIDDEN"


class NotFoundError(AppError):
    status_code = status.HTTP_404_NOT_FOUND
    code = "RESOURCE_NOT_FOUND"


class ConflictError(AppError):
    status_code = status.HTTP_409_CONFLICT
    code = "CONFLICT"


class ValidationFailedError(AppError):
    status_code = status.HTTP_422_UNPROCESSABLE_CONTENT
    code = "VALIDATION_ERROR"

    def __init__(self, field: str, message: str) -> None:
        super().__init__(
            "Request validation failed", details=[{"field": field, "message": message}]
        )


class RateLimitedError(AppError):
    status_code = status.HTTP_429_TOO_MANY_REQUESTS
    code = "RATE_LIMITED"

    def __init__(self, retry_after: int) -> None:
        super().__init__(
            "Too many requests, please retry later",
            headers={"Retry-After": str(max(retry_after, 1))},
        )


_HTTP_CODES = {
    401: "UNAUTHENTICATED",
    403: "FORBIDDEN",
    404: "RESOURCE_NOT_FOUND",
    405: "METHOD_NOT_ALLOWED",
    413: "PAYLOAD_TOO_LARGE",
    429: "RATE_LIMITED",
}


def error_body(
    request_id: str | None, code: str, message: str, details: list[dict[str, Any]]
) -> dict[str, Any]:
    return {
        "error": {"code": code, "message": message, "requestId": request_id, "details": details}
    }


def error_response(
    request: Request,
    status_code: int,
    code: str,
    message: str,
    details: list[dict[str, Any]] | None = None,
    headers: Mapping[str, str] | None = None,
) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        headers=headers,
        content=error_body(
            getattr(request.state, "request_id", None), code, message, details or []
        ),
    )


async def _app_error(request: Request, exc: AppError) -> JSONResponse:
    return error_response(
        request, exc.status_code, exc.code, exc.message, exc.details, exc.headers or None
    )


async def _validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
    # Never echo the submitted input back: it may contain passwords or tokens.
    details = [
        {"field": ".".join(str(p) for p in err["loc"]), "message": err["msg"]}
        for err in exc.errors()
    ]
    return error_response(request, 422, "VALIDATION_ERROR", "Request validation failed", details)


async def _http_error(request: Request, exc: StarletteHTTPException) -> JSONResponse:
    return error_response(
        request,
        exc.status_code,
        _HTTP_CODES.get(exc.status_code, "HTTP_ERROR"),
        str(exc.detail),
        headers=exc.headers,
    )


async def _unhandled_error(request: Request, exc: Exception) -> JSONResponse:
    log.exception("unhandled_error", exc_type=type(exc).__name__)
    return error_response(request, 500, "INTERNAL_ERROR", "An unexpected error occurred")


def register_exception_handlers(app: FastAPI) -> None:
    app.exception_handler(AppError)(_app_error)
    app.exception_handler(RequestValidationError)(_validation_error)
    app.exception_handler(StarletteHTTPException)(_http_error)
    app.exception_handler(Exception)(_unhandled_error)
