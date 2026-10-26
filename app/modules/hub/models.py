"""PostgreSQL schema for the client hub (API-19 spike, home ADR-002 exit path).

Mirrors the Firestore collections owned by sgsai-lab/home (docs/data-model.md) so the
``/api/v1`` contract can move to this service by switching ``API_UPSTREAM``. Document ids
are kept as primary keys so URLs, ETags and audit references stay valid after cut-over.
``user_id`` columns carry no foreign key yet: the users table arrives with API-06.
"""

from datetime import date, datetime
from typing import Any

from sqlalchemy import Date, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base

ID = String(64)


class HubClient(Base):
    __tablename__ = "clients"

    id: Mapped[str] = mapped_column(ID, primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    slug: Mapped[str] = mapped_column(String(60), unique=True)
    primary_sector: Mapped[str] = mapped_column(String(20))
    status: Mapped[str] = mapped_column(String(20))
    contact: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    branding: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    created_by: Mapped[str | None] = mapped_column(ID)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class HubMembership(Base):
    __tablename__ = "memberships"
    client_id: Mapped[str] = mapped_column(
        ID, ForeignKey("clients.id", ondelete="CASCADE"), primary_key=True
    )
    user_id: Mapped[str] = mapped_column(ID, primary_key=True, index=True)
    role: Mapped[str] = mapped_column(String(20))
    status: Mapped[str] = mapped_column(String(20))
    invited_by: Mapped[str | None] = mapped_column(ID)
    joined_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class HubProject(Base):
    __tablename__ = "projects"

    id: Mapped[str] = mapped_column(ID, primary_key=True)
    client_id: Mapped[str] = mapped_column(
        ID, ForeignKey("clients.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(120))
    summary: Mapped[str | None] = mapped_column(Text)
    sector: Mapped[str] = mapped_column(String(20))
    status: Mapped[str] = mapped_column(String(20))
    tags: Mapped[list[str]] = mapped_column(ARRAY(String(32)), default=list)
    start_date: Mapped[date | None] = mapped_column(Date)
    end_date: Mapped[date | None] = mapped_column(Date)
    sector_profile: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    milestones: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list)
    cover_asset_id: Mapped[str | None] = mapped_column(ID)
    owner_user_id: Mapped[str | None] = mapped_column(ID)
    version: Mapped[int] = mapped_column(Integer, default=1)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_by: Mapped[str | None] = mapped_column(ID)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class HubProduct(Base):
    __tablename__ = "products"

    id: Mapped[str] = mapped_column(ID, primary_key=True)
    client_id: Mapped[str] = mapped_column(
        ID, ForeignKey("clients.id", ondelete="CASCADE"), index=True
    )
    project_id: Mapped[str | None] = mapped_column(
        ID, ForeignKey("projects.id", ondelete="SET NULL")
    )
    kind: Mapped[str] = mapped_column(String(20))
    name: Mapped[str] = mapped_column(String(120))
    slug: Mapped[str] = mapped_column(String(60), unique=True)
    summary: Mapped[str | None] = mapped_column(Text)
    launch_url: Mapped[str | None] = mapped_column(String(500))
    store_urls: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    icon_asset_id: Mapped[str | None] = mapped_column(ID)
    public_icon_url: Mapped[str | None] = mapped_column(String(500))
    status: Mapped[str] = mapped_column(String(20))
    visibility: Mapped[str] = mapped_column(String(20))
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class HubAsset(Base):
    __tablename__ = "assets"

    id: Mapped[str] = mapped_column(ID, primary_key=True)
    client_id: Mapped[str] = mapped_column(
        ID, ForeignKey("clients.id", ondelete="CASCADE"), index=True
    )
    owner_type: Mapped[str] = mapped_column(String(20))
    owner_id: Mapped[str] = mapped_column(ID, index=True)
    purpose: Mapped[str] = mapped_column(String(20))
    kind: Mapped[str] = mapped_column(String(20))
    filename: Mapped[str] = mapped_column(String(200))
    alt_text: Mapped[str | None] = mapped_column(String(300))
    content_type: Mapped[str] = mapped_column(String(120))
    size_bytes: Mapped[int] = mapped_column(Integer)
    gcs_bucket: Mapped[str] = mapped_column(String(100))
    gcs_object: Mapped[str] = mapped_column(String(500))
    status: Mapped[str] = mapped_column(String(20))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
