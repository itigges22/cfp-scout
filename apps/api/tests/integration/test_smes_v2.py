"""Phase 2 integration tests for SME topic cap + expertise_areas removal.

Covers the spec in docs/planning/05-testing.md §test_smes_v2.py:
  - POST /smes with > SME_MAX_TOPICS topics → 422
  - POST /smes with exactly SME_MAX_TOPICS topics → 201
  - PUT /smes/{id} updating topics → primary_topics stays in sync
  - expertise_areas must NOT appear in GET /smes/{id} response
"""

from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import text


# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------


async def _insert_topic(test_engine, name: str) -> str:
    tid = str(uuid.uuid4())
    async with test_engine.begin() as conn:
        await conn.execute(
            text(
                "INSERT INTO app.topics (id, name, slug, is_active, pending_review) "
                "VALUES (:id, :name, :slug, true, false)"
            ),
            {"id": tid, "name": name, "slug": name.lower().replace(" ", "-")},
        )
    return tid


async def _insert_audience(test_engine, name: str) -> str:
    aid = str(uuid.uuid4())
    async with test_engine.begin() as conn:
        await conn.execute(
            text(
                "INSERT INTO app.audience_profiles "
                "(id, name, description, industry, role_seniority, "
                "primary_pain_points, key_messages, is_active) "
                "VALUES (:id, :name, 'test audience', 'Tech', 'Senior', "
                "'{}'::text[], '{}'::text[], true)"
            ),
            {"id": aid, "name": name},
        )
    return aid


def _sme_payload(topic_ids: list[str], audience_ids: list[str]) -> dict:
    return {
        "full_name": "Test SME",
        "team": "Platform",
        "primary_topics": topic_ids,
        "audience_focus": audience_ids,
        "location_country": "US",
        "bio": "A" * 200,  # min-length satisfied
    }


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_sme_topic_cap_over_limit_422(
    async_client: AsyncClient, clean_db, test_engine
) -> None:
    """POST /smes with 6 topics (SME_MAX_TOPICS=5) → 422."""
    topic_ids = [await _insert_topic(test_engine, f"Topic {i}") for i in range(6)]
    aud_id = await _insert_audience(test_engine, "DevOps Engineers")

    resp = await async_client.post(
        "/api/v1/smes", json=_sme_payload(topic_ids, [aud_id])
    )
    assert resp.status_code == 422
    detail = str(resp.json())
    assert "topics" in detail.lower() or "SME_MAX_TOPICS" in detail or "at most" in detail


@pytest.mark.asyncio
async def test_sme_topic_cap_at_limit_201(
    async_client: AsyncClient, clean_db, test_engine
) -> None:
    """POST /smes with exactly 5 topics (SME_MAX_TOPICS=5) → 201."""
    topic_ids = [await _insert_topic(test_engine, f"ExactTopic {i}") for i in range(5)]
    aud_id = await _insert_audience(test_engine, "Architects")

    resp = await async_client.post(
        "/api/v1/smes", json=_sme_payload(topic_ids, [aud_id])
    )
    assert resp.status_code == 201
    body = resp.json()
    assert len(body["primary_topics"]) == 5


@pytest.mark.asyncio
async def test_sme_primary_topics_sync_on_update(
    async_client: AsyncClient, clean_db, test_engine
) -> None:
    """PUT /smes/{id} with different topics keeps primary_topics in sync."""
    t1 = await _insert_topic(test_engine, "SyncA")
    t2 = await _insert_topic(test_engine, "SyncB")
    t3 = await _insert_topic(test_engine, "SyncC")
    aud_id = await _insert_audience(test_engine, "SyncAudience")

    create_resp = await async_client.post(
        "/api/v1/smes", json=_sme_payload([t1, t2], [aud_id])
    )
    assert create_resp.status_code == 201
    sme_id = create_resp.json()["id"]
    assert set(create_resp.json()["primary_topics"]) == {t1, t2}

    # Update to a different set of topics
    update_resp = await async_client.put(
        f"/api/v1/smes/{sme_id}",
        json=_sme_payload([t3], [aud_id]),
    )
    assert update_resp.status_code == 200
    assert set(update_resp.json()["primary_topics"]) == {t3}


@pytest.mark.asyncio
async def test_expertise_areas_not_in_response(
    async_client: AsyncClient, clean_db, test_engine
) -> None:
    """GET /smes/{id} must NOT include expertise_areas after Migration J."""
    topic_id = await _insert_topic(test_engine, "NoExpertiseTopic")
    aud_id = await _insert_audience(test_engine, "NoExpertiseAud")

    create_resp = await async_client.post(
        "/api/v1/smes", json=_sme_payload([topic_id], [aud_id])
    )
    assert create_resp.status_code == 201
    sme_id = create_resp.json()["id"]

    get_resp = await async_client.get(f"/api/v1/smes/{sme_id}")
    assert get_resp.status_code == 200
    assert "expertise_areas" not in get_resp.json()
