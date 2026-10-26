"""Read-only client hub endpoints for the API-19 spike.

Mounted only in ``local``/``test``: auth (API-09…13) is paused by ADR-002, so the caller is taken
from ``X-Spike-User-Id`` / ``X-Spike-User-Role`` headers. Responses mirror sgsai-lab/home.
"""

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Header, Query, Response
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import NotFoundError, UnauthenticatedError
from app.db.session import get_session
from app.modules.hub.migration import Row, client_json, product_json, project_etag, project_json
from app.modules.hub.models import HubClient, HubMembership, HubProduct, HubProject

router = APIRouter(tags=["hub-spike"])

Session = Annotated[AsyncSession, Depends(get_session)]


class Viewer(BaseModel):
    id: str
    sgs_admin: bool


def get_viewer(
    user_id: Annotated[str | None, Header(alias="X-Spike-User-Id")] = None,
    role: Annotated[str | None, Header(alias="X-Spike-User-Role")] = None,
) -> Viewer:
    if not user_id:
        raise UnauthenticatedError("Sign in to continue.")
    return Viewer(id=user_id, sgs_admin=role == "admin")


CurrentViewer = Annotated[Viewer, Depends(get_viewer)]


def as_row(model: Any) -> Row:
    return {column.key: getattr(model, column.key) for column in model.__table__.columns}


async def role_in(session: AsyncSession, viewer: Viewer, client_id: str) -> str:
    """Effective workspace role; unknown clients and non-members are indistinguishable (404)."""
    if await session.get(HubClient, client_id) is None:
        raise NotFoundError("Workspace not found.")
    if viewer.sgs_admin:
        return "owner"
    role = await session.scalar(
        select(HubMembership.role).where(
            HubMembership.client_id == client_id,
            HubMembership.user_id == viewer.id,
            HubMembership.status == "active",
        )
    )
    if role is None:
        raise NotFoundError("Workspace not found.")
    return role


@router.get("/clients/{client_id}")
async def get_client(client_id: str, viewer: CurrentViewer, session: Session) -> dict[str, Any]:
    role = await role_in(session, viewer, client_id)
    client = await session.get(HubClient, client_id)
    members = await session.scalar(
        select(func.count())
        .select_from(HubMembership)
        .where(HubMembership.client_id == client_id, HubMembership.status == "active")
    )
    return client_json(as_row(client), role=role, member_count=members or 0)


@router.get("/projects/{project_id}")
async def get_project(
    project_id: str, viewer: CurrentViewer, session: Session, response: Response
) -> dict[str, Any]:
    project = await session.get(HubProject, project_id)
    if project is None or project.deleted_at is not None:
        raise NotFoundError("Project not found.")
    role = await role_in(session, viewer, project.client_id)
    row = as_row(project)
    response.headers["ETag"] = project_etag(row)
    return project_json(row, role=role)


@router.get("/products")
async def list_products(
    viewer: CurrentViewer,
    session: Session,
    client_id: str | None = None,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
) -> dict[str, Any]:
    if client_id:
        roles = {client_id: await role_in(session, viewer, client_id)}
    elif viewer.sgs_admin:
        roles = {cid: "owner" for cid in (await session.scalars(select(HubClient.id))).all()}
    else:
        memberships = await session.execute(
            select(HubMembership.client_id, HubMembership.role).where(
                HubMembership.user_id == viewer.id, HubMembership.status == "active"
            )
        )
        roles = {cid: role for cid, role in memberships}
    query = select(HubProduct).where(HubProduct.client_id.in_(roles))
    total = await session.scalar(select(func.count()).select_from(query.subquery()))
    products = await session.scalars(
        query.order_by(HubProduct.sort_order, HubProduct.id)
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    return {
        "items": [product_json(as_row(p), role=roles[p.client_id]) for p in products],
        "total": total or 0,
        "page": page,
        "page_size": page_size,
    }
