import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import structlog
from sqlalchemy import Select, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import (
    ConflictError,
    NotFoundError,
    PreconditionFailedError,
    ValidationFailedError,
)
from app.core.pagination import escape_like, paginate
from app.modules.projects.models import Project
from app.modules.projects.schemas import ProjectCreate, ProjectFilters, ProjectUpdate
from app.modules.users.models import User

log = structlog.get_logger(__name__)

RESTORE_WINDOW = timedelta(days=30)

_SORT_COLUMNS = {
    "created_at": Project.created_at,
    "name": Project.name,
    "updated_at": Project.updated_at,
}


def _owned_by(owner_id: uuid.UUID) -> Select[Project]:
    return select(Project).where(Project.owner_id == owner_id, Project.deleted_at.is_(None))


def etag(project: Project) -> str:
    return f'"{int(project.updated_at.timestamp() * 1_000_000)}"'


async def get_project(session: AsyncSession, user: User, project_id: uuid.UUID) -> Project:
    project = await session.scalar(_owned_by(user.id).where(Project.id == project_id))
    if project is None:
        raise NotFoundError("Project not found")
    return project


async def list_projects(
    session: AsyncSession, owner_id: uuid.UUID, filters: ProjectFilters
) -> tuple[list[Any], int]:
    stmt = _owned_by(owner_id)
    if filters.status:
        stmt = stmt.where(Project.status == filters.status)
    if filters.tag:
        stmt = stmt.where(Project.tags.contains(filters.tag))
    if filters.q:
        pattern = f"%{escape_like(filters.q)}%"
        stmt = stmt.where(
            or_(
                Project.name.ilike(pattern, escape="\\"),
                Project.description.ilike(pattern, escape="\\"),
            )
        )
    if filters.created_from:
        stmt = stmt.where(Project.created_at >= filters.created_from)
    if filters.created_to:
        stmt = stmt.where(Project.created_at <= filters.created_to)
    column = _SORT_COLUMNS[filters.sort.lstrip("-")]
    order = column.desc() if filters.sort.startswith("-") else column.asc()
    return await paginate(session, stmt.order_by(order, Project.id), filters)


async def create_project(session: AsyncSession, user: User, payload: ProjectCreate) -> Project:
    data = payload.model_dump()
    data["metadata_"] = data.pop("metadata")
    project = Project(owner_id=user.id, **data)
    session.add(project)
    await _commit(session)
    await session.refresh(project)
    log.info("project_created", project_id=str(project.id))
    return project


def _check_if_match(project: Project, if_match: str | None) -> None:
    if if_match is None or if_match.strip() == "*":
        return
    candidates = {tag.strip().removeprefix("W/") for tag in if_match.split(",")}
    if etag(project) not in candidates:
        raise PreconditionFailedError("The project was modified by another request")


async def update_project(
    session: AsyncSession,
    user: User,
    project_id: uuid.UUID,
    payload: ProjectUpdate,
    if_match: str | None = None,
) -> Project:
    project = await get_project(session, user, project_id)
    _check_if_match(project, if_match)
    changes = payload.model_dump(exclude_unset=True)
    if "metadata" in changes:
        changes["metadata_"] = changes.pop("metadata")
    for field, value in changes.items():
        setattr(project, field, value)
    if project.start_date and project.end_date and project.end_date < project.start_date:
        await session.rollback()
        raise ValidationFailedError("end_date", "end_date must be on or after start_date")
    await _commit(session)
    await session.refresh(project)
    log.info("project_updated", project_id=str(project.id))
    return project


async def delete_project(session: AsyncSession, user: User, project_id: uuid.UUID) -> None:
    project = await get_project(session, user, project_id)
    project.deleted_at = datetime.now(UTC)
    await session.commit()
    log.info("project_deleted", project_id=str(project.id))


async def restore_project(session: AsyncSession, user: User, project_id: uuid.UUID) -> Project:
    project = await session.scalar(
        select(Project).where(
            Project.id == project_id,
            Project.owner_id == user.id,
            Project.deleted_at.is_not(None),
            Project.deleted_at >= datetime.now(UTC) - RESTORE_WINDOW,
        )
    )
    if project is None:
        raise NotFoundError("Project not found")
    project.deleted_at = None
    await _commit(session)
    await session.refresh(project)
    log.info("project_restored", project_id=str(project.id))
    return project


async def _commit(session: AsyncSession) -> None:
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise ConflictError("A project with this name already exists") from exc
