"""The Postgres mapping must reproduce the JSON home's /api/v1 returns (ADR-002 contract).

The fixture is recorded from sgsai-lab/home by scripts/record_home_contract.mjs.
"""

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from app.modules.hub.migration import (
    client_json,
    js_instant,
    parse_instant,
    product_json,
    project_etag,
    project_json,
    rows_from_firestore,
)

FIXTURE = Path(__file__).parent.parent / "fixtures" / "home_contract.json"


@pytest.fixture(scope="module")
def contract() -> dict[str, Any]:
    data: dict[str, Any] = json.loads(FIXTURE.read_text(encoding="utf-8"))
    return data


def test_maps_every_collection(contract: dict[str, Any]) -> None:
    rows = rows_from_firestore(contract["collections"])

    assert len(rows.clients) == 1
    assert len(rows.memberships) == 2
    assert len(rows.projects) == 1
    assert len(rows.products) == 1
    assert rows.skipped == []


def test_client_response_matches_home(contract: dict[str, Any]) -> None:
    rows = rows_from_firestore(contract["collections"])
    role = contract["viewer_role"]

    actual = client_json(rows.clients[0], role=role, member_count=len(rows.memberships))

    assert actual == contract["responses"]["client"]


def test_project_response_matches_home(contract: dict[str, Any]) -> None:
    rows = rows_from_firestore(contract["collections"])

    actual = project_json(rows.projects[0], role=contract["viewer_role"])

    assert actual == contract["responses"]["project"]
    assert project_etag(rows.projects[0]) == '"v1"'


def test_product_list_matches_home(contract: dict[str, Any]) -> None:
    rows = rows_from_firestore(contract["collections"])

    items = [product_json(row, role=contract["viewer_role"]) for row in rows.products]

    assert items == contract["responses"]["products"]["items"]


def test_skips_pending_assets_and_inactive_memberships() -> None:
    now = "2026-11-01T10:00:00.000Z"
    rows = rows_from_firestore(
        {
            "memberships": [
                {"client_id": "c1", "user_id": "u1", "role": "member", "status": "removed"}
            ],
            "assets": [
                {"id": "a1", "status": "pending", "created_at": now},
                {
                    "id": "a2",
                    "status": "ready",
                    "client_id": "c1",
                    "owner_type": "project",
                    "owner_id": "p1",
                    "purpose": "gallery",
                    "kind": "image",
                    "filename": "cover.png",
                    "content_type": "image/png",
                    "size_bytes": 10,
                    "gcs_bucket": "media",
                    "gcs_object": "clients/c1/projects/p1/a2/cover.png",
                    "created_at": now,
                },
            ],
        }
    )

    assert [asset["id"] for asset in rows.assets] == ["a2"]
    assert rows.memberships == []
    assert rows.skipped == ["membership c1/u1", "asset a1 (pending)"]


def test_instants_round_trip_like_javascript() -> None:
    value = parse_instant("2026-11-01T10:00:00.120Z")

    assert value == datetime(2026, 11, 1, 10, 0, 0, 120000, tzinfo=UTC)
    assert js_instant(value) == "2026-11-01T10:00:00.120Z"
    assert parse_instant(None) is None


def test_rejects_documents_without_timestamps() -> None:
    with pytest.raises(ValueError, match="created_at"):
        rows_from_firestore(
            {"clients": [{"id": "c1", "name": "A", "slug": "a", "primary_sector": "business"}]}
        )


def test_spike_routes_are_not_mounted_in_production(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.core.config import get_settings
    from app.main import create_app

    monkeypatch.setenv("ENVIRONMENT", "production")
    get_settings.cache_clear()
    try:
        paths = {getattr(route, "path", "") for route in create_app().routes}
    finally:
        get_settings.cache_clear()

    assert "/api/v1/clients/{client_id}" not in paths
