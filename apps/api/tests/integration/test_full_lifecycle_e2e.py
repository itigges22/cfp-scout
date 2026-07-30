"""The whole product path, in one test, through the HTTP surface only.

WHY THIS EXISTS
    Individual joints of this chain are covered elsewhere. Nothing walks
    the entire thing, and the entire thing is what the tool is for:

        a scraped conference is a NEW conference
          -> mark it planning-to-attend
          -> record who is going, when, and what they will do there
          -> once the dates pass (or you say so) it reads as ATTENDED
          -> then the outcome questions open up: cost, leads, verdict
          -> and it all shows up in the dashboard totals

    After merging 33 route modules into 10 and 88 service modules into
    17, "each piece works" and "the chain works" are different claims.
    This asserts the second one, and it only touches the API — no service
    imports, no direct SQL — so it fails the way a user would see it fail.
"""

from __future__ import annotations

from datetime import date, timedelta

import pytest
from httpx import AsyncClient

pytestmark = pytest.mark.asyncio

TODAY = date.today()


async def _json(response, expect: int | tuple[int, ...] = 200):
    allowed = expect if isinstance(expect, tuple) else (expect,)
    assert response.status_code in allowed, (
        f"{response.request.method} {response.request.url.path} -> "
        f"{response.status_code}: {response.text[:400]}"
    )
    return response.json() if response.content else None


async def test_a_conference_travels_the_whole_path(
    async_client: AsyncClient, clean_db: None
) -> None:
    """New -> planning -> attending -> attended -> outcome recorded."""
    # --- 1. it arrives, the way the scraper leaves it ---------------------
    created = await _json(
        await async_client.post(
            "/api/v1/conferences",
            json={
                "name": "Lifecycle Summit 2099",
                # NOT grassroot: the finder list defaults to
                # exclude_grassroot=true, because grassroot events are ones
                # we already run rather than ones we are deciding about. A
                # grassroot conference here would correctly never appear.
                "event_kind": "corporate",
                "website": "https://lifecycle.example/2099",
                "location_city": "Lisbon",
                "location_country": "PT",
                "start_date": str(TODAY - timedelta(days=10)),
                "end_date": str(TODAY - timedelta(days=8)),
            },
        ),
        201,
    )
    conf = created["conference"]["id"]

    # --- 2. it is readable, and appears in the list ------------------------
    detail = await _json(await async_client.get(f"/api/v1/conferences/{conf}"))
    assert detail["name"] == "Lifecycle Summit 2099"

    listing = await _json(await async_client.get("/api/v1/conferences"))
    assert conf in {row["id"] for row in listing["items"]}, (
        "a created conference does not appear in the finder list"
    )

    # --- 3. correcting a bad extraction -----------------------------------
    edited = await _json(
        await async_client.patch(
            f"/api/v1/conferences/{conf}", json={"venue": "Altice Arena"}
        )
    )
    assert edited["venue"] == "Altice Arena"
    assert edited["name"] == "Lifecycle Summit 2099", (
        "PATCH blanked a field that was not in the body"
    )

    # --- 4. the decision — a human says yes --------------------------------
    await _json(
        await async_client.post(
            f"/api/v1/conferences/{conf}/decisions",
            json={"decision": "approved", "reason": "on-strategy, we have speakers"},
        ),
        (200, 201),
    )

    # --- 5. who is going, and what they will do ---------------------------
    plan = await _json(
        await async_client.post(
            f"/api/v1/conferences/{conf}/participation",
            json={
                "person_label": "Alice Ng",
                "activity": "talk",
                "arrives_on": str(TODAY - timedelta(days=11)),
                "departs_on": str(TODAY - timedelta(days=7)),
            },
        ),
        201,
    )
    assert plan["person_label"] == "Alice Ng"

    roster = await _json(
        await async_client.get(f"/api/v1/conferences/{conf}/participation")
    )
    assert {r["person_label"] for r in roster} == {"Alice Ng"}

    # --- 6. it has happened ------------------------------------------------
    await _json(
        await async_client.post(
            f"/api/v1/participation/{plan['id']}/attended", json={"attended": True}
        ),
        (200, 201),
    )

    roster_after = await _json(
        await async_client.get(f"/api/v1/conferences/{conf}/participation")
    )
    assert roster_after[0]["has_attended"] is True, (
        "marking attended did not stick"
    )

    # --- 7. the retrospective ---------------------------------------------
    # Outcome lives on the CONFERENCE, not on a participant: what the trip
    # cost and what it produced are properties of the event, and are
    # deferrable — the operator often has the numbers weeks later.
    await _json(
        await async_client.put(
            f"/api/v1/conferences/{conf}/attendance",
            json={
                "spend_usd": 1250,
                "leads_generated": 42,
                "attendance_verdict": "would_attend",
                "attendance_notes": "strong booth traffic",
            },
        ),
        (200, 201),
    )
    recorded = await _json(
        await async_client.get(f"/api/v1/conferences/{conf}/attendance")
    )
    assert recorded["leads_generated"] == 42, f"outcome did not persist: {recorded}"
    assert recorded["spend_usd"] == 1250

    # --- 8. and the dashboard can still be built --------------------------
    await _json(await async_client.get("/api/v1/conferences/stats/dashboard"))


