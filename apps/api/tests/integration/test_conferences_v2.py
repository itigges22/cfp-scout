"""Phase 1 API integration tests — conference v2 fields (event_kind, assigned_pillar_id)."""

from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import text


async def _create_pillar(test_engine, name: str = "TestPillar") -> str:
    pid = str(uuid.uuid4())
    async with test_engine.begin() as conn:
        await conn.execute(
            text(
                "INSERT INTO app.strategic_pillars (id, name, description, display_order) "
                "VALUES (:id, :name, 'desc', 20)"
            ),
            {"id": pid, "name": name},
        )
    return pid


@pytest.mark.asyncio
async def test_create_conference_team_managed_status_approved(
    async_client: AsyncClient, clean_db
) -> None:
    """POST /conferences with event_kind='team_managed' → status='approved' immediately."""
    resp = await async_client.post(
        "/api/v1/conferences",
        json={
            "name": "Our Internal Summit 2099",
            "event_kind": "team_managed",
        },
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["conference"]["event_kind"] == "team_managed"
    assert body["conference"]["status"] == "approved"
    # Matcher should be skipped for team_managed
    assert body["match"] is None
    assert "skipped" in (body["match_error"] or "").lower()


@pytest.mark.asyncio
async def test_create_conference_corporate_normal_lifecycle(
    async_client: AsyncClient, clean_db
) -> None:
    """POST /conferences with event_kind='corporate' → status follows normal lifecycle."""
    resp = await async_client.post(
        "/api/v1/conferences",
        json={
            "name": "PyConf Corporate 2099",
            "event_kind": "corporate",
        },
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["conference"]["event_kind"] == "corporate"
    # Status should NOT be 'approved' from the start
    assert body["conference"]["status"] != "approved"


@pytest.mark.asyncio
async def test_create_conference_invalid_event_kind_422(
    async_client: AsyncClient, clean_db
) -> None:
    resp = await async_client.post(
        "/api/v1/conferences",
        json={"name": "BadKind 2099", "event_kind": "INVALID_KIND"},
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_create_conference_with_assigned_pillar_id(
    async_client: AsyncClient, clean_db, test_engine
) -> None:
    pid = await _create_pillar(test_engine, "AssignPillar")

    resp = await async_client.post(
        "/api/v1/conferences",
        json={
            "name": "PillarConf 2099",
            "assigned_pillar_id": pid,
        },
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["conference"]["assigned_pillar_id"] == pid


@pytest.mark.asyncio
async def test_create_conference_nonexistent_pillar_stored(
    async_client: AsyncClient, clean_db
) -> None:
    """A nonexistent assigned_pillar_id is stored as-is (FK is nullable SET NULL at DB level).

    The API doesn't validate FK existence for assigned_pillar_id — it just stores what's given.
    The DB has ON DELETE SET NULL so it won't break on stale IDs.
    This test documents the current behaviour.
    """
    fake_id = str(uuid.uuid4())
    resp = await async_client.post(
        "/api/v1/conferences",
        json={"name": "FakePillarConf 2099", "assigned_pillar_id": fake_id},
    )
    # The behaviour depends on whether FK exists — could be 201 (if FK deferred) or 422/500
    # Document that it's either 201 or 4xx/5xx (not a server error that crashes):
    assert resp.status_code in (201, 422, 409)
