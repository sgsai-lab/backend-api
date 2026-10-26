"""Firestore → PostgreSQL mapping for the client hub (API-19 spike).

Pure functions only: ``rows_from_firestore`` turns exported documents into table rows and the
``*_json`` serializers rebuild the exact JSON the home API returns, which the contract test
(tests/unit/test_hub_contract.py) compares against responses recorded from home.
"""

from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from typing import Any

Document = dict[str, Any]
Row = dict[str, Any]

ROLE_RANK = {"viewer": 0, "member": 1, "admin": 2, "owner": 3}


def parse_instant(value: Any) -> datetime | None:
    """Firestore exports carry ISO-8601 strings written by JavaScript's toISOString()."""
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=UTC)
    return datetime.fromisoformat(str(value).replace("Z", "+00:00"))


def js_instant(value: datetime | None) -> str | None:
    """Formats like JavaScript's toISOString(): UTC, millisecond precision, ``Z`` suffix."""
    if value is None:
        return None
    utc = value.astimezone(UTC)
    return f"{utc.strftime('%Y-%m-%dT%H:%M:%S')}.{utc.microsecond // 1000:03d}Z"


def parse_day(value: Any) -> date | None:
    return date.fromisoformat(value) if isinstance(value, str) and value else None


def day(value: date | None) -> str | None:
    return value.isoformat() if value else None


def _required_instant(document: Document, key: str) -> datetime:
    value = parse_instant(document.get(key))
    if value is None:
        raise ValueError(f"{key} is missing on document {document.get('id')!r}")
    return value


@dataclass
class HubRows:
    clients: list[Row] = field(default_factory=list)
    memberships: list[Row] = field(default_factory=list)
    projects: list[Row] = field(default_factory=list)
    products: list[Row] = field(default_factory=list)
    assets: list[Row] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)


def rows_from_firestore(collections: dict[str, list[Document]]) -> HubRows:
    """Maps exported collections to rows. Pending assets and inactive memberships are skipped."""
    rows = HubRows()
    for doc in collections.get("clients", []):
        rows.clients.append(
            {
                "id": doc["id"],
                "name": doc["name"],
                "slug": doc["slug"],
                "primary_sector": doc["primary_sector"],
                "status": doc.get("status", "active"),
                "contact": doc.get("contact") or {},
                "branding": doc.get("branding") or {},
                "created_by": doc.get("created_by"),
                "created_at": _required_instant(doc, "created_at"),
                "updated_at": _required_instant(doc, "updated_at"),
            }
        )
    for doc in collections.get("memberships", []):
        if doc.get("status") != "active":
            rows.skipped.append(f"membership {doc.get('client_id')}/{doc.get('user_id')}")
            continue
        rows.memberships.append(
            {
                "client_id": doc["client_id"],
                "user_id": doc["user_id"],
                "role": doc["role"],
                "status": "active",
                "invited_by": doc.get("invited_by"),
                "joined_at": parse_instant(doc.get("joined_at")),
            }
        )
    for doc in collections.get("projects", []):
        rows.projects.append(
            {
                "id": doc["id"],
                "client_id": doc["client_id"],
                "name": doc["name"],
                "summary": doc.get("summary"),
                "sector": doc["sector"],
                "status": doc["status"],
                "tags": list(doc.get("tags") or []),
                "start_date": parse_day(doc.get("start_date")),
                "end_date": parse_day(doc.get("end_date")),
                "sector_profile": doc.get("sector_profile"),
                "milestones": list(doc.get("milestones") or []),
                "cover_asset_id": doc.get("cover_asset_id"),
                "owner_user_id": doc.get("owner_user_id"),
                "version": int(doc.get("version") or 1),
                "deleted_at": parse_instant(doc.get("deleted_at")),
                "created_by": doc.get("created_by"),
                "created_at": _required_instant(doc, "created_at"),
                "updated_at": _required_instant(doc, "updated_at"),
            }
        )
    for doc in collections.get("products", []):
        rows.products.append(
            {
                "id": doc["id"],
                "client_id": doc["client_id"],
                "project_id": doc.get("project_id"),
                "kind": doc["kind"],
                "name": doc["name"],
                "slug": doc["slug"],
                "summary": doc.get("summary"),
                "launch_url": doc.get("launch_url"),
                "store_urls": doc.get("store_urls") or {},
                "icon_asset_id": doc.get("icon_asset_id"),
                "public_icon_url": doc.get("public_icon_url"),
                "status": doc["status"],
                "visibility": doc["visibility"],
                "sort_order": int(doc.get("order") or 0),
                "created_at": _required_instant(doc, "created_at"),
                "updated_at": _required_instant(doc, "updated_at"),
            }
        )
    for doc in collections.get("assets", []):
        if doc.get("status") != "ready":
            rows.skipped.append(f"asset {doc.get('id')} ({doc.get('status')})")
            continue
        rows.assets.append(
            {
                key: doc.get(key)
                for key in (
                    "id",
                    "client_id",
                    "owner_type",
                    "owner_id",
                    "purpose",
                    "kind",
                    "filename",
                    "alt_text",
                    "content_type",
                    "size_bytes",
                    "gcs_bucket",
                    "gcs_object",
                    "status",
                )
            }
            | {"created_at": _required_instant(doc, "created_at")}
        )
    return rows


def can_edit(role: str | None) -> bool:
    return ROLE_RANK.get(role or "", -1) >= ROLE_RANK["admin"]


def client_json(row: Row, *, role: str | None, member_count: int) -> dict[str, Any]:
    """GET /api/v1/clients/{id}."""
    return {
        "id": row["id"],
        "name": row["name"],
        "slug": row["slug"],
        "primary_sector": row["primary_sector"],
        "status": row["status"],
        "contact": row["contact"],
        "branding": row["branding"],
        "created_at": js_instant(row["created_at"]),
        "updated_at": js_instant(row["updated_at"]),
        **({"my_role": role} if role else {}),
        "member_count": member_count,
    }


def project_json(row: Row, *, role: str | None) -> dict[str, Any]:
    """GET /api/v1/projects/{id}."""
    return {
        "id": row["id"],
        "client_id": row["client_id"],
        "name": row["name"],
        "summary": row["summary"],
        "sector": row["sector"],
        "status": row["status"],
        "tags": row["tags"],
        "start_date": day(row["start_date"]),
        "end_date": day(row["end_date"]),
        "sector_profile": row["sector_profile"],
        "milestones": row["milestones"],
        "cover_asset_id": row["cover_asset_id"],
        "owner_user_id": row["owner_user_id"],
        "created_at": js_instant(row["created_at"]),
        "updated_at": js_instant(row["updated_at"]),
        "deleted_at": js_instant(row["deleted_at"]),
        "can_edit": can_edit(role),
    }


def project_etag(row: Row) -> str:
    return f'"v{row["version"]}"'


def product_json(row: Row, *, role: str | None) -> dict[str, Any]:
    """Items of GET /api/v1/products."""
    return {
        "id": row["id"],
        "client_id": row["client_id"],
        "project_id": row["project_id"],
        "kind": row["kind"],
        "name": row["name"],
        "slug": row["slug"],
        "summary": row["summary"],
        "launch_url": row["launch_url"],
        "store_urls": row["store_urls"],
        "icon_asset_id": row["icon_asset_id"],
        "public_icon_url": row["public_icon_url"],
        "status": row["status"],
        "visibility": row["visibility"],
        "order": row["sort_order"],
        "created_at": js_instant(row["created_at"]),
        "updated_at": js_instant(row["updated_at"]),
        **({"can_edit": can_edit(role)} if role else {}),
    }
