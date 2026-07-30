"""Phase 1 API integration tests for /api/v1/pillars."""

from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import text

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _create_pillar(test_engine, name: str, order: int = 1) -> str:
    pid = str(uuid.uuid4())
    async with test_engine.begin() as conn:
        await conn.execute(
            text(
                "INSERT INTO app.strategic_pillars (id, name, description, display_order) "
                "VALUES (:id, :name, 'Test description', :order)"
            ),
            {"id": pid, "name": name, "order": order},
        )
    return pid


async def _create_sme(test_engine, name: str = "Test SME") -> str:
    sme_id = str(uuid.uuid4())
    async with test_engine.begin() as conn:
        await conn.execute(
            text(
                "INSERT INTO app.smes "
                "(id, full_name, team, audience_focus, "
                "location_country, bio, languages, external_links, is_active) "
                "VALUES (:id, :name, 'Eng', '{}', 'US', "
                "'A sufficiently long bio for testing purposes.', '{}', '{}', true)"
            ),
            {"id": sme_id, "name": name},
        )
    return sme_id


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_pillars_returns_aggregate_counts(
    async_client: AsyncClient, clean_db, test_engine
) -> None:
    await _create_pillar(test_engine, "CloudNative", 1)

    resp = await async_client.get("/api/v1/pillars")
    assert resp.status_code == 200
    items = resp.json()
    assert len(items) >= 1
    # Each pillar should have aggregate count fields
    pillar = next(p for p in items if p["name"] == "CloudNative")
    assert "sme_count" in pillar
    assert "talk_count" in pillar
    assert "audience_count" in pillar
    assert "conference_count" in pillar


@pytest.mark.asyncio
async def test_get_pillar(async_client: AsyncClient, clean_db, test_engine) -> None:
    pid = await _create_pillar(test_engine, "GetMePillar", 2)

    resp = await async_client.get(f"/api/v1/pillars/{pid}")
    assert resp.status_code == 200
    body = resp.json()
    assert body["id"] == pid
    assert body["name"] == "GetMePillar"


