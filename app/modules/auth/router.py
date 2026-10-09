from typing import Any

from fastapi import APIRouter

from app.core.tokens import jwks
from app.modules.auth.routes import apple, google, login, mfa, password, registration

router = APIRouter(prefix="/auth", tags=["auth"])
for module in (registration, login, google, apple, password, mfa):
    router.include_router(module.router)

well_known_router = APIRouter(tags=["auth"])


@well_known_router.get("/.well-known/jwks.json", summary="Public keys for verifying access tokens")
async def get_jwks() -> dict[str, list[dict[str, Any]]]:
    return jwks()
