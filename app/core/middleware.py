import re
import time
import uuid
from collections.abc import Awaitable, Callable

import structlog
from fastapi import Request, Response
from fastapi.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.core.config import get_settings
from app.core.errors import error_body

log = structlog.get_logger("app.request")

_VALID_REQUEST_ID = re.compile(r"^[A-Za-z0-9._-]{1,64}$")
_CLOUD_TRACE = re.compile(r"^([0-9a-f]{32})(?:/\d+)?(?:;o=\d)?$")
_SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Strict-Transport-Security": "max-age=63072000; includeSubDomains",
}
_NO_STORE_PREFIXES = ("/api/v1/auth", "/api/v1/users/me")


def _bind_trace(request: Request) -> None:
    project_id = get_settings().gcp_project_id
    match = _CLOUD_TRACE.match(request.headers.get("x-cloud-trace-context", ""))
    if project_id and match:
        structlog.contextvars.bind_contextvars(
            **{"logging.googleapis.com/trace": f"projects/{project_id}/traces/{match.group(1)}"}
        )


async def request_context_middleware(
    request: Request, call_next: Callable[[Request], Awaitable[Response]]
) -> Response:
    incoming = request.headers.get("x-request-id", "")
    request_id = incoming if _VALID_REQUEST_ID.match(incoming) else uuid.uuid4().hex
    request.state.request_id = request_id

    structlog.contextvars.clear_contextvars()
    structlog.contextvars.bind_contextvars(request_id=request_id)
    _bind_trace(request)

    start = time.perf_counter()
    response = await call_next(request)
    log.info(
        "request",
        method=request.method,
        path=request.url.path,
        status_code=response.status_code,
        latency_ms=round((time.perf_counter() - start) * 1000, 2),
    )
    response.headers["X-Request-ID"] = request_id
    response.headers.update(_SECURITY_HEADERS)
    if request.url.path.startswith(_NO_STORE_PREFIXES):
        response.headers["Cache-Control"] = "no-store"
    return response


class BodySizeLimitMiddleware:
    """Rejects bodies over `max_bytes` with 413, by Content-Length or while streaming."""

    def __init__(self, app: ASGIApp, max_bytes: int) -> None:
        self.app = app
        self.max_bytes = max_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        declared = dict(scope["headers"]).get(b"content-length")
        if declared is not None and declared.isdigit() and int(declared) > self.max_bytes:
            await self._reject(scope, receive, send)
            return

        received = 0
        too_large = False

        async def limited_receive() -> Message:
            nonlocal received, too_large
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > self.max_bytes:
                    # Truncate the stream; the app's response is swapped for a 413 in guarded_send.
                    too_large = True
                    return {"type": "http.request", "body": b"", "more_body": False}
            return message

        async def guarded_send(message: Message) -> None:
            if not too_large:
                await send(message)
            elif message["type"] == "http.response.start":
                await self._reject(scope, receive, send)

        await self.app(scope, limited_receive, guarded_send)

    @staticmethod
    async def _reject(scope: Scope, receive: Receive, send: Send) -> None:
        response = JSONResponse(
            status_code=413,
            content=error_body(None, "PAYLOAD_TOO_LARGE", "Request body too large", []),
        )
        await response(scope, receive, send)
