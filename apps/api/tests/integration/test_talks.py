"""Phase 1 API integration tests for /api/v1/talks.

Tests match the spec in docs/planning/05-testing.md §test_talks.py.
Uses a real test DB (testcontainers). Each test function uses `clean_db`
to truncate tables after the test.
"""

from __future__ import annotations

import uuid
from datetime import date

import pytest
from httpx import AsyncClient
from sqlalchemy import text


# ---------------------------------------------------------------------------
# Helper to create reference data (pillar + conference)
# ---------------------------------------------------------------------------


async def _make_pillar(client: AsyncClient, name: str = "TestPillar") -> str:
    """Insert a pillar directly via the test engine (pillars are seeded, not POST-created)."""
    # Pillars don't have a POST endpoint — they're seeded reference data.
    # We'll insert one directly and return its ID.
    resp = await client.get("/api/v1/pillars")
    assert resp.status_code == 200
    items = resp.json()
    if items:
        return items[0]["id"]
    return ""  # no pillars in test DB — that's fine for most tests


async def _insert_pillar(test_engine, name: str = "IntTestPillar") -> str:
    pid = str(uuid.uuid4())
    async with test_engine.begin() as conn:
        await conn.execute(
            text(
                "INSERT INTO app.strategic_pillars (id, name, description, display_order) "
                "VALUES (:id, :name, 'desc', 50)"
            ),
            {"id": pid, "name": name},
        )
    return pid


async def _insert_conference(test_engine, conf_id: str | None = None) -> str:
    cid = conf_id or str(uuid.uuid4())
    slug = f"int-test-conf-{cid[:8]}"
    async with test_engine.begin() as conn:
        await conn.execute(
            text(
                "INSERT INTO app.conferences "
                "(id, name, slug, status, event_kind, freshness_score, topics, "
                "cfp_topics_of_interest, cfp_deadlines, is_virtual) "
                "VALUES (:id, 'IntTestConf', :slug, 'approved', 'corporate', "
                "1.0, '{}', '{}', '[]', false)"
            ),
            {"id": cid, "slug": slug},
        )
    return cid


async def _insert_series(test_engine, name: str = "IntTestSeries") -> str:
    sid = str(uuid.uuid4())
    async with test_engine.begin() as conn:
        await conn.execute(
            text(
                "INSERT INTO app.conference_series (id, canonical_name, aliases, "
                "typical_topics, is_active) "
                "VALUES (:id, :name, '{}', '{}', true)"
            ),
            {"id": sid, "name": name},
        )
    return sid


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_talks_empty(async_client: AsyncClient, clean_db) -> None:
    resp = await async_client.get("/api/v1/talks")
    assert resp.status_code == 200
    body = resp.json()
    assert body["items"] == []
    assert body["total"] == 0


