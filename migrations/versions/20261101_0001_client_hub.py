"""client hub tables mirroring home Firestore (API-19 spike)

Revision ID: 0001_client_hub
Revises:
Create Date: 2026-11-01
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001_client_hub"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

ID = sa.String(64)
TS = sa.DateTime(timezone=True)
JSON_OBJECT = sa.text("'{}'::jsonb")


def upgrade() -> None:
    op.create_table(
        "clients",
        sa.Column("id", ID, primary_key=True),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("slug", sa.String(60), nullable=False),
        sa.Column("primary_sector", sa.String(20), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("contact", postgresql.JSONB(), nullable=False, server_default=JSON_OBJECT),
        sa.Column("branding", postgresql.JSONB(), nullable=False, server_default=JSON_OBJECT),
        sa.Column("created_by", ID),
        sa.Column("created_at", TS, nullable=False),
        sa.Column("updated_at", TS, nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_clients")),
        sa.UniqueConstraint("slug", name=op.f("uq_clients_slug")),
    )
    op.create_table(
        "memberships",
        sa.Column("client_id", ID, nullable=False),
        sa.Column("user_id", ID, nullable=False),
        sa.Column("role", sa.String(20), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("invited_by", ID),
        sa.Column("joined_at", TS),
        sa.ForeignKeyConstraint(
            ["client_id"],
            ["clients.id"],
            name=op.f("fk_memberships_client_id_clients"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("client_id", "user_id", name=op.f("pk_memberships")),
    )
    op.create_index(op.f("ix_memberships_user_id"), "memberships", ["user_id"])
    op.create_table(
        "projects",
        sa.Column("id", ID, nullable=False),
        sa.Column("client_id", ID, nullable=False),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("summary", sa.Text()),
        sa.Column("sector", sa.String(20), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column(
            "tags",
            postgresql.ARRAY(sa.String(32)),
            nullable=False,
            server_default=sa.text("'{}'::varchar[]"),
        ),
        sa.Column("start_date", sa.Date()),
        sa.Column("end_date", sa.Date()),
        sa.Column("sector_profile", postgresql.JSONB()),
        sa.Column(
            "milestones", postgresql.JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")
        ),
        sa.Column("cover_asset_id", ID),
        sa.Column("owner_user_id", ID),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("deleted_at", TS),
        sa.Column("created_by", ID),
        sa.Column("created_at", TS, nullable=False),
        sa.Column("updated_at", TS, nullable=False),
        sa.ForeignKeyConstraint(
            ["client_id"],
            ["clients.id"],
            name=op.f("fk_projects_client_id_clients"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_projects")),
    )
    op.create_index(op.f("ix_projects_client_id"), "projects", ["client_id"])
    op.create_table(
        "products",
        sa.Column("id", ID, nullable=False),
        sa.Column("client_id", ID, nullable=False),
        sa.Column("project_id", ID),
        sa.Column("kind", sa.String(20), nullable=False),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("slug", sa.String(60), nullable=False),
        sa.Column("summary", sa.Text()),
        sa.Column("launch_url", sa.String(500)),
        sa.Column("store_urls", postgresql.JSONB(), nullable=False, server_default=JSON_OBJECT),
        sa.Column("icon_asset_id", ID),
        sa.Column("public_icon_url", sa.String(500)),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("visibility", sa.String(20), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", TS, nullable=False),
        sa.Column("updated_at", TS, nullable=False),
        sa.ForeignKeyConstraint(
            ["client_id"],
            ["clients.id"],
            name=op.f("fk_products_client_id_clients"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["projects.id"],
            name=op.f("fk_products_project_id_projects"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_products")),
        sa.UniqueConstraint("slug", name=op.f("uq_products_slug")),
    )
    op.create_index(op.f("ix_products_client_id"), "products", ["client_id"])
    op.create_table(
        "assets",
        sa.Column("id", ID, nullable=False),
        sa.Column("client_id", ID, nullable=False),
        sa.Column("owner_type", sa.String(20), nullable=False),
        sa.Column("owner_id", ID, nullable=False),
        sa.Column("purpose", sa.String(20), nullable=False),
        sa.Column("kind", sa.String(20), nullable=False),
        sa.Column("filename", sa.String(200), nullable=False),
        sa.Column("alt_text", sa.String(300)),
        sa.Column("content_type", sa.String(120), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("gcs_bucket", sa.String(100), nullable=False),
        sa.Column("gcs_object", sa.String(500), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("created_at", TS, nullable=False),
        sa.ForeignKeyConstraint(
            ["client_id"],
            ["clients.id"],
            name=op.f("fk_assets_client_id_clients"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_assets")),
    )
    op.create_index(op.f("ix_assets_client_id"), "assets", ["client_id"])
    op.create_index(op.f("ix_assets_owner_id"), "assets", ["owner_id"])


def downgrade() -> None:
    op.drop_table("assets")
    op.drop_table("products")
    op.drop_table("projects")
    op.drop_table("memberships")
    op.drop_table("clients")
