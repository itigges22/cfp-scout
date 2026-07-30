"""discovered -> planning to attend -> attended.

WHY THIS EXISTS
    Only the two ends of that chain existed. ``approved`` was wired, and
    attendance was inferred from participation rows existing. Between them
    there was nothing — no way to say "we intend to send Alice to KubeCon,
    arriving Tuesday, working the booth". That middle is where a
    conference sits for most of its life, and it is where "track when and
    who is going" lives.

    The operator's chain, verbatim: a scraped conference is a new
    conference; mark it planning-to-attend and that unlocks cost, who is
    attending, when, and type of attendance; once attended "either by
    acknowledgement of the dates attending or by setting it to attended",
    ask for actual cost and leads generated, "which they can add later on
    if they don't have already".

    The tests below pin each joint of that chain, and one design decision
    worth defending: attendance is DERIVED, not stored.
"""

from __future__ import annotations

from datetime import date, timedelta

import pytest
from httpx import AsyncClient

TODAY = date.today()


async def _conference(client: AsyncClient, name: str) -> str:
    r = await client.post(
        "/api/v1/conferences", json={"name": name, "event_kind": "grassroot"}
    )
    assert r.status_code == 201, r.text
    return r.json()["conference"]["id"]


async def _plan(client: AsyncClient, conf: str, **kw) -> dict:
    body = {"person_label": "Alice Ng", "activity": "booth", **kw}
    r = await client.post(f"/api/v1/conferences/{conf}/participation", json=body)
    assert r.status_code == 201, r.text
    return r.json()


# --- the planning state ----------------------------------------------------
@pytest.mark.asyncio
async def test_a_plan_records_who_when_and_what_they_will_do(
    async_client: AsyncClient, clean_db
) -> None:
    """The four things marking a conference planning-to-attend unlocks."""
    conf = await _conference(async_client, "KubeCon Europe 2099")
    row = await _plan(
        async_client,
        conf,
        activity="booth",
        arrives_on=str(TODAY + timedelta(days=30)),
        departs_on=str(TODAY + timedelta(days=33)),
    )

    assert row["person_label"] == "Alice Ng"
    assert row["activity"] == "booth"
    assert row["arrives_on"] == str(TODAY + timedelta(days=30))
    assert row["departs_on"] == str(TODAY + timedelta(days=33))
    # Future trip: planned, not attended.
    assert row["has_attended"] is False
    assert row["attended_at"] is None


@pytest.mark.asyncio
async def test_per_person_dates_are_independent_of_the_conference_dates(
    async_client: AsyncClient, clean_db
) -> None:
    """People arrive late, leave early, or cover one day of three. Storing
    only the conference's dates cannot answer "who is on the ground on
    Wednesday", which is a question the team actually asks."""
    conf = await _conference(async_client, "Multi Day Summit 2099")
    early = await _plan(
        async_client, conf,
        person_label="Alice", activity="booth",
        arrives_on=str(TODAY + timedelta(days=10)),
        departs_on=str(TODAY + timedelta(days=11)),
    )
    late = await _plan(
        async_client, conf,
        person_label="Bob", activity="talk",
        arrives_on=str(TODAY + timedelta(days=12)),
        departs_on=str(TODAY + timedelta(days=13)),
    )
    assert early["departs_on"] != late["arrives_on"]

    listed = (await async_client.get(f"/api/v1/conferences/{conf}/participation")).json()
    assert {r["person_label"] for r in listed} == {"Alice", "Bob"}


@pytest.mark.asyncio
async def test_departure_before_arrival_is_refused(
    async_client: AsyncClient, clean_db
) -> None:
    conf = await _conference(async_client, "Backwards Trip 2099")
    r = await async_client.post(
        f"/api/v1/conferences/{conf}/participation",
        json={
            "person_label": "Alice",
            "activity": "attend",
            "arrives_on": str(TODAY + timedelta(days=5)),
            "departs_on": str(TODAY + timedelta(days=2)),
        },
    )
    assert r.status_code == 422


# --- the transition to attended -------------------------------------------
@pytest.mark.asyncio
async def test_a_trip_whose_dates_have_passed_reads_as_attended(
    async_client: AsyncClient, clean_db
) -> None:
    """One of the operator's two routes: "by acknowledgement of the dates
    attending". No cron, no endpoint call — the predicate answers it."""
    conf = await _conference(async_client, "Already Happened 2020")
    row = await _plan(
        async_client, conf,
        arrives_on=str(TODAY - timedelta(days=10)),
        departs_on=str(TODAY - timedelta(days=8)),
    )
    assert row["has_attended"] is True
    # ...and nothing wrote a confirmation to get there.
    assert row["attended_at"] is None