async def test_status_is_a_decision_not_an_edit(
    async_client: AsyncClient, clean_db: None
) -> None:
    """PATCH must not be able to set status.

    A status change has to leave a Decision row and an audit entry. If it
    can be written through the ordinary edit path it is silently
    overwritten with no record of who or why — and the tracking the whole
    tool exists for has a hole in it.
    """
    created = await _json(
        await async_client.post(
            "/api/v1/conferences",
            json={"name": "Status Guard 2099", "event_kind": "grassroot"},
        ),
        201,
    )
    conf = created["conference"]["id"]
    before = (await _json(await async_client.get(f"/api/v1/conferences/{conf}")))["status"]

    response = await async_client.patch(
        f"/api/v1/conferences/{conf}", json={"status": "approved"}
    )

    if response.status_code < 400:
        after = (await _json(await async_client.get(f"/api/v1/conferences/{conf}")))["status"]
        assert after == before, (
            "PATCH changed status, bypassing the decision record entirely"
        )


async def test_a_decision_is_written_to_the_audit_log(
    async_client: AsyncClient, clean_db: None, test_engine
) -> None:
    """The audit trail is the point of the tool, and it is easy to lose:
    ``write_audit`` only stages the INSERT and the caller commits, so a
    refactor that drops the commit loses the row with no error anywhere.
    """
    from sqlalchemy import text

    created = await _json(
        await async_client.post(
            "/api/v1/conferences",
            json={"name": "Audited Conf 2099", "event_kind": "grassroot"},
        ),
        201,
    )
    conf = created["conference"]["id"]

    await _json(
        await async_client.post(
            f"/api/v1/conferences/{conf}/decisions",
            json={"decision": "rejected", "reason": "wrong audience"},
        ),
        (200, 201),
    )

    async with test_engine.connect() as conn:
        count = (
            await conn.execute(
                text(
                    "SELECT count(*) FROM audit.audit_log "
                    "WHERE target_id = :cid"
                ),
                {"cid": conf},
            )
        ).scalar()

    assert count and count > 0, (
        "a decision left no audit row — write_audit stages the INSERT and "
        "the caller commits, so a dropped commit loses it silently"
    )


async def test_deleting_a_conference_takes_its_children_with_it(
    async_client: AsyncClient, clean_db: None
) -> None:
    """FKs are ondelete=CASCADE. If one were dropped in the model merge,
    the DELETE raises a foreign-key violation instead."""
    created = await _json(
        await async_client.post(
            "/api/v1/conferences",
            json={"name": "Cascade Conf 2099", "event_kind": "grassroot"},
        ),
        201,
    )
    conf = created["conference"]["id"]
    await _json(
        await async_client.post(
            f"/api/v1/conferences/{conf}/participation",
            json={"person_label": "Bob", "activity": "booth"},
        ),
        201,
    )
    await _json(
        await async_client.post(
            f"/api/v1/conferences/{conf}/decisions",
            json={"decision": "approved", "reason": "yes"},
        ),
        (200, 201),
    )

    deleted = await async_client.delete(f"/api/v1/conferences/{conf}")
    assert deleted.status_code in {200, 204}, deleted.text

    gone = await async_client.get(f"/api/v1/conferences/{conf}")
    assert gone.status_code == 404


async def test_paging_is_capped_by_the_setting(
    async_client: AsyncClient, clean_db: None
) -> None:
    """``api_max_page_size`` replaced a module constant. An uncapped page
    holds a database connection long enough to matter."""
    for i in range(3):
        await _json(
            await async_client.post(
                "/api/v1/conferences",
                json={"name": f"Paged Conf {i} 2099", "event_kind": "grassroot"},
            ),
            201,
        )

    # The cap is enforced by rejecting the request, not by silently
    # clamping it — the caller is told the limit rather than being handed
    # fewer rows than asked for with no explanation.
    response = await async_client.get("/api/v1/conferences", params={"per_page": 999999})
    assert response.status_code == 422, response.text
    assert "per_page" in response.text

    ok = await async_client.get("/api/v1/conferences", params={"per_page": 200})
    assert ok.status_code == 200, ok.text


async def test_grassroot_events_are_excluded_from_the_finder_by_default(
    async_client: AsyncClient, clean_db: None
) -> None:
    """A deliberate default that is easy to mistake for a bug.

    ``exclude_grassroot`` defaults to true because a grassroot event is one
    we already run — it is not a candidate we are deciding about, so it
    would only be noise in the finder. It must still be reachable when
    asked for explicitly, or the row becomes invisible in the UI entirely.
    """
    created = await _json(
        await async_client.post(
            "/api/v1/conferences",
            json={"name": "Our Own Meetup 2099", "event_kind": "grassroot"},
        ),
        201,
    )
    conf = created["conference"]["id"]

    default_view = await _json(await async_client.get("/api/v1/conferences"))
    assert conf not in {r["id"] for r in default_view["items"]}

    asked_for = await _json(
        await async_client.get(
            "/api/v1/conferences", params={"exclude_grassroot": "false"}
        )
    )
    assert conf in {r["id"] for r in asked_for["items"]}, (
        "grassroot events are unreachable even when explicitly requested"
    )
