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
async def test_an_unconfigured_event_kind_is_rejected_by_the_api(
    async_client, clean_db
) -> None:
    """Enforcement moved layers, deliberately.

    There used to be a CHECK constraint here, and this test inserted raw
    SQL to prove it fired. Migration 20260727_2200 dropped it: event kinds
    are now settings.event_kinds, which an operator edits at runtime, and
    a DDL constraint frozen when the migration ran cannot enforce a list
    that changes afterwards. Regenerating the constraint on every settings
    save would mean a settings page running DDL against a live table —
    a far worse failure than a bad string in a column.

    So the guarantee is now "the API refuses to write one", not "the
    database refuses to store one". The database WILL accept any string
    via direct SQL. That is the acknowledged cost of an editable
    vocabulary, and this test pins what replaced it.
    """
    r = await async_client.post(
        "/api/v1/conferences", json={"name": "Bad Kind 2099", "event_kind": "INVALID"}
    )
    assert r.status_code == 422
    assert "event kind" in r.text.lower()


@pytest.mark.asyncio
async def test_the_rejection_names_the_configured_kinds(
    async_client, clean_db
) -> None:
    """A Literal published the options in openapi.json; a runtime check
    does not. If the 422 does not list them, the error is unactionable."""
    r = await async_client.post(
        "/api/v1/conferences", json={"name": "Bad Kind 2099", "event_kind": "summit"}
    )
    assert r.status_code == 422
    assert "grassroot" in r.text, "the error should say what IS allowed"


@pytest.mark.parametrize(
    "kind", ["corporate", "grassroot", "developer_day", "research", "hackathon"]
)
@pytest.mark.asyncio
async def test_event_kind_canonical_values_accepted(test_engine, kind: str) -> None:
    """Every kind in EVENT_KINDS must be insertable.

    This test previously asserted the OPPOSITE — that 'team_managed' is
    accepted — and passed, because migration 20260604_1100 renamed the
    values in data but left the CHECK constraint alone. That drift made
    'grassroot' and 'hackathon' uninsertable in production while the API
    happily accepted them. Pinning the real set both ways now.
    """
    async with test_engine.begin() as conn:
        await conn.execute(
            text(
                "INSERT INTO app.conferences "
                "(id, name, slug, status, event_kind, topics, "
                "cfp_topics_of_interest, cfp_deadlines, is_virtual) "
                "VALUES (:id, :name, :slug, 'approved', "
                ":kind, '{}', '{}', '[]', false)"
            ),
            {
                "id": str(uuid.uuid4()),
                "name": f"Kind {kind}",
                "slug": f"kind-{kind}-2099",
                "kind": kind,
            },
        )
        await conn.execute(
            text("DELETE FROM app.conferences WHERE slug = :slug"),
            {"slug": f"kind-{kind}-2099"},
        )


@pytest.mark.asyncio
async def test_retired_event_kinds_are_not_in_the_default_vocabulary() -> None:
    """The pre-v2 values must not come back.

    Previously proved by attempting an INSERT; the CHECK that made that
    fail is gone (see above), so this now asserts the shipped default
    vocabulary instead. An operator CAN re-add 'meetup' deliberately —
    that is the point of the setting — but it must not reappear by
    accident.
    """
    from app.settings import Settings

    kinds = set(Settings().event_kinds)
    assert not ({"team_managed", "meetup"} & kinds)


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
                "topics, cfp_topics_of_interest, cfp_deadlines, is_virtual) "
                "VALUES (:cid, 'PillarConf', 'pillarconf-2099', 'discovered', "
                "'corporate', :pid, '{}', '{}', '[]', false)"
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
                "(id, full_name, team, audience_focus, "
                "location_country, bio, languages, external_links, is_active) "
                "VALUES (:id, 'Test SME', 'Eng', '{}', "
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
                "(id, name, slug, status, event_kind, topics, "
                "cfp_topics_of_interest, cfp_deadlines, is_virtual) "
                "VALUES (:id, 'TestConf', :slug, 'discovered', 'corporate', "
                "'{}', '{}', '[]', false)"
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
