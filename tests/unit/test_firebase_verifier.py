from typing import Any

import pytest
from firebase_admin import App

from app.core.errors import AppError, UnauthenticatedError
from app.modules.auth.firebase_verifier import FirebaseTokenVerifier


async def test_firebase_verifier_binds_to_project_and_checks_revocation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = object()
    received: dict[str, Any] = {}

    monkeypatch.setattr(
        "app.modules.auth.firebase_verifier._admin_app",
        lambda project_id: app,
    )

    def verify_id_token(token: str, *, app: App, check_revoked: bool) -> dict[str, Any]:
        received.update(token=token, app=app, check_revoked=check_revoked)
        return {
            "uid": "firebase-uid",
            "email": "verified@example.com",
            "email_verified": True,
            "name": "Verified User",
            "auth_time": 123,
            "firebase": {"sign_in_second_factor": "phone"},
        }

    monkeypatch.setattr(
        "app.modules.auth.firebase_verifier.auth.verify_id_token",
        verify_id_token,
    )

    identity = await FirebaseTokenVerifier("sgsai-test").verify("signed-id-token")

    assert received == {
        "token": "signed-id-token",
        "app": app,
        "check_revoked": True,
    }
    assert identity.uid == "firebase-uid"
    assert identity.email == "verified@example.com"
    assert identity.auth_time == 123
    assert identity.mfa_enabled is True


async def test_firebase_verifier_rejects_unverified_email(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "app.modules.auth.firebase_verifier._admin_app",
        lambda project_id: object(),
    )
    monkeypatch.setattr(
        "app.modules.auth.firebase_verifier.auth.verify_id_token",
        lambda *args, **kwargs: {
            "uid": "firebase-uid",
            "email": "unverified@example.com",
            "email_verified": False,
            "auth_time": 123,
        },
    )

    with pytest.raises(UnauthenticatedError):
        await FirebaseTokenVerifier("sgsai-test").verify("signed-id-token")


async def test_firebase_verifier_fails_closed_without_project_id() -> None:
    with pytest.raises(AppError) as error:
        await FirebaseTokenVerifier(None).verify("signed-id-token")

    assert error.value.code == "FIREBASE_SIGNIN_UNAVAILABLE"
