"""Possible duplicates get surfaced, never merged.

WHY THIS EXISTS
    Dedup at ingest is EXACT — services/extraction.py matches a
    name-plus-year slug against a unique index and refuses anything
    fuzzier. That bias is right there: a false merge applies one
    conference's attendance history, decisions and verdict to another,
    silently and irreversibly, while a duplicate row costs one dismissal.

    Its cost is duplicate rows, and W1 made that bite. The same
    conference now arrives from a keyword sweep, several aggregators and
    an unfiltered feed, so "KubeCon EU 2026" and "KubeCon +
    CloudNativeCon Europe 2026" can both exist.

    This endpoint asks the looser question and does not act on it. That
    is what makes looser matching safe.
"""

from __future__ import annotations

import pytest
from httpx import AsyncClient


async def _conf(client: AsyncClient, name: str, **extra) -> str:
    body = {"name": name, "event_kind": "corporate", **extra}
    r = await client.post("/api/v1/conferences", json=body)
    assert r.status_code == 201, r.text
    return r.json()["conference"]["id"]


@pytest.mark.asyncio
async def test_the_route_is_not_swallowed_by_the_id_route(
    async_client: AsyncClient, clean_db
) -> None:
    """/duplicates is a literal segment competing with /{conference_id}.
    Registered after it, FastAPI would try to parse "duplicates" as a
    UUID and 422. The package __init__ registers it early on purpose."""
    r = await async_client.get("/api/v1/conferences/duplicates")
    assert r.status_code == 200, r.text
    assert "pairs" in r.json()


@pytest.mark.asyncio
async def test_an_abbreviated_name_is_flagged_against_its_full_form(
    async_client: AsyncClient, clean_db
) -> None:
    await _conf(async_client, "KubeCon EU 2026", start_date="2026-03-19")
    await _conf(
        async_client, "KubeCon + CloudNativeCon Europe 2026", start_date="2026-03-20"
    )

    body = (await async_client.get("/api/v1/conferences/duplicates")).json()
    names = {(p["left"]["name"], p["right"]["name"]) for p in body["pairs"]}
    flat = {n for pair in names for n in pair}
    assert "KubeCon EU 2026" in flat
    assert "KubeCon + CloudNativeCon Europe 2026" in flat


@pytest.mark.asyncio
async def test_different_regions_are_not_flagged(
    async_client: AsyncClient, clean_db
) -> None:
    """KubeCon EU and KubeCon NA are genuinely different events with
    different audiences, budgets and outcomes. Merging them would make
    "we went last year" mean the wrong thing."""
    await _conf(async_client, "KubeCon EU 2026", start_date="2026-03-19")
    await _conf(async_client, "KubeCon NA 2026", start_date="2026-11-10")

    body = (await async_client.get("/api/v1/conferences/duplicates")).json()
    assert body["pairs"] == []


@pytest.mark.asyncio
async def test_different_years_are_not_flagged(
    async_client: AsyncClient, clean_db
) -> None:
    """Different years of one event are separate conferences on purpose —
    that is what makes "we attended this last year" meaningful."""
    await _conf(async_client, "PyTorch Conference 2026", start_date="2026-10-01")
    await _conf(async_client, "PyTorch Conference 2027", start_date="2027-10-01")

    body = (await async_client.get("/api/v1/conferences/duplicates")).json()
    assert body["pairs"] == []


@pytest.mark.asyncio
async def test_unrelated_conferences_are_not_flagged(
    async_client: AsyncClient, clean_db
) -> None:
    await _conf(async_client, "NeurIPS 2026", start_date="2026-12-01")
    await _conf(async_client, "WordPress Community Summit 2026", start_date="2026-12-02")

    body = (await async_client.get("/api/v1/conferences/duplicates")).json()
    assert body["pairs"] == []


@pytest.mark.asyncio
async def test_nothing_is_merged_or_modified(
    async_client: AsyncClient, clean_db
) -> None:
    """The whole safety argument. Looser matching is acceptable ONLY
    because the endpoint is advisory — a person confirms or dismisses."""
    a = await _conf(async_client, "PyTorch Conference 2026", start_date="2026-10-01")
    b = await _conf(async_client, "PyTorch Conf 2026", start_date="2026-10-01")

    before = [
        (await async_client.get(f"/api/v1/conferences/{i}")).json() for i in (a, b)
    ]
    body = (await async_client.get("/api/v1/conferences/duplicates")).json()
    assert body["pairs"], "these should be flagged"

    after = [
        (await async_client.get(f"/api/v1/conferences/{i}")).json() for i in (a, b)
    ]
    assert [r["status"] for r in before] == [r["status"] for r in after]
    assert [r["name"] for r in before] == [r["name"] for r in after]
    assert all(r.status_code == 200 for r in [
        await async_client.get(f"/api/v1/conferences/{a}"),
        await async_client.get(f"/api/v1/conferences/{b}"),
    ]), "neither conference was deleted"
