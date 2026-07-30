"""A scraped conference must be correctable.

WHY THIS EXISTS
    There was no write path on a conference at all — POST to create, GET,
    DELETE, and nothing between. So a row's dates, location, venue or cost
    could never be fixed after ingestion, and the extraction LLM's answer
    was final.

    Most rows come from the scraper, which makes "the machine guessed and
    you cannot argue" the normal case rather than the edge case.

    Separately, several fields were WRITE-ONLY: accepted on create,
    persisted, and absent from every read. ``estimated_cost_usd`` could be
    filtered on via ?max_cost_usd= but never seen, so the operator was
    filtering against a number they could not inspect. ``cfp_open_at`` was
    worse — cfp_is_open() branches on it, so the open/closed verdict on
    screen depended on a field the client had no way to read.
"""

from __future__ import annotations

import pytest
from httpx import AsyncClient


async def _conference(client: AsyncClient, name: str, **extra) -> str:
    body = {"name": name, "event_kind": "grassroot", **extra}
    r = await client.post("/api/v1/conferences", json=body)
    assert r.status_code == 201, r.text
    return r.json()["conference"]["id"]


# --- the fields are visible now --------------------------------------------
@pytest.mark.asyncio
async def test_previously_write_only_fields_come_back_on_read(
    async_client: AsyncClient, clean_db
) -> None:
    cid = await _conference(
        async_client,
        "Costed Event 2099",
        estimated_cost_usd=4200,
        venue="Hall 7",
        acceptance_rate_percent=31,
        cfp_open_at="2099-01-01",
    )
    got = (await async_client.get(f"/api/v1/conferences/{cid}")).json()

    assert got["estimated_cost_usd"] == 4200
    assert got["venue"] == "Hall 7"
    assert got["acceptance_rate_percent"] == 31
    assert got["cfp_open_at"] == "2099-01-01"


@pytest.mark.asyncio
async def test_the_list_shows_them_too(
    async_client: AsyncClient, clean_db
) -> None:
    """Filtering on ?max_cost_usd= is only usable if the cost is visible
    in the rows it filters.

    Uses event_kind='corporate': grassroot events are deliberately
    auto-approved and kept out of the finder, so they never appear here.
    """
    await _conference(
        async_client, "Listed Cost 2099", event_kind="corporate", estimated_cost_usd=999
    )
    body = (await async_client.get("/api/v1/conferences?per_page=100")).json()
    row = next(r for r in body["items"] if r["name"] == "Listed Cost 2099")
    assert row["estimated_cost_usd"] == 999