@pytest.mark.asyncio
async def test_create_talk_manual(async_client: AsyncClient, clean_db) -> None:
    resp = await async_client.post(
        "/api/v1/talks",
        json={"title": "My First Talk", "abstract": "An intro abstract."},
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["title"] == "My First Talk"
    assert "id" in body
    assert body["source_type"] == "manual"
    assert body["review_status"] == "draft"


@pytest.mark.asyncio
async def test_create_talk_missing_title(async_client: AsyncClient, clean_db) -> None:
    resp = await async_client.post("/api/v1/talks", json={"abstract": "no title"})
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_get_talk(async_client: AsyncClient, clean_db) -> None:
    create_resp = await async_client.post(
        "/api/v1/talks",
        json={"title": "Get Me"},
    )
    assert create_resp.status_code == 201
    talk_id = create_resp.json()["id"]

    resp = await async_client.get(f"/api/v1/talks/{talk_id}")
    assert resp.status_code == 200
    body = resp.json()
    assert body["id"] == talk_id
    assert body["tags"] == []
    assert body["topics"] == []
    assert body["submissions"] == []


@pytest.mark.asyncio
async def test_update_talk(async_client: AsyncClient, clean_db) -> None:
    create_resp = await async_client.post("/api/v1/talks", json={"title": "Old Title"})
    assert create_resp.status_code == 201
    talk_id = create_resp.json()["id"]
    old_updated = create_resp.json()["updated_at"]

    resp = await async_client.put(
        f"/api/v1/talks/{talk_id}",
        json={"title": "New Title", "review_status": "approved"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["title"] == "New Title"
    assert body["review_status"] == "approved"


@pytest.mark.asyncio
async def test_delete_talk_soft(async_client: AsyncClient, clean_db) -> None:
    create_resp = await async_client.post("/api/v1/talks", json={"title": "DeleteMe"})
    assert create_resp.status_code == 201
    talk_id = create_resp.json()["id"]

    del_resp = await async_client.delete(f"/api/v1/talks/{talk_id}")
    assert del_resp.status_code == 204

    # Default list query excludes inactive talks
    list_resp = await async_client.get("/api/v1/talks")
    assert not any(t["id"] == talk_id for t in list_resp.json()["items"])


@pytest.mark.asyncio
async def test_submit_talk(async_client: AsyncClient, clean_db, test_engine) -> None:
    create_resp = await async_client.post("/api/v1/talks", json={"title": "Submit Me"})
    assert create_resp.status_code == 201
    talk_id = create_resp.json()["id"]

    conf_id = await _insert_conference(test_engine)

    resp = await async_client.post(
        f"/api/v1/talks/{talk_id}/submit",
        json={"conference_id": conf_id, "submitted_at": str(date.today())},
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["talk_id"] == talk_id
    assert body["conference_id"] == conf_id


@pytest.mark.asyncio
async def test_submit_talk_duplicate_conference_409(
    async_client: AsyncClient, clean_db, test_engine
) -> None:
    create_resp = await async_client.post("/api/v1/talks", json={"title": "Dup Submit"})
    talk_id = create_resp.json()["id"]
    conf_id = await _insert_conference(test_engine)

    await async_client.post(
        f"/api/v1/talks/{talk_id}/submit", json={"conference_id": conf_id}
    )
    resp = await async_client.post(
        f"/api/v1/talks/{talk_id}/submit", json={"conference_id": conf_id}
    )
    assert resp.status_code == 409


@pytest.mark.asyncio
async def test_update_submission_outcome(
    async_client: AsyncClient, clean_db, test_engine
) -> None:
    create_resp = await async_client.post("/api/v1/talks", json={"title": "Outcome Talk"})
    talk_id = create_resp.json()["id"]
    conf_id = await _insert_conference(test_engine)

    sub_resp = await async_client.post(
        f"/api/v1/talks/{talk_id}/submit", json={"conference_id": conf_id}
    )
    sub_id = sub_resp.json()["id"]

    patch_resp = await async_client.patch(
        f"/api/v1/talks/{talk_id}/submissions/{sub_id}",
        json={"outcome": "accepted"},
    )
    assert patch_resp.status_code == 200
    assert patch_resp.json()["outcome"] == "accepted"


@pytest.mark.asyncio
async def test_reuse_check_low_risk(async_client: AsyncClient, clean_db) -> None:
    create_resp = await async_client.post("/api/v1/talks", json={"title": "Reuse Low"})
    talk_id = create_resp.json()["id"]

    resp = await async_client.get(f"/api/v1/talks/{talk_id}/reuse-check")
    assert resp.status_code == 200
    body = resp.json()
    assert body["risk_level"] == "low"
    assert body["submission_count_12m"] == 0
    assert body["warning"] is None


@pytest.mark.asyncio
async def test_reuse_check_high_risk_three_submissions(
    async_client: AsyncClient, clean_db, test_engine
) -> None:
    """3 submissions in 12 months → high risk."""
    create_resp = await async_client.post("/api/v1/talks", json={"title": "Reuse High"})
    talk_id = create_resp.json()["id"]

    # Create 3 conferences and submit to each
    for _ in range(3):
        conf_id = await _insert_conference(test_engine)
        await async_client.post(
            f"/api/v1/talks/{talk_id}/submit",
            json={"conference_id": conf_id, "submitted_at": str(date.today())},
        )

    resp = await async_client.get(f"/api/v1/talks/{talk_id}/reuse-check")
    assert resp.status_code == 200
    body = resp.json()
    assert body["risk_level"] == "high"
    assert body["submission_count_12m"] == 3


@pytest.mark.asyncio
async def test_reuse_check_series_reuse(
    async_client: AsyncClient, clean_db, test_engine
) -> None:
    """2 submissions to same series → series_reuse detected."""
    create_resp = await async_client.post("/api/v1/talks", json={"title": "SeriesReuse"})
    talk_id = create_resp.json()["id"]

    series_id = await _insert_series(test_engine, "KubeCon")

    # Create 2 conferences in the same series
    for _ in range(2):
        cid = str(uuid.uuid4())
        slug = f"kubecon-{cid[:8]}"
        async with test_engine.begin() as conn:
            await conn.execute(
                text(
                    "INSERT INTO app.conferences "
                    "(id, name, slug, status, event_kind, freshness_score, topics, "
                    "cfp_topics_of_interest, cfp_deadlines, is_virtual, series_id) "
                    "VALUES (:id, 'KubeCon', :slug, 'approved', 'corporate', "
                    "1.0, '{}', '{}', '[]', false, :series_id)"
                ),
                {"id": cid, "slug": slug, "series_id": series_id},
            )
        await async_client.post(
            f"/api/v1/talks/{talk_id}/submit",
            json={"conference_id": cid, "submitted_at": str(date.today())},
        )

    resp = await async_client.get(f"/api/v1/talks/{talk_id}/reuse-check")
    assert resp.status_code == 200
    body = resp.json()
    assert body["risk_level"] == "high"
    assert len(body["series_reuse"]) >= 1
    assert body["series_reuse"][0]["series_name"] == "KubeCon"


@pytest.mark.asyncio
async def test_filter_talks_by_pillar(
    async_client: AsyncClient, clean_db, test_engine
) -> None:
    pillar_id = await _insert_pillar(test_engine, "FilterPillar")

    # Create 2 talks: one with pillar, one without
    resp1 = await async_client.post(
        "/api/v1/talks",
        json={"title": "With Pillar", "pillar_id": pillar_id},
    )
    assert resp1.status_code == 201
    await async_client.post("/api/v1/talks", json={"title": "No Pillar"})

    resp = await async_client.get(f"/api/v1/talks?pillar_id={pillar_id}")
    assert resp.status_code == 200
    items = resp.json()["items"]
    assert len(items) == 1
    assert items[0]["title"] == "With Pillar"


@pytest.mark.asyncio
async def test_filter_talks_by_tag(
    async_client: AsyncClient, clean_db, test_engine
) -> None:
    """GET /talks?tag_id=X returns only talks with that tag."""
    # Create a tag
    tag_resp = await async_client.post("/api/v1/talk-tags", json={"name": "filter-tag"})
    assert tag_resp.status_code == 201
    tag_id = tag_resp.json()["id"]

    # Create two talks
    t1 = (await async_client.post("/api/v1/talks", json={"title": "Tagged Talk"})).json()["id"]
    await async_client.post("/api/v1/talks", json={"title": "Untagged Talk"})

    # Assign tag to first talk directly
    async with test_engine.begin() as conn:
        await conn.execute(
            text("INSERT INTO app.talk_tag_assignments (talk_id, tag_id) VALUES (:tid, :tagid)"),
            {"tid": t1, "tagid": tag_id},
        )

    resp = await async_client.get(f"/api/v1/talks?tag_id={tag_id}")
    assert resp.status_code == 200
    items = resp.json()["items"]
    assert len(items) == 1
    assert items[0]["title"] == "Tagged Talk"


# ---------------------------------------------------------------------------
# Upload endpoint
# ---------------------------------------------------------------------------

_FIXTURE_DIR = __import__("pathlib").Path(__file__).parent.parent / "fixtures"


@pytest.mark.asyncio
async def test_upload_txt_returns_preview_no_db_row(
    async_client: AsyncClient, clean_db
) -> None:
    """POST /talks/upload with a TXT file returns ExtractedTalk preview; no DB row created."""
    sample = _FIXTURE_DIR / "sample_talk.txt"
    with open(sample, "rb") as fh:
        resp = await async_client.post(
            "/api/v1/talks/upload",
            files={"file": ("sample_talk.txt", fh, "text/plain")},
        )
    assert resp.status_code == 200
    body = resp.json()
    assert "extracted" in body
    assert "suggested_topic_matches" in body
    # extracted should have at minimum title and abstract
    assert body["extracted"]["title"]
    assert body["extracted"]["abstract"]
    # Verify no talk row was created
    list_resp = await async_client.get("/api/v1/talks")
    assert list_resp.json()["total"] == 0


@pytest.mark.asyncio
async def test_upload_unsupported_type_422(async_client: AsyncClient, clean_db) -> None:
    """POST /talks/upload with an unsupported file type returns 422."""
    resp = await async_client.post(
        "/api/v1/talks/upload",
        files={"file": ("presentation.pptx", b"PK\x03\x04fake", "application/octet-stream")},
    )
    assert resp.status_code == 422
