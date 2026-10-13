from typing import Annotated

from fastapi import APIRouter, Depends

from app.core.openapi import error_responses
from app.core.rate_limit import rate_limit
from app.db.session import DbSession
from app.modules.auth.firebase_verifier import FirebaseTokenVerifier, get_firebase_verifier
from app.modules.auth.schemas import FirebaseRequest
from app.modules.auth.services.firebase import sign_in_with_firebase
from app.modules.users.schemas import UserRead

router = APIRouter()

Verifier = Annotated[FirebaseTokenVerifier, Depends(get_firebase_verifier)]


@router.post(
    "/firebase",
    response_model=UserRead,
    summary="Link or provision the user for a verified Firebase ID token",
    responses=error_responses(400, 401, 409, 422, 429),
    dependencies=[Depends(rate_limit("firebase", 10, 60))],
)
async def firebase_sign_in(
    payload: FirebaseRequest, session: DbSession, verifier: Verifier
) -> UserRead:
    identity = await verifier.verify(payload.id_token)
    user = await sign_in_with_firebase(session, identity)
    return UserRead.model_validate(user)
