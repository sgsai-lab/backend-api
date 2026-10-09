import uuid
from typing import Annotated

from fastapi import APIRouter, Header, Query, Response, status

from app.core.openapi import error_responses
from app.core.pagination import Page
from app.db.session import DbSession
from app.modules.auth.deps import CurrentAuth, CurrentUser, VerifiedUser, require_admin
from app.modules.projects import service
from app.modules.projects.schemas import (
    ProjectCreate,
    ProjectFilters,
    ProjectRead,
    ProjectUpdate,
)

router = APIRouter(prefix="/projects", tags=["projects"])

_ERRORS = error_responses(401, 404, 422)
_WRITE_ERRORS = error_responses(401, 403, 404, 409, 422)


@router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    summary="Create a project",
    responses=error_responses(401, 403, 409, 422),
)
async def create_project(
    payload: ProjectCreate, user: VerifiedUser, session: DbSession, response: Response
) -> ProjectRead:
    project = await service.create_project(session, user, payload)
    response.headers["Location"] = f"/api/v1/projects/{project.id}"
    response.headers["ETag"] = service.etag(project)
    return ProjectRead.model_validate(project)


@router.get(
    "",
    summary="List my projects (admins may pass owner_id)",
    responses=error_responses(401, 403, 422),
)
async def list_projects(
    auth: CurrentAuth, session: DbSession, filters: Annotated[ProjectFilters, Query()]
) -> Page[ProjectRead]:
    owner_id = auth.user.id
    if filters.owner_id is not None and filters.owner_id != auth.user.id:
        await require_admin(auth)
        owner_id = filters.owner_id
    items, total = await service.list_projects(session, owner_id, filters)
    return Page[ProjectRead](
        items=[ProjectRead.model_validate(p) for p in items],
        total=total,
        page=filters.page,
        page_size=filters.page_size,
    )


@router.get("/{project_id}", summary="Get one of my projects", responses=_ERRORS)
async def get_project(
    project_id: uuid.UUID, user: CurrentUser, session: DbSession, response: Response
) -> ProjectRead:
    project = await service.get_project(session, user, project_id)
    response.headers["ETag"] = service.etag(project)
    return ProjectRead.model_validate(project)


@router.patch(
    "/{project_id}",
    summary="Update a project (optional If-Match for optimistic concurrency)",
    responses={**_WRITE_ERRORS, **error_responses(412)},
)
async def update_project(
    project_id: uuid.UUID,
    payload: ProjectUpdate,
    user: VerifiedUser,
    session: DbSession,
    response: Response,
    if_match: Annotated[str | None, Header()] = None,
) -> ProjectRead:
    project = await service.update_project(session, user, project_id, payload, if_match)
    response.headers["ETag"] = service.etag(project)
    return ProjectRead.model_validate(project)


@router.delete(
    "/{project_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a project (restorable for 30 days)",
    responses=error_responses(401, 403, 404),
)
async def delete_project(project_id: uuid.UUID, user: VerifiedUser, session: DbSession) -> None:
    await service.delete_project(session, user, project_id)


@router.post(
    "/{project_id}/restore",
    summary="Restore a project deleted within the last 30 days",
    responses=_WRITE_ERRORS,
)
async def restore_project(
    project_id: uuid.UUID, user: VerifiedUser, session: DbSession, response: Response
) -> ProjectRead:
    project = await service.restore_project(session, user, project_id)
    response.headers["ETag"] = service.etag(project)
    return ProjectRead.model_validate(project)
