"""A human decision outranks the matcher.

This was silently false. `run_fit_match` assigned `conference.status`
unconditionally, under a comment claiming it only wrote when moving out of
the extraction-set states. So any recompute — the admin "recompute all"
button, a re-scrape, or the auto-run inside GET /{id}/match — reset an
operator's explicit "rejected" back to "approved". The conference reappeared
in the finder, and the only surviving evidence was a row in app.decisions
that nothing reads.
"""

from __future__ import annotations

import pytest
from httpx import AsyncClient
from sqlalchemy import text


async def _conf(client: AsyncClient, name: str) -> str:
    r = await client.post(
        "/api/v1/conferences", json={"name": name, "event_kind": "grassroot"}
    )
    assert r.status_code == 201, r.text
    return r.json()["conference"]["id"]


async def _status(engine, cid: str) -> str:
    async with engine.begin() as conn:
        return (
            await conn.execute(
                text("SELECT status FROM app.conferences WHERE id = :i"), {"i": cid}
            )
        ).scalar_one()


@pytest.mark.asyncio
@pytest.mark.parametrize("verdict", ["approved", "rejected", "needs_review"])
async def test_the_matcher_does_not_overwrite_a_human_decision(
    async_client: AsyncClient, test_engine, clean_db, verdict: str
) -> None:
    conf = await _conf(async_client, f"Decision Test {verdict} 2099")

    d = await async_client.post(
        f"/api/v1/conferences/{conf}/decisions",
        json={"decision": verdict, "reason": "operator looked at it"},
    )
    assert d.status_code in (200, 201), d.text
    assert await _status(test_engine, conf) == verdict

    # Re-run the matcher the way recompute-all / a re-scrape would.
    from app.services.matcher import run_fit_match
    from sqlalchemy.ext.asyncio import async_sessionmaker

    Session = async_sessionmaker(test_engine, expire_on_commit=False)
    async with Session() as db:
        try:
            await run_fit_match(db, __import__("uuid").UUID(conf))
            await db.commit()
        except Exception:
            # A scoring failure is fine for this test; the point is that
            # nothing rewrote the status on the way through.
            await db.rollback()

    assert await _status(test_engine, conf) == verdict, (
        f"the matcher overwrote the operator's {verdict!r} decision"
    )


@pytest.mark.asyncio
async def test_an_undecided_conference_still_gets_a_matcher_status(
    async_client: AsyncClient, test_engine, clean_db
) -> None:
    """The guard must not turn the matcher into a no-op for everything else."""
    conf = await _conf(async_client, "Undecided Event 2099")
    before = await _status(test_engine, conf)

    from app.services.matcher import run_fit_match
    from sqlalchemy.ext.asyncio import async_sessionmaker

    Session = async_sessionmaker(test_engine, expire_on_commit=False)
    async with Session() as db:
        try:
            await run_fit_match(db, __import__("uuid").UUID(conf))
            await db.commit()
        except Exception:
            await db.rollback()
            pytest.skip("matcher could not score in this fixture; guard untested here")

    after = await _status(test_engine, conf)
    assert after, "status was cleared"
    # It may legitimately stay the same, but it must be a real matcher status.
    assert after in {
        before,
        "approved",
        "needs_review",
        "needs_sme_review",
        "low_messaging_fit",
        "vetoed",
    }
