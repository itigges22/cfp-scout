"""Filtering must not invent a new leaderboard.

The boss asked for a ranking, so "#7 of 48" has to mean the same thing on
every screen. That only holds if rank is assigned over the whole cohort and
filters are predicates applied afterwards (D11). The easy mistake — filter
first, then number what is left — makes the top of every filtered view a
"#1", and the number stops carrying information.
"""

from __future__ import annotations

import pytest
from httpx import AsyncClient


async def _conf(client: AsyncClient, name: str, **kw) -> str:
    body = {"name": name, "event_kind": "corporate", **kw}
    r = await client.post("/api/v1/conferences", json=body)
    assert r.status_code == 201, r.text
    return r.json()["conference"]["id"]


async def _listing(client: AsyncClient, **params):
    r = await client.get("/api/v1/conferences", params=params)
    assert r.status_code == 200, r.text
    return r.json()


@pytest.mark.asyncio
async def test_filtering_preserves_the_global_rank(
    async_client: AsyncClient, clean_db
) -> None:
    await _conf(async_client, "Alpha Platform Summit 2099", location_country="DE")
    await _conf(async_client, "Beta Inference Conf 2099", location_country="US")
    await _conf(async_client, "Gamma Cloud Days 2099", location_country="DE")
    await _conf(async_client, "Delta Data Forum 2099", location_country="US")

    everything = await _listing(async_client, per_page=100)
    rank_by_name = {i["name"]: i["rank"] for i in everything["items"]}

    german = await _listing(async_client, per_page=100, country="DE")
    for item in german["items"]:
        assert item["rank"] == rank_by_name[item["name"]], (
            f"{item['name']} was renumbered by the filter: "
            f"{rank_by_name[item['name']]} -> {item['rank']}"
        )


@pytest.mark.asyncio
async def test_ranked_total_counts_the_cohort_not_the_slice(
    async_client: AsyncClient, clean_db
) -> None:
    """``total`` paginates the slice; ``ranked_total`` is the denominator
    for "#7 of 48". Confusing them is how a rank starts contradicting the
    count printed beside it."""
    await _conf(async_client, "Solo German Event 2099", location_country="DE")
    for i in range(3):
        await _conf(async_client, f"US Event {i} 2099", location_country="US")

    german = await _listing(async_client, per_page=100, country="DE")
    assert german["total"] == 1
    assert german["ranked_total"] == 4


@pytest.mark.asyncio
async def test_ranks_are_dense_over_the_cohort(
    async_client: AsyncClient, clean_db
) -> None:
    """Every rank is a real position: rank - 1 conferences score above it."""
    for i in range(4):
        await _conf(async_client, f"Cohort Event {i} 2099")
    body = await _listing(async_client, per_page=100)
    ranks = sorted(i["rank"] for i in body["items"])
    assert ranks[0] == 1
    assert max(ranks) <= len(ranks)


@pytest.mark.asyncio
async def test_country_filter_is_case_insensitive(
    async_client: AsyncClient, clean_db
) -> None:
    await _conf(async_client, "Munich Platform Days 2099", location_country="DE")
    body = await _listing(async_client, per_page=100, country="de")
    assert [i["name"] for i in body["items"]] == ["Munich Platform Days 2099"]


@pytest.mark.asyncio
async def test_date_window_filters(async_client: AsyncClient, clean_db) -> None:
    await _conf(async_client, "Early Event 2099", start_date="2099-01-10")
    await _conf(async_client, "Late Event 2099", start_date="2099-11-10")

    early = await _listing(async_client, per_page=100, starts_before="2099-06-01")
    assert [i["name"] for i in early["items"]] == ["Early Event 2099"]

    late = await _listing(async_client, per_page=100, starts_after="2099-06-01")
    assert [i["name"] for i in late["items"]] == ["Late Event 2099"]


@pytest.mark.asyncio
async def test_cfp_open_needs_evidence(async_client: AsyncClient, clean_db) -> None:
    """No dates recorded means NOT open. Guessing "yes" would put a
    conference in a submit queue on no evidence at all."""
    await _conf(async_client, "Open CFP Event 2099", cfp_close_at="2099-12-01")
    await _conf(async_client, "Unknown CFP Event 2099")

    body = await _listing(async_client, per_page=100, cfp_open=True)
    assert [i["name"] for i in body["items"]] == ["Open CFP Event 2099"]

    closed = await _listing(async_client, per_page=100, cfp_open=False)
    assert "Unknown CFP Event 2099" in [i["name"] for i in closed["items"]]


