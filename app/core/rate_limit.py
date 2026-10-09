import time
from collections.abc import Awaitable, Callable
from functools import lru_cache
from typing import Annotated

from fastapi import Depends, Request

from app.core.config import get_settings
from app.core.errors import RateLimitedError

_PRUNE_THRESHOLD = 10_000


class RateLimiter:
    """Fixed-window limiter, in-memory per instance. Redis-backed variant: API-16."""

    def __init__(self, enabled: bool = True) -> None:
        self.enabled = enabled
        self._windows: dict[str, tuple[float, int]] = {}

    def hit(self, key: str, limit: int, window_seconds: int) -> None:
        if not self.enabled:
            return
        now = time.monotonic()
        if len(self._windows) > _PRUNE_THRESHOLD:
            self._prune(now)
        reset_at, count = self._windows.get(key, (now + window_seconds, 0))
        if reset_at <= now:
            reset_at, count = now + window_seconds, 0
        if count >= limit:
            raise RateLimitedError(int(reset_at - now) + 1)
        self._windows[key] = (reset_at, count + 1)

    def reset(self) -> None:
        self._windows.clear()

    def _prune(self, now: float) -> None:
        self._windows = {k: v for k, v in self._windows.items() if v[0] > now}


@lru_cache
def get_rate_limiter() -> RateLimiter:
    return RateLimiter(enabled=get_settings().rate_limit_enabled)


Limiter = Annotated[RateLimiter, Depends(get_rate_limiter)]


def client_ip(request: Request) -> str:
    # Uvicorn runs with proxy_headers, so request.client is the real caller behind Cloud Run.
    return request.client.host if request.client else "unknown"


def rate_limit(scope: str, limit: int, window_seconds: int) -> Callable[..., Awaitable[None]]:
    async def dependency(request: Request, limiter: Limiter) -> None:
        limiter.hit(f"{scope}:ip:{client_ip(request)}", limit, window_seconds)

    return dependency
