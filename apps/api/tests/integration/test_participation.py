"""Attendance is recorded against the conference we already track.

These cover the thing the old ``past_conferences`` table could not do: say
who did WHAT. An array of SME ids could record that five people went, never
that Alice gave the talk while Bob worked the booth — which was the fact the
team most wanted out of it.

They also pin the rules that keep the data honest, because each one is a way
the table could quietly fill up with records nobody can act on.
"""

from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import text


async def _conference(async_client: AsyncClient, name: str) -> str:
    resp = await async_client.post(
        "/api/v1/conferences", json={"name": name, "event_kind": "grassroot"}
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["conference"]["id"]


async def _sme(test_engine, full_name: str = "Alice Researcher") -> str:
    sid = str(uuid.uuid4())
    async with test_engine.begin() as conn:
        await conn.execute(
            text(
                "INSERT INTO app.smes (id, full_name, team, location_country, bio) "
                "VALUES (:id, :n, 'DevRel', 'US', :bio)"
            ),
            {"id": sid, "n": full_name, "bio": "b" * 220},
        )
    return sid


# ---------------------------------------------------------------------------
# The case the old model could not express
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_two_people_two_activities_at_one_conference(
    async_client: AsyncClient, test_engine, clean_db
) -> None:
    """Alice spoke, Bob worked the booth, same event.

    The array-of-ids column this replaced could store both names but not
    what either of them did there.
    """
    conf = await _conference(async_client, "KubeCon + CloudNativeCon Europe 2025")
    alice = await _sme(test_engine, "Alice Researcher")
    bob = await _sme(test_engine, "Bob Engineer")

    for sme_id, activity in (
        (alice, "talk"),
        (bob, "booth"),
    ):
        resp = await async_client.post(
            f"/api/v1/conferences/{conf}/participation",
            json={
                "sme_id": sme_id,
                "person_label": "",
                "activity": activity,
            },
        )
        assert resp.status_code == 201, resp.text

    rows = (await async_client.get(f"/api/v1/conferences/{conf}/participation")).json()
    assert {(r["person_label"], r["activity"]) for r in rows} == {
        ("Alice Researcher", "talk"),
        ("Bob Engineer", "booth"),
    }


@pytest.mark.asyncio
async def test_one_person_can_do_two_things(
    async_client: AsyncClient, test_engine, clean_db
) -> None:
    """Speaking and staffing the booth is one person, two rows."""
    conf = await _conference(async_client, "PyTorch Conference 2025")
    alice = await _sme(test_engine)

    for activity in ("talk", "booth"):
        resp = await async_client.post(
            f"/api/v1/conferences/{conf}/participation",
            json={"sme_id": alice, "person_label": "", "activity": activity},
        )
        assert resp.status_code == 201, resp.text

    rows = (await async_client.get(f"/api/v1/conferences/{conf}/participation")).json()
    assert sorted(r["activity"] for r in rows) == ["booth", "talk"]


@pytest.mark.asyncio
async def test_the_same_person_and_activity_twice_is_rejected(
    async_client: AsyncClient, test_engine, clean_db
) -> None:
    """A double-submitted form must not produce two identical records."""
    conf = await _conference(async_client, "MLOps World 2025")
    alice = await _sme(test_engine)
    body = {"sme_id": alice, "person_label": "", "activity": "talk"}

    assert (
        await async_client.post(f"/api/v1/conferences/{conf}/participation", json=body)
    ).status_code == 201
    dup = await async_client.post(
        f"/api/v1/conferences/{conf}/participation", json=body
    )
    assert dup.status_code == 409, dup.text


# ---------------------------------------------------------------------------
# People who are not on the SME roster
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_a_person_who_is_not_an_sme_still_counts(
    async_client: AsyncClient, clean_db
) -> None:
    """An exec or a guest speaker was still there.

    Refusing to record them would push the fact into a free-text notes
    field, where nothing can count it.
    """
    conf = await _conference(async_client, "AI Engineer World's Fair 2025")
    resp = await async_client.post(
        f"/api/v1/conferences/{conf}/participation",
        json={"person_label": "A Visiting Executive", "activity": "attend"},
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["sme_id"] is None
    assert resp.json()["person_label"] == "A Visiting Executive"


@pytest.mark.asyncio
async def test_two_unmatched_guests_can_both_be_recorded(
    async_client: AsyncClient, clean_db
) -> None:
    """The unique constraint must not collapse people it cannot identify.

    ``sme_id`` is null for both, and Postgres treats nulls as distinct in a
    unique index — which is exactly what this relies on.
    """
    conf = await _conference(async_client, "Open Source Summit 2025")
    for name in ("Guest One", "Guest Two"):
        resp = await async_client.post(
            f"/api/v1/conferences/{conf}/participation",
            json={"person_label": name, "activity": "attend"},
        )
        assert resp.status_code == 201, resp.text

    rows = (await async_client.get(f"/api/v1/conferences/{conf}/participation")).json()
    assert len(rows) == 2


@pytest.mark.asyncio
async def test_an_unknown_sme_id_is_rejected(
    async_client: AsyncClient, clean_db
) -> None:
    """A stale id from a cached form must not create a row pointing nowhere."""
    conf = await _conference(async_client, "Ray Summit 2025")
    resp = await async_client.post(
        f"/api/v1/conferences/{conf}/participation",
        json={"sme_id": str(uuid.uuid4()), "person_label": "X", "activity": "attend"},
    )
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Combinations that would read as meaningful and are not
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
@pytest.mark.asyncio
async def test_an_unknown_activity_is_rejected(
    async_client: AsyncClient, clean_db
) -> None:
    conf = await _conference(async_client, "Another Event 2025")
    resp = await async_client.post(
        f"/api/v1/conferences/{conf}/participation",
        json={"person_label": "P", "activity": "keynote"},
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_participation_against_a_missing_conference_is_404(
    async_client: AsyncClient, clean_db
) -> None:
    resp = await async_client.post(
        f"/api/v1/conferences/{uuid.uuid4()}/participation",
        json={"person_label": "P", "activity": "attend"},
    )
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# The event-level facts
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_attendance_summary_round_trips(
    async_client: AsyncClient, clean_db
) -> None:
    conf = await _conference(async_client, "NVIDIA GTC 2025")
    payload = {
        "edition_year": 2025,
        "spend_usd": 18_000,
        "leads_generated": 140,
        "audience_size_estimate": 25_000,
        "attendance_verdict": "would_attend",
        "attendance_notes": "Booth traffic was strong.",
    }
    put = await async_client.put(f"/api/v1/conferences/{conf}/attendance", json=payload)
    assert put.status_code == 200, put.text
    got = (await async_client.get(f"/api/v1/conferences/{conf}/attendance")).json()
    assert got == payload


@pytest.mark.asyncio
async def test_an_unattended_conference_has_empty_attendance(
    async_client: AsyncClient, clean_db
) -> None:
    """Nothing is recorded until somebody records it.

    No defaulted zero spend, no "unsure" verdict pretending to be a
    retrospective nobody has written yet.
    """
    conf = await _conference(async_client, "Snowflake Summit 2027")
    got = (await async_client.get(f"/api/v1/conferences/{conf}/attendance")).json()
    assert got["spend_usd"] is None
    assert got["audience_size_estimate"] is None
    assert got["attendance_verdict"] is None
    assert (
        await async_client.get(f"/api/v1/conferences/{conf}/participation")
    ).json() == []


@pytest.mark.asyncio
async def test_a_nonsense_verdict_is_rejected(
    async_client: AsyncClient, clean_db
) -> None:
    conf = await _conference(async_client, "Databricks Data + AI 2025")
    resp = await async_client.put(
        f"/api/v1/conferences/{conf}/attendance",
        json={"attendance_verdict": "loved_it"},
    )
    assert resp.status_code == 422


# ---------------------------------------------------------------------------
# Lifecycle
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_deleting_the_conference_removes_its_participation(
    async_client: AsyncClient, test_engine, clean_db
) -> None:
    """The rows describe an event. Without the event they describe nothing."""
    conf = await _conference(async_client, "Doomed Event 2025")
    alice = await _sme(test_engine)
    await async_client.post(
        f"/api/v1/conferences/{conf}/participation",
        json={"sme_id": alice, "person_label": "", "activity": "attend"},
    )

    assert (await async_client.delete(f"/api/v1/conferences/{conf}")).status_code in (
        200,
        204,
    )
    async with test_engine.begin() as conn:
        remaining = (
            await conn.execute(
                text(
                    "SELECT count(*) FROM app.participation WHERE conference_id = :c"
                ),
                {"c": conf},
            )
        ).scalar_one()
    assert remaining == 0


@pytest.mark.asyncio
async def test_a_participation_row_can_be_edited_and_removed(
    async_client: AsyncClient, clean_db
) -> None:
    conf = await _conference(async_client, "Editable Event 2025")
    created = (
        await async_client.post(
            f"/api/v1/conferences/{conf}/participation",
            json={"person_label": "P", "activity": "attend"},
        )
    ).json()

    patched = await async_client.patch(
        f"/api/v1/participation/{created['id']}",
        json={"person_label": "P", "activity": "talk"},
    )
    assert patched.status_code == 200, patched.text

    assert (
        await async_client.delete(f"/api/v1/participation/{created['id']}")
    ).status_code == 204
    assert (
        await async_client.get(f"/api/v1/conferences/{conf}/participation")
    ).json() == []
