"""The CFP digest is a deadline alarm: today and tomorrow only.

Two behaviours locked here. First, the digest must see the deadlines the
rest of the app sees — it once read only the rich ``cfp_deadlines``
JSONB array (rarely filled) while everything else uses ``cfp_close_at``,
so it shipped empty forever. Second, the window is deliberately tight:
an empty digest means "nothing urgent", and the finder's deadline
filters cover planning ahead.
"""

from __future__ import annotations

import uuid
from datetime import date, timedelta

import pytest
from app.services.reports import build_cfp_digest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker


async def _insert_conf(engine, name: str, *, close_in_days: int | None, status: str = "approved") -> str:
    cid = str(uuid.uuid4())
    close = (
        date.today() + timedelta(days=close_in_days)
        if close_in_days is not None
        else None
    )
    async with engine.begin() as conn:
        await conn.execute(
            text(
                "INSERT INTO app.conferences "
                "(id, name, slug, status, event_kind, topics, cfp_topics_of_interest, "
                " cfp_deadlines, is_virtual, cfp_close_at) "
                "VALUES (:id, :name, :slug, :status, 'corporate', '{}', '{}', "
                " '[]', false, :close)"
            ),
            {"id": cid, "name": name, "slug": f"digest-{cid[:8]}", "status": status, "close": close},
        )
    return cid


@pytest.mark.asyncio
async def test_digest_falls_back_to_cfp_close_at(test_engine, clean_db) -> None:
    """A conference with only cfp_close_at (empty deadlines array) still
    lands in the digest bucket its deadline belongs to."""
    await _insert_conf(test_engine, "Digest Today Conf", close_in_days=0)
    await _insert_conf(test_engine, "Digest Tomorrow Conf", close_in_days=1)
    # Outside the today/tomorrow window — must NOT appear.
    await _insert_conf(test_engine, "Digest Far Conf", close_in_days=5)
    # Vetoed — ineligible even with a deadline.
    await _insert_conf(test_engine, "Digest Vetoed Conf", close_in_days=0, status="vetoed")

    Session = async_sessionmaker(test_engine, expire_on_commit=False)
    async with Session() as db:
        result = await build_cfp_digest(db)
        await db.commit()

    names = {
        e.name
        for bucket in result.buckets.values()
        for e in bucket
    }
    assert names == {"Digest Today Conf", "Digest Tomorrow Conf"}
    assert result.stats["today"] == 1
    assert result.stats["tomorrow"] == 1
    # Something surfaced, so a bell notification must exist.
    assert result.notification_id is not None


@pytest.mark.asyncio
async def test_digest_empty_when_nothing_closes(test_engine, clean_db) -> None:
    """No deadlines in the horizon: no notification row, no bell noise."""
    await _insert_conf(test_engine, "No Deadline Conf", close_in_days=None)

    Session = async_sessionmaker(test_engine, expire_on_commit=False)
    async with Session() as db:
        result = await build_cfp_digest(db)
        await db.commit()

    assert sum(result.stats.values()) == 0
    assert result.notification_id is None