@pytest.mark.asyncio
async def test_cfp_deadline_window_composes_with_other_filters(
    async_client: AsyncClient, clean_db
) -> None:
    """cfp_closes_within_days keeps only deadlines inside [today, +N] —
    unknown and already-passed deadlines drop — and ANDs with the other
    slice filters instead of replacing them."""
    from datetime import date, timedelta

    soon = (date.today() + timedelta(days=10)).isoformat()
    far = (date.today() + timedelta(days=120)).isoformat()

    await _conf(
        async_client, "Closing Soon US 2099", cfp_close_at=soon, location_country="US"
    )
    await _conf(
        async_client, "Closing Soon DE 2099", cfp_close_at=soon, location_country="DE"
    )
    await _conf(
        async_client, "Closing Later 2099", cfp_close_at=far, location_country="US"
    )
    await _conf(async_client, "No Deadline 2099", location_country="US")

    windowed = await _listing(async_client, per_page=100, cfp_closes_within_days=30)
    names = {i["name"] for i in windowed["items"]}
    assert names == {"Closing Soon US 2099", "Closing Soon DE 2099"}

    combined = await _listing(
        async_client, per_page=100, cfp_closes_within_days=30, country="US"
    )
    assert [i["name"] for i in combined["items"]] == ["Closing Soon US 2099"]


@pytest.mark.asyncio
async def test_cost_filter_keeps_unknown_costs(
    async_client: AsyncClient, clean_db
) -> None:
    """An unknown cost must not be filtered out as if it were expensive —
    that silently hides conferences for having a thin scrape."""
    await _conf(async_client, "Cheap Event 2099", estimated_cost_usd=500)
    await _conf(async_client, "Pricey Event 2099", estimated_cost_usd=9000)
    await _conf(async_client, "Unknown Cost Event 2099")

    body = await _listing(async_client, per_page=100, max_cost_usd=1000)
    names = {i["name"] for i in body["items"]}
    assert "Cheap Event 2099" in names
    assert "Unknown Cost Event 2099" in names
    assert "Pricey Event 2099" not in names


@pytest.mark.asyncio
async def test_sorting_reorders_but_never_renumbers(
    async_client: AsyncClient, clean_db
) -> None:
    await _conf(async_client, "Zulu Event 2099", start_date="2099-02-01")
    await _conf(async_client, "Alpha Event 2099", start_date="2099-09-01")

    by_score = await _listing(async_client, per_page=100)
    rank_by_name = {i["name"]: i["rank"] for i in by_score["items"]}

    for order in ("name", "date"):
        body = await _listing(async_client, per_page=100, sort=order)
        for item in body["items"]:
            assert item["rank"] == rank_by_name[item["name"]], (
                f"sort={order} renumbered {item['name']}"
            )


@pytest.mark.asyncio
async def test_hidden_statuses_are_out_of_the_default_list_but_reachable(
    async_client: AsyncClient, test_engine, clean_db
) -> None:
    """A veto is a review flag, not a deletion — so it must not hide.

    Rejected and quarantined conferences stay out of the finder: one is a
    decision a person already made, the other is data too broken to show.
    A machine opinion is neither, and hiding on one would delete most of
    what discovery finds now that ingestion is deliberately broad and the
    judge runs ungated on every row.

    So: vetoed appears in the default list, and an explicit ?status= must
    still reach every one of these for the operator to review or disagree.
    """
    from sqlalchemy import text as sql_text

    vetoed_id = await _conf(async_client, "Judged Wrong Audience 2099")
    rejected_id = await _conf(async_client, "Human Said No 2099")
    async with test_engine.begin() as conn:
        await conn.execute(
            sql_text("UPDATE app.conferences SET status='vetoed' WHERE id=:i"),
            {"i": vetoed_id},
        )
        await conn.execute(
            sql_text("UPDATE app.conferences SET status='rejected' WHERE id=:i"),
            {"i": rejected_id},
        )

    default_names = [
        i["name"] for i in (await _listing(async_client, per_page=100))["items"]
    ]
    assert "Judged Wrong Audience 2099" in default_names, (
        "a judge veto must not remove a conference from the operator's list"
    )
    assert "Human Said No 2099" not in default_names, (
        "a human rejection should still stay out of the way"
    )

    explicit = await _listing(async_client, per_page=100, status="vetoed")
    assert [i["name"] for i in explicit["items"]] == ["Judged Wrong Audience 2099"]

    reachable = await _listing(async_client, per_page=100, status="rejected")
    assert [i["name"] for i in reachable["items"]] == ["Human Said No 2099"]


