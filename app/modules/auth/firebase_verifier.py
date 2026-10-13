from dataclasses import dataclass
from functools import lru_cache
from typing import Any

import firebase_admin
from firebase_admin import auth
from firebase_admin.exceptions import FirebaseError
from google.auth.exceptions import DefaultCredentialsError
from starlette.concurrency import run_in_threadpool

from app.core.config import get_settings
from app.core.errors import AppError, UnauthenticatedError


@dataclass(frozen=True)
class FirebaseIdentity:
    uid: str
    email: str
    name: str | None
    picture: str | None
    auth_time: int
    mfa_enabled: bool


@lru_cache(maxsize=4)
def _admin_app(project_id: str) -> firebase_admin.App:
    try:
        return firebase_admin.get_app(project_id)
    except ValueError:
        try:
            return firebase_admin.initialize_app(
                options={"projectId": project_id},
                name=project_id,
            )
        except ValueError:
            return firebase_admin.get_app(project_id)


class FirebaseTokenVerifier:
    def __init__(self, project_id: str | None) -> None:
        self._project_id = project_id

    @property
    def is_configured(self) -> bool:
        return self._project_id is not None

    async def verify(self, id_token: str) -> FirebaseIdentity:
        if self._project_id is None:
            raise AppError(
                "Firebase sign-in is not configured",
                code="FIREBASE_SIGNIN_UNAVAILABLE",
            )
        try:
            app = _admin_app(self._project_id)
            claims: dict[str, Any] = await run_in_threadpool(
                auth.verify_id_token,
                id_token,
                app=app,
                check_revoked=True,
            )
            uid = str(claims.get("uid") or claims["sub"])
            email = claims.get("email")
            auth_time = claims.get("auth_time")
            if (
                not uid
                or not isinstance(email, str)
                or claims.get("email_verified") is not True
                or not isinstance(auth_time, int)
            ):
                raise ValueError("Required verified Firebase claims are missing")
            firebase_claims = claims.get("firebase")
            second_factor = (
                firebase_claims.get("sign_in_second_factor")
                if isinstance(firebase_claims, dict)
                else None
            )
            return FirebaseIdentity(
                uid=uid,
                email=email,
                name=claims.get("name") if isinstance(claims.get("name"), str) else None,
                picture=claims.get("picture") if isinstance(claims.get("picture"), str) else None,
                auth_time=auth_time,
                mfa_enabled=isinstance(second_factor, str) and bool(second_factor),
            )
        except AppError:
            raise
        except (FirebaseError, DefaultCredentialsError, KeyError, TypeError, ValueError) as exc:
            raise UnauthenticatedError("Invalid Firebase ID token") from exc

    async def revoke(self, uid: str) -> None:
        if self._project_id is None:
            raise AppError(
                "Firebase sign-in is not configured",
                code="FIREBASE_SIGNIN_UNAVAILABLE",
            )
        try:
            app = _admin_app(self._project_id)
            await run_in_threadpool(auth.revoke_refresh_tokens, uid, app=app)
        except (FirebaseError, DefaultCredentialsError) as exc:
            raise UnauthenticatedError("Could not revoke the Firebase session") from exc


@lru_cache
def get_firebase_verifier() -> FirebaseTokenVerifier:
    return FirebaseTokenVerifier(get_settings().firebase_project_id)
