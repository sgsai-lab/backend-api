import re
import time
import uuid
from collections.abc import Awaitable, Callable

import structlog
from fastapi import Request, Response

log = structlog.get_logger("app.request")

_VALID_REQUEST_ID = re.compile(r"^[A-Za-z0-9._-]{1,64}$")


async def request_context_middleware(
    request: Request, call_next: Callable[[Request], Awaitable[Response]]
) -> Response:
    incoming = request.headers.get("x-request-id", "")
    request_id = incoming if _VALID_REQUEST_ID.match(incoming) else uuid.uuid4().hex
    request.state.request_id = request_id

    structlog.contextvars.clear_contextvars()
    structlog.contextvars.bind_contextvars(request_id=request_id)

    start = time.perf_counter()
    response = await call_next(request)
    route = request.scope.get("route")
    log.info(
        "request",
        method=request.method,
        route=getattr(route, "path", request.url.path),
        status_code=response.status_code,
        latency_ms=round((time.perf_counter() - start) * 1000, 2),
    )
    response.headers["X-Request-ID"] = request_id
    return response