@pytest.mark.asyncio
async def test_the_list_returns_the_same_order_every_time(
    async_client: AsyncClient, clean_db
) -> None:
    """Ties must not reshuffle between identical requests.

    With no ORDER BY on the score path, Postgres was free to return tied
    conferences in a different order each call — so a paginated list could
    drop rows and repeat others between pages.
    """
    for i in range(8):
        await _conf(async_client, f"Identical Event {i} 2099")

    runs = [
        [i["name"] for i in (await _listing(async_client, per_page=100))["items"]]
        for _ in range(3)
    ]
    assert runs[0] == runs[1] == runs[2], "the list order is not stable"


@pytest.mark.asyncio
async def test_pagination_neither_drops_nor_repeats(
    async_client: AsyncClient, clean_db
) -> None:
    for i in range(9):
        await _conf(async_client, f"Paged Event {i} 2099")

    seen: list[str] = []
    for page in (1, 2, 3):
        body = await _listing(async_client, per_page=3, page=page)
        seen += [i["name"] for i in body["items"]]

    assert len(seen) == len(set(seen)), f"pagination repeated rows: {seen}"
    assert len(seen) == 9, f"pagination dropped rows: got {len(seen)} of 9"


@pytest.mark.asyncio
async def test_the_stats_routes_are_not_shadowed_by_the_id_route(
    async_client: AsyncClient, clean_db
) -> None:
    """Registration order is load-bearing after the P6 split.

    FastAPI matches in the order routes are added. If /{conference_id} were
    registered before /stats/dashboard, this request would be read as a
    conference whose id is the literal string "stats" and 422 on the UUID
    parse. The old single file was safe by accident; the package makes the
    order explicit, and this proves it.
    """
    for path in ("/api/v1/conferences/stats/dashboard",
                 "/api/v1/conferences/stats/by-location"):
        r = await async_client.get(path)
        assert r.status_code == 200, f"{path} -> {r.status_code}: {r.text[:160]}"


@pytest.mark.asyncio
async def test_export_matches_the_filtered_view(
    async_client: AsyncClient, clean_db
) -> None:
    """The export contains exactly the rows the filters keep, in both
    formats, with the outcome columns present even when nothing has
    filled them in yet."""
    await _conf(async_client, "Export DE Event 2099", location_country="DE")
    await _conf(async_client, "Export US Event 2099", location_country="US")

    r = await async_client.get(
        "/api/v1/conferences/export", params={"format": "csv", "country": "DE"}
    )
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/csv")
    assert "attachment" in r.headers["content-disposition"]
    body = r.content.decode("utf-8-sig")
    lines = [ln for ln in body.splitlines() if ln.strip()]
    header, rows = lines[0], lines[1:]
    # Unfilled tracking columns still ship — that is the boss's checklist.
    for col in ("Actual spend (USD)", "Leads generated", "Worth it?", "Who is going"):
        assert col in header
    assert len(rows) == 1
    assert "Export DE Event 2099" in rows[0]
    assert "Export US Event 2099" not in body

    r2 = await async_client.get(
        "/api/v1/conferences/export", params={"format": "xlsx", "country": "DE"}
    )
    assert r2.status_code == 200
    assert "spreadsheetml" in r2.headers["content-type"]
    # XLSX files are zip archives — PK magic proves a real workbook.
    assert r2.content[:2] == b"PK"


@pytest.mark.asyncio
async def test_secondary_sort_breaks_ties_only(
    async_client: AsyncClient, clean_db
) -> None:
    """then_by orders WITHIN groups the primary key ties, and never
    reorders across them — and, like the primary, never renumbers."""
    await _conf(
        async_client, "Same Day Zed 2099", cfp_close_at="2099-05-01", start_date="2099-08-01"
    )
    await _conf(
        async_client, "Same Day Alpha 2099", cfp_close_at="2099-05-01", start_date="2099-08-01"
    )
    await _conf(
        async_client, "Earlier Close Zulu 2099", cfp_close_at="2099-03-01", start_date="2099-06-01"
    )

    body = await _listing(
        async_client, per_page=100, sort="cfp_close", then_by="name",
        include_closed_cfp=True,
    )
    names = [i["name"] for i in body["items"]]
    # Earlier deadline stays first regardless of name; the tied pair
    # orders alphabetically.
    assert names == [
        "Earlier Close Zulu 2099",
        "Same Day Alpha 2099",
        "Same Day Zed 2099",
    ]

    plain = await _listing(async_client, per_page=100, include_closed_cfp=True)
    rank_by_name = {i["name"]: i["rank"] for i in plain["items"]}
    for item in body["items"]:
        assert item["rank"] == rank_by_name[item["name"]]