@pytest.mark.asyncio
async def test_marking_attended_works_without_any_dates(
    async_client: AsyncClient, clean_db
) -> None:
    """The other route: "or by setting it to attended". Needed for what
    dates cannot answer — someone went at short notice."""
    conf = await _conference(async_client, "Short Notice 2099")
    row = await _plan(async_client, conf, activity="attend")
    assert row["has_attended"] is False

    r = await async_client.post(
        f"/api/v1/participation/{row['id']}/attended", json={"attended": True}
    )
    assert r.status_code == 200, r.text
    assert r.json()["has_attended"] is True
    assert r.json()["attended_at"] is not None


@pytest.mark.asyncio
async def test_marking_attended_can_be_undone(
    async_client: AsyncClient, clean_db
) -> None:
    """A record nobody can correct stops being trusted, and the whole
    point of this table is that the team believes what it says."""
    conf = await _conference(async_client, "Mistaken Click 2099")
    row = await _plan(async_client, conf, activity="attend")

    await async_client.post(
        f"/api/v1/participation/{row['id']}/attended", json={"attended": True}
    )
    r = await async_client.post(
        f"/api/v1/participation/{row['id']}/attended", json={"attended": False}
    )
    assert r.status_code == 200
    assert r.json()["has_attended"] is False
    assert r.json()["attended_at"] is None


@pytest.mark.asyncio
async def test_unmarking_does_not_override_dates_that_have_passed(
    async_client: AsyncClient, clean_db
) -> None:
    """Clearing the confirmation does not clear the dates, so a past trip
    still reads as attended. The derived answer is the honest one — the
    trip's dates went by regardless of which button was clicked."""
    conf = await _conference(async_client, "Past Trip 2020")
    row = await _plan(
        async_client, conf,
        arrives_on=str(TODAY - timedelta(days=6)),
        departs_on=str(TODAY - timedelta(days=4)),
    )
    r = await async_client.post(
        f"/api/v1/participation/{row['id']}/attended", json={"attended": False}
    )
    assert r.json()["attended_at"] is None
    assert r.json()["has_attended"] is True


# --- the outcome fields ----------------------------------------------------
@pytest.mark.asyncio
async def test_leads_generated_round_trips(
    async_client: AsyncClient, clean_db
) -> None:
    """The last of the four things an attended conference carries, and the
    only one that had no representation anywhere — no column, no schema
    field, no endpoint."""
    conf = await _conference(async_client, "Lead Machine 2099")
    put = await async_client.put(
        f"/api/v1/conferences/{conf}/attendance",
        json={"spend_usd": 12_000, "leads_generated": 87},
    )
    assert put.status_code == 200, put.text

    got = (await async_client.get(f"/api/v1/conferences/{conf}/attendance")).json()
    assert got["leads_generated"] == 87
    assert got["spend_usd"] == 12_000