# --- editing ---------------------------------------------------------------
@pytest.mark.asyncio
async def test_a_conference_can_be_corrected(
    async_client: AsyncClient, clean_db
) -> None:
    cid = await _conference(async_client, "Wrong Venue 2099", venue="Hall 1")
    r = await async_client.patch(
        f"/api/v1/conferences/{cid}",
        json={"venue": "Hall 4", "location_city": "Berlin"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["venue"] == "Hall 4"
    assert r.json()["location_city"] == "Berlin"


@pytest.mark.asyncio
async def test_a_partial_edit_does_not_blank_untouched_fields(
    async_client: AsyncClient, clean_db
) -> None:
    """The reason the route uses exclude_unset. A form that submits one
    field must not wipe the rest of the row."""
    cid = await _conference(
        async_client,
        "Keep My Dates 2099",
        start_date="2099-06-01",
        estimated_cost_usd=1500,
    )
    r = await async_client.patch(f"/api/v1/conferences/{cid}", json={"venue": "Hall 9"})
    assert r.status_code == 200
    body = r.json()
    assert body["venue"] == "Hall 9"
    assert body["start_date"] == "2099-06-01", "an untouched date was cleared"
    assert body["estimated_cost_usd"] == 1500, "an untouched cost was cleared"


@pytest.mark.asyncio
async def test_an_explicit_null_does_clear_a_field(
    async_client: AsyncClient, clean_db
) -> None:
    """"Absent" and "null" must mean different things, or there is no way
    to undo a bad extraction."""
    cid = await _conference(async_client, "Bad Extraction 2099", venue="Nonsense")
    r = await async_client.patch(f"/api/v1/conferences/{cid}", json={"venue": None})
    assert r.status_code == 200
    assert r.json()["venue"] is None


@pytest.mark.asyncio
async def test_an_empty_patch_is_a_no_op(
    async_client: AsyncClient, clean_db
) -> None:
    cid = await _conference(async_client, "Nothing To Say 2099", venue="Hall 2")
    r = await async_client.patch(f"/api/v1/conferences/{cid}", json={})
    assert r.status_code == 200
    assert r.json()["venue"] == "Hall 2"


@pytest.mark.asyncio
async def test_status_cannot_be_edited_through_the_patch_route(
    async_client: AsyncClient, clean_db
) -> None:
    """Changing a status is a DECISION. It goes through POST /decisions so
    it produces a Decision row and an audit entry. An edit form that could
    quietly flip an approval would be the decay pass's defect with a human
    driving it."""
    cid = await _conference(async_client, "Not Your Status 2099")
    r = await async_client.patch(
        f"/api/v1/conferences/{cid}", json={"status": "approved"}
    )
    assert r.status_code == 422, "status must not be an editable field"


@pytest.mark.asyncio
async def test_slug_cannot_be_edited(
    async_client: AsyncClient, clean_db
) -> None:
    """It is derived identity — rewriting it orphans the dedup key that
    stops the same conference being ingested twice."""
    cid = await _conference(async_client, "Stable Identity 2099")
    r = await async_client.patch(
        f"/api/v1/conferences/{cid}", json={"slug": "something-else"}
    )
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_end_before_start_is_refused(
    async_client: AsyncClient, clean_db
) -> None:
    cid = await _conference(async_client, "Time Travel 2099")
    r = await async_client.patch(
        f"/api/v1/conferences/{cid}",
        json={"start_date": "2099-06-10", "end_date": "2099-06-01"},
    )
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_editing_a_missing_conference_is_404(
    async_client: AsyncClient, clean_db
) -> None:
    import uuid

    r = await async_client.patch(
        f"/api/v1/conferences/{uuid.uuid4()}", json={"venue": "x"}
    )
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_an_edit_writes_an_audit_row(
    async_client: AsyncClient, test_engine, clean_db
) -> None:
    """Every other mutation in the codebase records one. The decay pass
    not doing so is why nobody noticed it overwriting decisions."""
    from sqlalchemy import text as sql_text

    cid = await _conference(async_client, "Audited Edit 2099")
    await async_client.patch(f"/api/v1/conferences/{cid}", json={"venue": "Hall 3"})

    async with test_engine.begin() as conn:
        n = (
            await conn.execute(
                sql_text(
                    "SELECT count(*) FROM audit.audit_log "
                    "WHERE target_id = :i AND action = 'conference.updated'"
                ),
                {"i": cid},
            )
        ).scalar()
    assert n == 1


# --- logistics -------------------------------------------------------------
@pytest.mark.asyncio
async def test_logistics_persist_server_side(
    async_client: AsyncClient, clean_db
) -> None:
    """These four fields used to live in localStorage under a key the
    BACKEND computed and handed to the frontend. So "are the flights
    booked" was visible to one person, on one machine, until a cache
    clear removed it — for a tool whose stated purpose is full tracking.
    """
    cid = await _conference(async_client, "Logistics Event 2099")
    r = await async_client.patch(
        f"/api/v1/conferences/{cid}",
        json={
            "logistics_travel": "Flights booked, Anna has the confirmation",
            "logistics_sponsorship": "Gold tier, invoice paid",
        },
    )
    assert r.status_code == 200, r.text

    got = (await async_client.get(f"/api/v1/conferences/{cid}")).json()
    assert got["logistics_travel"].startswith("Flights booked")
    assert got["logistics_sponsorship"] == "Gold tier, invoice paid"
    # Untouched slots stay empty rather than null — every conference has
    # all four, so no read path needs a None check.
    assert got["logistics_lodging"] == ""
    assert got["logistics_booth"] == ""


@pytest.mark.asyncio
async def test_the_brief_serves_logistics_not_a_storage_key(
    async_client: AsyncClient, clean_db
) -> None:
    cid = await _conference(async_client, "Brief Logistics 2099")
    await async_client.patch(
        f"/api/v1/conferences/{cid}", json={"logistics_lodging": "Hotel Ibis, 3 nights"}
    )
    brief = (await async_client.get(f"/api/v1/conferences/{cid}/brief")).json()

    assert "logistics_placeholder" not in brief, (
        "the brief is still handing the frontend a localStorage key"
    )
    assert brief["logistics"]["lodging"] == "Hotel Ibis, 3 nights"
