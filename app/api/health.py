import asyncio

import structlog
from fastapi import APIRouter, Response, status
from sqlalchemy import text

from app.db.session import get_engine

router = APIRouter(tags=["health"])
log = structlog.get_logger(__name__)


@router.get("/healthz")
async def healthz() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/readyz")
async def readyz(response: Response) -> dict[str, str]:
    try:
        async with asyncio.timeout(2):
            async with get_engine().connect() as conn:
                await conn.execute(text("SELECT 1"))
    except Exception as exc:
        log.warning("readiness_check_failed", exc_type=type(exc).__name__)
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return {"status": "unavailable"}
    return {"status": "ok"}