@pytest.mark.asyncio
async def test_update_pillar(async_client: AsyncClient, clean_db, test_engine) -> None:
    pid = await _create_pillar(test_engine, "OldName", 3)

    resp = await async_client.put(
        f"/api/v1/pillars/{pid}",
        json={"name": "NewName", "description": "Updated desc"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["name"] == "NewName"
    assert body["description"] == "Updated desc"


@pytest.mark.asyncio
async def test_link_sme_to_pillar(async_client: AsyncClient, clean_db, test_engine) -> None:
    pid = await _create_pillar(test_engine, "LinkPillar", 4)
    sme_id = await _create_sme(test_engine)

    resp = await async_client.post(
        f"/api/v1/pillars/{pid}/smes/{sme_id}",
        json={"is_primary": True},
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["sme_id"] == sme_id
    assert body["pillar_id"] == pid
    assert body["is_primary"] is True


@pytest.mark.asyncio
async def test_link_sme_duplicate_409(
    async_client: AsyncClient, clean_db, test_engine
) -> None:
    pid = await _create_pillar(test_engine, "DupLinkPillar", 5)
    sme_id = await _create_sme(test_engine, "DupSME")

    await async_client.post(
        f"/api/v1/pillars/{pid}/smes/{sme_id}", json={"is_primary": False}
    )
    resp = await async_client.post(
        f"/api/v1/pillars/{pid}/smes/{sme_id}", json={"is_primary": False}
    )
    assert resp.status_code == 409


@pytest.mark.asyncio
async def test_unlink_sme_from_pillar(
    async_client: AsyncClient, clean_db, test_engine
) -> None:
    pid = await _create_pillar(test_engine, "UnlinkPillar", 6)
    sme_id = await _create_sme(test_engine, "UnlinkSME")

    await async_client.post(
        f"/api/v1/pillars/{pid}/smes/{sme_id}", json={"is_primary": False}
    )
    del_resp = await async_client.delete(f"/api/v1/pillars/{pid}/smes/{sme_id}")
    assert del_resp.status_code == 204

    list_resp = await async_client.get(f"/api/v1/pillars/{pid}/smes")
    assert all(s["sme_id"] != sme_id for s in list_resp.json())


@pytest.mark.asyncio
async def test_list_pillar_smes_primary_first(
    async_client: AsyncClient, clean_db, test_engine
) -> None:
    pid = await _create_pillar(test_engine, "PrimaryPillar", 7)
    sme1 = await _create_sme(test_engine, "Primary SME")
    sme2 = await _create_sme(test_engine, "Secondary SME")

    await async_client.post(
        f"/api/v1/pillars/{pid}/smes/{sme2}", json={"is_primary": False}
    )
    await async_client.post(
        f"/api/v1/pillars/{pid}/smes/{sme1}", json={"is_primary": True}
    )

    resp = await async_client.get(f"/api/v1/pillars/{pid}/smes")
    assert resp.status_code == 200
    items = resp.json()
    # Primary SME should be first
    assert items[0]["is_primary"] is True


# ---------------------------------------------------------------------------
# Pillar-scoped collections
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_pillar_conferences(
    async_client: AsyncClient, clean_db, test_engine
) -> None:
    """Ranked by the matcher's per-pillar edge (conference_pillars), best
    first — NOT by assigned_pillar_id, which only knows the top pillar."""
    pid = await _create_pillar(test_engine, "ConfPillar", 14)

    weak, strong = str(uuid.uuid4()), str(uuid.uuid4())
    async with test_engine.begin() as conn:
        for cid, name, score in ((weak, "WeakConf", 0.2), (strong, "StrongConf", 0.7)):
            await conn.execute(
                text(
                    "INSERT INTO app.conferences "
                    "(id, name, slug, status, event_kind, topics, "
                    "cfp_topics_of_interest, cfp_deadlines, is_virtual) "
                    "VALUES (:id, :name, :slug, 'approved', 'corporate', "
                    "'{}', '{}', '[]', false)"
                ),
                {"id": cid, "name": name, "slug": f"pillarconf-{cid[:8]}"},
            )
            await conn.execute(
                text(
                    "INSERT INTO app.conference_pillars (conference_id, pillar_id, score) "
                    "VALUES (:cid, :pid, :score)"
                ),
                {"cid": cid, "pid": pid, "score": score},
            )

    resp = await async_client.get(f"/api/v1/pillars/{pid}/conferences")
    assert resp.status_code == 200
    items = resp.json()
    assert [c["id"] for c in items] == [strong, weak]
    assert items[0]["pillar_score"] == 0.7
    # No match row inserted — overall must be null, not fabricated.
    assert items[0]["overall_score"] is None
    assert "cfp_close_at" in items[0]


@pytest.mark.asyncio
async def test_list_pillar_talks(
    async_client: AsyncClient, clean_db, test_engine
) -> None:
    pid = await _create_pillar(test_engine, "TalkPillar", 15)

    create_resp = await async_client.post(
        "/api/v1/talks",
        json={"title": "Pillar Talk", "pillar_id": pid},
    )
    assert create_resp.status_code == 201

    resp = await async_client.get(f"/api/v1/pillars/{pid}/talks")
    assert resp.status_code == 200
    items = resp.json()
    assert any(t["title"] == "Pillar Talk" for t in items)


@pytest.mark.asyncio
async def test_list_pillar_audiences(
    async_client: AsyncClient, clean_db, test_engine
) -> None:
    pid = await _create_pillar(test_engine, "AudPillar", 16)

    aud_id = str(uuid.uuid4())
    async with test_engine.begin() as conn:
        await conn.execute(
            text(
                "INSERT INTO app.audience_profiles "
                "(id, name, description, industry, role_seniority, "
                "primary_pain_points, key_messages, pillar_id) "
                "VALUES (:id, 'DevOps Engineers', 'CI/CD focused developers', "
                "'Technology', 'senior', '{}', '{}', :pid)"
            ),
            {"id": aud_id, "pid": pid},
        )

    resp = await async_client.get(f"/api/v1/pillars/{pid}/audiences")
    assert resp.status_code == 200
    items = resp.json()
    assert any(a["id"] == aud_id for a in items)
    assert any(a["name"] == "DevOps Engineers" for a in items)
