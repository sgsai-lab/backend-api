import uuid
from typing import Annotated

from fastapi import APIRouter, Query, Response, status

from app.core.email import MailerDep
from app.core.openapi import error_responses
from app.core.pagination import Page
from app.db.session import DbSession
from app.modules.auth.deps import AdminUser, CurrentUser
from app.modules.auth.schemas import ReauthRequest
from app.modules.users import service
from app.modules.users.schemas import (
    AdminUserCreate,
    AdminUserUpdate,
    UserListParams,
    UserRead,
    UserUpdateMe,
)

router = APIRouter(prefix="/users", tags=["users"])

_ADMIN_ERRORS = error_responses(401, 403, 404, 422)


@router.get("/me", summary="Get my profile", responses=error_responses(401))
async def get_me(user: CurrentUser) -> UserRead:
    return UserRead.model_validate(user)


@router.patch("/me", summary="Update my profile", responses=error_responses(401, 422))
async def update_me(payload: UserUpdateMe, user: CurrentUser, session: DbSession) -> UserRead:
    return UserRead.model_validate(await service.update_me(session, user, payload))


@router.delete(
    "/me",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete my account (requires re-authentication)",
    responses=error_responses(401, 403, 422),
)
async def delete_me(payload: ReauthRequest, user: CurrentUser, session: DbSession) -> None:
    await service.delete_me(session, user, payload.password, payload.code)


@router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    summary="Create a user and email an invitation (admin)",
    responses={**_ADMIN_ERRORS, **error_responses(409)},
)
async def create_user(
    payload: AdminUserCreate,
    _: AdminUser,
    session: DbSession,
    mailer: MailerDep,
    response: Response,
) -> UserRead:
    user = await service.create_user(session, mailer, payload)
    response.headers["Location"] = f"/api/v1/users/{user.id}"
    return UserRead.model_validate(user)


@router.get("", summary="List users (admin)", responses=_ADMIN_ERRORS)
async def list_users(
    _: AdminUser, session: DbSession, params: Annotated[UserListParams, Query()]
) -> Page[UserRead]:
    items, total = await service.list_users(session, params)
    return Page[UserRead](
        items=[UserRead.model_validate(u) for u in items],
        total=total,
        page=params.page,
        page_size=params.page_size,
    )


@router.get("/{user_id}", summary="Get a user (admin)", responses=_ADMIN_ERRORS)
async def get_user(user_id: uuid.UUID, _: AdminUser, session: DbSession) -> UserRead:
    return UserRead.model_validate(await service.get_user(session, user_id))


@router.patch(
    "/{user_id}",
    summary="Update a user's name, role or status (admin)",
    responses={**_ADMIN_ERRORS, **error_responses(409)},
)
async def update_user(
    user_id: uuid.UUID, payload: AdminUserUpdate, admin: AdminUser, session: DbSession
) -> UserRead:
    return UserRead.model_validate(
        await service.admin_update_user(session, admin, user_id, payload)
    )


@router.delete(
    "/{user_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a user (admin)",
    responses={**_ADMIN_ERRORS, **error_responses(409)},
)
async def delete_user(user_id: uuid.UUID, admin: AdminUser, session: DbSession) -> None:
    await service.admin_delete_user(session, admin, user_id)
