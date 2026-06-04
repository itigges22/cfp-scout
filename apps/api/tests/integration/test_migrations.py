"""Migration tests — Phase 1 (migrations A–I).

Verifies that:
  * Alembic upgrade head runs clean (done by session-scoped conftest)
  * CHECK constraints reject invalid enum values
  * FK ON DELETE CASCADE / SET NULL behave correctly

These tests run against the real test DB (no mocks). Each test uses
the `clean_db` fixture to truncate tables between runs.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError


# ---------------------------------------------------------------------------
# Migration A: event_kind CHECK + assigned_pillar_id SET NULL
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_event_kind_invalid_raises(test_engine) -> None:
    """INSERT with an invalid event_kind must raise IntegrityError."""
    async with test_engine.begin() as conn:
        with pytest.raises(IntegrityError):
            await conn.execute(
                text(
                    "INSERT INTO app.conferences "
                    "(id, name, slug, status, event_kind, freshness_score, topics, "
                    "cfp_topics_of_interest, cfp_deadlines, is_virtual) "
                    "VALUES (gen_random_uuid(), 'X', 'x-2099', 'discovered', "
                    "'INVALID_KIND', 1.0, '{}', '{}', '[]', false)"
                )
            )


@pytest.mark.asyncio
async def test_event_kind_team_managed_accepted(test_engine) -> None:
    """INSERT with event_kind='team_managed' must succeed."""
    async with test_engine.begin() as conn:
        await conn.execute(
            text(
                "INSERT INTO app.conferences "
                "(id, name, slug, status, event_kind, freshness_score, topics, "
                "cfp_topics_of_interest, cfp_deadlines, is_virtual) "
                "VALUES (:id, 'TeamEv', 'teamev-2099', 'approved', "
                "'team_managed', 1.0, '{}', '{}', '[]', false)"
            ),
            {"id": str(uuid.uuid4())},
        )
        await conn.execute(
            text("DELETE FROM app.conferences WHERE slug = 'teamev-2099'")
        )


@pytest.mark.asyncio
async def test_assigned_pillar_id_set_null_on_pillar_delete(test_engine) -> None:
    """Deleting a pillar sets conferences.assigned_pillar_id to NULL (SET NULL)."""
    async with test_engine.begin() as conn:
        pillar_id = str(uuid.uuid4())
        conf_id = str(uuid.uuid4())

        await conn.execute(
            text(
                "INSERT INTO app.strategic_pillars "
                "(id, name, description, display_order) "
                "VALUES (:id, 'TestPillar', 'desc', 99)"
            ),
            {"id": pillar_id},
        )
        await conn.execute(
            text(
                "INSERT INTO app.conferences "
                "(id, name, slug, status, event_kind, assigned_pillar_id, "
                "freshness_score, topics, cfp_topics_of_interest, cfp_deadlines, is_virtual) "
                "VALUES (:cid, 'PillarConf', 'pillarconf-2099', 'discovered', "
                "'corporate', :pid, 1.0, '{}', '{}', '[]', false)"
            ),
            {"cid": conf_id, "pid": pillar_id},
        )

        await conn.execute(
            text("DELETE FROM app.strategic_pillars WHERE id = :id"), {"id": pillar_id}
        )

        row = (
            await conn.execute(
                text(
                    "SELECT assigned_pillar_id FROM app.conferences WHERE id = :cid"
                ),
                {"cid": conf_id},
            )
        ).fetchone()
        assert row is not None
        assert row[0] is None

        # Cleanup
        await conn.execute(
            text("DELETE FROM app.conferences WHERE id = :cid"), {"cid": conf_id}
        )


# ---------------------------------------------------------------------------
# Migration C: sme_pillars CASCADE deletes
# ---------------------------------------------------------------------------


@pytest.fixture()
async def pillar_and_sme(test_engine):  # type: ignore[misc]
    """Insert a pillar and SME row; yield their IDs; clean up after."""
    pillar_id = str(uuid.uuid4())
    sme_id = str(uuid.uuid4())
    async with test_engine.begin() as conn:
        await conn.execute(
            text(
                "INSERT INTO app.strategic_pillars (id, name, description, display_order) "
                "VALUES (:id, :name, 'desc', 98)"
            ),
            {"id": pillar_id, "name": f"P-{pillar_id[:8]}"},
        )
        await conn.execute(
            text(
                "INSERT INTO app.smes "
                "(id, full_name, team, primary_topics, audience_focus, "
                "location_country, bio, languages, external_links, is_active) "
                "VALUES (:id, 'Test SME', 'Eng', '{}', '{}', "
                "'US', 'Test bio text for this sme', '{}', '{}', true)"
            ),
            {"id": sme_id},
        )
    yield pillar_id, sme_id
    async with test_engine.begin() as conn:
        await conn.execute(
            text("DELETE FROM app.smes WHERE id = :id"), {"id": sme_id}
        )
        await conn.execute(
            text("DELETE FROM app.strategic_pillars WHERE id = :id"), {"id": pillar_id}
        )


@pytest.mark.asyncio
async def test_sme_pillars_cascade_on_sme_delete(test_engine, pillar_and_sme) -> None:
    """Deleting an SME cascades to sme_pillars."""
    pillar_id, sme_id = pillar_and_sme
    async with test_engine.begin() as conn:
        await conn.execute(
            text(
                "INSERT INTO app.sme_pillars (sme_id, pillar_id, is_primary) "
                "VALUES (:sid, :pid, false)"
            ),
            {"sid": sme_id, "pid": pillar_id},
        )
        await conn.execute(text("DELETE FROM app.smes WHERE id = :id"), {"id": sme_id})
        count = (
            await conn.execute(
                text(
                    "SELECT COUNT(*) FROM app.sme_pillars "
                    "WHERE sme_id = :sid AND pillar_id = :pid"
                ),
                {"sid": sme_id, "pid": pillar_id},
            )
        ).scalar_one()
        assert count == 0


@pytest.mark.asyncio
async def test_sme_pillars_cascade_on_pillar_delete(test_engine, pillar_and_sme) -> None:
    """Deleting a pillar cascades to sme_pillars."""
    pillar_id, sme_id = pillar_and_sme
    async with test_engine.begin() as conn:
        await conn.execute(
            text(
                "INSERT INTO app.sme_pillars (sme_id, pillar_id, is_primary) "
                "VALUES (:sid, :pid, false)"
            ),
            {"sid": sme_id, "pid": pillar_id},
        )
        await conn.execute(
            text("DELETE FROM app.strategic_pillars WHERE id = :id"), {"id": pillar_id}
        )
        count = (
            await conn.execute(
                text(
                    "SELECT COUNT(*) FROM app.sme_pillars "
                    "WHERE sme_id = :sid"
                ),
                {"sid": sme_id},
            )
        ).scalar_one()
        assert count == 0


# ---------------------------------------------------------------------------
# Migration D: talks CHECK constraints
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_talks_invalid_review_status_raises(test_engine) -> None:
    """INSERT talks with invalid review_status must raise IntegrityError."""
    async with test_engine.begin() as conn:
        with pytest.raises(IntegrityError):
            await conn.execute(
                text(
                    "INSERT INTO app.talks (id, title, source_type, review_status, is_active) "
                    "VALUES (gen_random_uuid(), 'T', 'manual', 'INVALID_STATUS', true)"
                )
            )


@pytest.mark.asyncio
async def test_talks_invalid_source_type_raises(test_engine) -> None:
    """INSERT talks with invalid source_type must raise IntegrityError."""
    async with test_engine.begin() as conn:
        with pytest.raises(IntegrityError):
            await conn.execute(
                text(
                    "INSERT INTO app.talks (id, title, source_type, review_status, is_active) "
                    "VALUES (gen_random_uuid(), 'T', 'INVALID', 'draft', true)"
                )
            )


# ---------------------------------------------------------------------------
# Migration G: talk_submissions UNIQUE + CASCADE
# ---------------------------------------------------------------------------


@pytest.fixture()
async def talk_and_conference(test_engine):  # type: ignore[misc]
    talk_id = str(uuid.uuid4())
    conf_id = str(uuid.uuid4())
    async with test_engine.begin() as conn:
        await conn.execute(
            text(
                "INSERT INTO app.talks (id, title, source_type, review_status, is_active) "
                "VALUES (:id, 'TestTalk', 'manual', 'draft', true)"
            ),
            {"id": talk_id},
        )
        await conn.execute(
            text(
                "INSERT INTO app.conferences "
                "(id, name, slug, status, event_kind, freshness_score, topics, "
                "cfp_topics_of_interest, cfp_deadlines, is_virtual) "
                "VALUES (:id, 'TestConf', :slug, 'discovered', 'corporate', "
                "1.0, '{}', '{}', '[]', false)"
            ),
            {"id": conf_id, "slug": f"testconf-{conf_id[:8]}"},
        )
    yield talk_id, conf_id
    async with test_engine.begin() as conn:
        await conn.execute(
            text("DELETE FROM app.talks WHERE id = :id"), {"id": talk_id}
        )
        await conn.execute(
            text("DELETE FROM app.conferences WHERE id = :id"), {"id": conf_id}
        )


@pytest.mark.asyncio
async def test_talk_submissions_unique_violation(test_engine, talk_and_conference) -> None:
    """Duplicate (talk_id, conference_id) must raise UniqueViolation."""
    talk_id, conf_id = talk_and_conference
    async with test_engine.begin() as conn:
        await conn.execute(
            text(
                "INSERT INTO app.talk_submissions (id, talk_id, conference_id) "
                "VALUES (gen_random_uuid(), :tid, :cid)"
            ),
            {"tid": talk_id, "cid": conf_id},
        )
        with pytest.raises(IntegrityError):
            await conn.execute(
                text(
                    "INSERT INTO app.talk_submissions (id, talk_id, conference_id) "
                    "VALUES (gen_random_uuid(), :tid, :cid)"
                ),
                {"tid": talk_id, "cid": conf_id},
            )


@pytest.mark.asyncio
async def test_talk_submissions_cascade_on_talk_delete(test_engine, talk_and_conference) -> None:
    """Deleting a talk cascades to talk_submissions."""
    talk_id, conf_id = talk_and_conference
    sub_id = str(uuid.uuid4())
    async with test_engine.begin() as conn:
        await conn.execute(
            text(
                "INSERT INTO app.talk_submissions (id, talk_id, conference_id) "
                "VALUES (:sid, :tid, :cid)"
            ),
            {"sid": sub_id, "tid": talk_id, "cid": conf_id},
        )
        await conn.execute(text("DELETE FROM app.talks WHERE id = :id"), {"id": talk_id})
        count = (
            await conn.execute(
                text("SELECT COUNT(*) FROM app.talk_submissions WHERE id = :sid"),
                {"sid": sub_id},
            )
        ).scalar_one()
        assert count == 0


# ---------------------------------------------------------------------------
# Migration E: talk_tag_assignments CASCADE on tag delete
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_talk_tag_assignments_cascade_on_tag_delete(test_engine) -> None:
    """Deleting a tag cascades to talk_tag_assignments."""
    talk_id = str(uuid.uuid4())
    tag_id = str(uuid.uuid4())

    async with test_engine.begin() as conn:
        await conn.execute(
            text(
                "INSERT INTO app.talks (id, title, source_type, review_status, is_active) "
                "VALUES (:id, 'T', 'manual', 'draft', true)"
            ),
            {"id": talk_id},
        )
        await conn.execute(
            text("INSERT INTO app.talk_tags (id, name) VALUES (:id, :name)"),
            {"id": tag_id, "name": f"tag-{tag_id[:8]}"},
        )
        await conn.execute(
            text(
                "INSERT INTO app.talk_tag_assignments (talk_id, tag_id) "
                "VALUES (:tid, :tagid)"
            ),
            {"tid": talk_id, "tagid": tag_id},
        )
        # Delete the tag → assignment should cascade
        await conn.execute(
            text("DELETE FROM app.talk_tags WHERE id = :id"), {"id": tag_id}
        )
        count = (
            await conn.execute(
                text(
                    "SELECT COUNT(*) FROM app.talk_tag_assignments "
                    "WHERE talk_id = :tid"
                ),
                {"tid": talk_id},
            )
        ).scalar_one()
        assert count == 0
        # Cleanup
        await conn.execute(text("DELETE FROM app.talks WHERE id = :id"), {"id": talk_id})


# ---------------------------------------------------------------------------
# Migration G: talk_submissions CASCADE on conference delete
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_talk_submissions_cascade_on_conference_delete(
    test_engine, talk_and_conference
) -> None:
    """Deleting a conference cascades to talk_submissions."""
    talk_id, conf_id = talk_and_conference
    sub_id = str(uuid.uuid4())
    async with test_engine.begin() as conn:
        await conn.execute(
            text(
                "INSERT INTO app.talk_submissions (id, talk_id, conference_id) "
                "VALUES (:sid, :tid, :cid)"
            ),
            {"sid": sub_id, "tid": talk_id, "cid": conf_id},
        )
        await conn.execute(
            text("DELETE FROM app.conferences WHERE id = :id"), {"id": conf_id}
        )
        count = (
            await conn.execute(
                text("SELECT COUNT(*) FROM app.talk_submissions WHERE id = :sid"),
                {"sid": sub_id},
            )
        ).scalar_one()
        assert count == 0
