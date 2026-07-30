"""Per-SME and per-pillar performance analytics.

Both endpoints aggregate the "who is going" rows plus the per-conference
outcome fields (spend, leads, worth-it) server-side — the frontend only
renders. Spend and leads are EVENT-level numbers: an SME's totals are
the outcomes of events they attended, and a conference aligned to two
pillars counts toward both pillars.
"""

from __future__ import annotations

import uuid
from datetime import date, timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy import text


async def _conf(engine, name: str, *, spend=None, leads=None, verdict=None, start_days=-30) -> str:
    cid = str(uuid.uuid4())
    async with engine.begin() as conn:
        await conn.execute(
            text(
                "INSERT INTO app.conferences "
                "(id, name, slug, status, event_kind, topics, cfp_topics_of_interest, "
                " cfp_deadlines, is_virtual, start_date, spend_usd, leads_generated, "
                " attendance_verdict) "
                "VALUES (:id, :name, :slug, 'approved', 'corporate', '{}', '{}', '[]', "
                " false, :start, :spend, :leads, :verdict)"
            ),
            {
                "id": cid, "name": name, "slug": f"an-{cid[:8]}",
                "start": date.today() + timedelta(days=start_days),
                "spend": spend, "leads": leads, "verdict": verdict,
            },
        )
    return cid


async def _sme(engine, name: str) -> str:
    sid = str(uuid.uuid4())
    async with engine.begin() as conn:
        await conn.execute(
            text(
                "INSERT INTO app.smes (id, full_name, team, audience_focus, "
                "location_country, bio, languages, external_links, is_active) "
                "VALUES (:id, :name, 'Eng', '{}', 'US', "
                "'A sufficiently long bio for analytics testing.', '{}', '{}', true)"
            ),
            {"id": sid, "name": name},
        )
    return sid


async def _go(client: AsyncClient, conf_id: str, sme_id: str, activity: str, attended: bool):
    r = await client.post(
        f"/api/v1/conferences/{conf_id}/participation",
        json={"sme_id": sme_id, "person_label": "X", "activity": activity},
    )
    assert r.status_code == 201, r.text
    if attended:
        r2 = await client.post(
            f"/api/v1/participation/{r.json()['id']}/attended",
            json={"attended": True},
        )
        assert r2.status_code == 200


@pytest.mark.asyncio
async def test_sme_analytics_aggregates_their_events(
    async_client: AsyncClient, clean_db, test_engine
) -> None:
    sme = await _sme(test_engine, "Analytics SME")
    went = await _conf(
        test_engine, "Went Conf", spend=2000, leads=10, verdict="would_attend"
    )
    upcoming = await _conf(test_engine, "Upcoming Conf", start_days=30)
    await _go(async_client, went, sme, "talk", attended=True)
    await _go(async_client, upcoming, sme, "attend", attended=False)

    r = await async_client.get(f"/api/v1/smes/{sme}/analytics")
    assert r.status_code == 200
    a = r.json()
    assert a["events_total"] == 2
    assert a["events_attended"] == 1
    assert a["events_upcoming"] == 1
    assert a["by_activity"] == {"talk": 1, "attend": 1}
    assert a["attended_events_spend_usd"] == 2000
    assert a["attended_events_leads"] == 10
    assert a["verdicts"] == {"would_attend": 1}


@pytest.mark.asyncio
async def test_pillar_analytics_aggregates_aligned_outcomes(
    async_client: AsyncClient, clean_db, test_engine
) -> None:
    pid = str(uuid.uuid4())
    async with test_engine.begin() as conn:
        await conn.execute(
            text(
                "INSERT INTO app.strategic_pillars (id, name, description, display_order) "
                "VALUES (:id, 'AnalyticsPillar', 'd', 60)"
            ),
            {"id": pid},
        )
    sme = await _sme(test_engine, "Pillar SME")
    went = await _conf(
        test_engine, "Pillar Went Conf", spend=1000, leads=20, verdict="unsure"
    )
    # Aligned but nobody went — must not add to spend.
    idle = await _conf(test_engine, "Pillar Idle Conf")
    async with test_engine.begin() as conn:
        for cid in (went, idle):
            await conn.execute(
                text(
                    "INSERT INTO app.conference_pillars (conference_id, pillar_id, score) "
                    "VALUES (:cid, :pid, 0.5)"
                ),
                {"cid": cid, "pid": pid},
            )
    await _go(async_client, went, sme, "booth", attended=True)

    r = await async_client.get(f"/api/v1/pillars/{pid}/analytics")
    assert r.status_code == 200
    a = r.json()
    assert a["conferences_aligned"] == 2
    assert a["conferences_attended"] == 1
    assert a["spend_usd_total"] == 1000
    assert a["leads_total"] == 20
    assert a["cost_per_lead_usd"] == 50.0
    assert a["verdicts"] == {"unsure": 1}
    assert len(a["attended"]) == 1
    assert a["attended"][0]["n_people"] == 1


@pytest.mark.asyncio
async def test_multiple_smes_on_one_conference(
    async_client: AsyncClient, clean_db, test_engine
) -> None:
    """The usual case: several people at one event, each their own row,
    each visible in their own analytics."""
    conf = await _conf(test_engine, "Team Trip Conf", spend=3000, leads=5)
    s1 = await _sme(test_engine, "First SME")
    s2 = await _sme(test_engine, "Second SME")
    await _go(async_client, conf, s1, "talk", attended=True)
    await _go(async_client, conf, s2, "booth", attended=True)

    for sid in (s1, s2):
        r = await async_client.get(f"/api/v1/smes/{sid}/analytics")
        assert r.json()["events_attended"] == 1
        assert r.json()["attended_events_spend_usd"] == 3000


@pytest.mark.asyncio
async def test_analytics_overview_endpoint_bins_server_side(
    async_client: AsyncClient, clean_db, test_engine
) -> None:
    """The chart endpoint returns pre-binned series and respects the
    country filter — the frontend never aggregates."""
    await _conf(test_engine, "US Chart Conf", start_days=10)
    await _conf(test_engine, "US Chart Conf 2", start_days=20)
    async with test_engine.begin() as conn:
        await conn.execute(
            text("UPDATE app.conferences SET location_country='US'")
        )

    r = await async_client.get("/api/v1/analytics/overview", params={"country": "US"})
    assert r.status_code == 200
    a = r.json()
    assert a["conference_count"] == 2
    assert a["filters"]["country"] == "US"
    assert len(a["score_histogram"]) == 10
    assert sum(b["count"] for b in a["status_funnel"]) == 2

    other = await async_client.get(
        "/api/v1/analytics/overview", params={"country": "DE"}
    )
    assert other.json()["conference_count"] == 0