@pytest.mark.asyncio
async def test_outcome_fields_can_all_be_left_for_later(
    async_client: AsyncClient, clean_db
) -> None:
    """The operator asked for these to be deferrable: "which they can add
    later on if they don't have already". A form that refused to save
    without them would mean nothing gets recorded at all."""
    conf = await _conference(async_client, "Numbers Pending 2099")
    r = await async_client.put(
        f"/api/v1/conferences/{conf}/attendance", json={}
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["leads_generated"] is None
    assert body["spend_usd"] is None
    assert body["attendance_verdict"] is None


@pytest.mark.asyncio
async def test_negative_leads_are_refused(
    async_client: AsyncClient, clean_db
) -> None:
    conf = await _conference(async_client, "Bad Data 2099")
    r = await async_client.put(
        f"/api/v1/conferences/{conf}/attendance", json={"leads_generated": -5}
    )
    assert r.status_code == 422


# --- the design decision ---------------------------------------------------
def test_attendance_is_not_a_conference_status() -> None:
    """Neither 'planning' nor 'attended' may become a status value.

    conferences.status already carries extraction state, gate outcomes,
    the judge's veto AND the operator's approve/reject decision. Adding a
    fifth meaning is how the decay pass came to overwrite recorded
    decisions — a background job wrote one meaning and destroyed another.

    Attendance is a property of participation rows and dates. Derived
    answers cannot be clobbered by a cron.
    """
    from app.services import conferences as cs

    assert "attended" not in cs.ALL
    assert "planning" not in cs.ALL
    assert "planned" not in cs.ALL


# --- one record of a CfP submission ----------------------------------------
@pytest.mark.asyncio
async def test_participation_no_longer_records_a_submission_outcome(
    async_client: AsyncClient, clean_db
) -> None:
    """Two tables used to store "this talk was pitched here and here is
    what happened": talk_submissions, and participation with
    activity='talk' + outcome. Nothing reconciled them, their vocabularies
    disagreed, and the reuse-risk check counted only one — so a submission
    recorded through participation was invisible to the warning meant to
    catch over-pitching.

    They were never the same fact. A submission is something we did
    BEFORE the event; a participation row says who was THERE. Only
    `outcome` conflated them, and its one attendance-shaped value
    ('delivered') is now `attended_at`.
    """
    conf = await _conference(async_client, "One Record 2099")
    r = await async_client.post(
        f"/api/v1/conferences/{conf}/participation",
        json={"person_label": "Alice", "activity": "talk", "outcome": "accepted"},
    )
    assert r.status_code == 422, "participation must not accept a submission outcome"
    assert "outcome" in r.text


@pytest.mark.asyncio
async def test_participation_still_records_which_talk_was_given(
    async_client: AsyncClient, clean_db
) -> None:
    """talk_id stays — which talk somebody gave is genuinely an
    attendance fact, unlike whether an abstract was accepted."""
    conf = await _conference(async_client, "Talk Given 2099")
    r = await async_client.post(
        f"/api/v1/conferences/{conf}/participation",
        json={"person_label": "Alice", "activity": "talk"},
    )
    assert r.status_code == 201, r.text
    assert "talk_id" in r.json()


@pytest.mark.asyncio
async def test_a_booth_shift_still_cannot_carry_an_abstract(
    async_client: AsyncClient, clean_db
) -> None:
    conf = await _conference(async_client, "Booth Only 2099")
    import uuid as _uuid

    r = await async_client.post(
        f"/api/v1/conferences/{conf}/participation",
        json={
            "person_label": "Bob",
            "activity": "booth",
            "talk_id": str(_uuid.uuid4()),
        },
    )
    assert r.status_code == 422


# --- the full chain the UI now drives --------------------------------------
@pytest.mark.asyncio
async def test_the_whole_chain_end_to_end(
    async_client: AsyncClient, clean_db
) -> None:
    """discovered -> planning to attend -> attended -> outcome recorded.

    Every step here is one the AttendancePanel calls. Until that panel
    existed the app could SHOW "previously attended" in three places and
    set it in none, and actual cost, leads and the worth-it verdict had
    columns and endpoints that nothing in the UI ever reached.
    """
    conf = await _conference(async_client, "Full Chain 2099")

    # 1. planning: who is going, when, doing what
    plan = await _plan(
        async_client, conf,
        person_label="Alice Ng", activity="booth",
        arrives_on=str(TODAY + timedelta(days=20)),
        departs_on=str(TODAY + timedelta(days=22)),
    )
    assert plan["has_attended"] is False, "a future trip is a plan, not a record"

    # 2. the conference now has someone going
    listed = (await async_client.get(f"/api/v1/conferences/{conf}/participation")).json()
    assert [r["person_label"] for r in listed] == ["Alice Ng"]

    # 3. attended, confirmed by a person rather than by the calendar
    marked = await async_client.post(
        f"/api/v1/participation/{plan['id']}/attended", json={"attended": True}
    )
    assert marked.status_code == 200
    assert marked.json()["has_attended"] is True

    # 4. the outcome, recorded later, as the operator asked
    put = await async_client.put(
        f"/api/v1/conferences/{conf}/attendance",
        json={
            "spend_usd": 8_400,
            "leads_generated": 62,
            "attendance_verdict": "would_attend",
            "attendance_notes": "Booth was busy all three days.",
        },
    )
    assert put.status_code == 200, put.text

    got = (await async_client.get(f"/api/v1/conferences/{conf}/attendance")).json()
    assert got["leads_generated"] == 62
    assert got["attendance_verdict"] == "would_attend"

    # 5. and the brief reflects it, rather than a matcher's suggestion
    brief = (await async_client.get(f"/api/v1/conferences/{conf}/brief")).json()
    assert brief["attendees"]["source"] == "participation"
    assert brief["attendees"]["members"][0]["person_label"] == "Alice Ng"
    assert brief["attendees"]["members"][0]["has_attended"] is True
