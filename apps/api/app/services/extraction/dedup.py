"""Conference dedup (plan 15, pass 1: slug + year only).

A conference name without a year is ambiguous — "AAAI" 2026 vs 2027 are
distinct conferences. We slugify on ``name + "-" + year`` so the unique
constraint on ``conferences.slug`` catches the legitimate "same conference,
same year, two sources" case while letting "same name, different years"
coexist.

Pass 2 will add ``pg_trgm`` fuzzy matching for spelling variations
(``NeurIPS`` vs ``NIPS``, ``CVPR 2026`` vs ``Computer Vision and Pattern
Recognition 2026``) — but slug-on-name+year is correct for the well-formed
case and avoids false-positive merges across years.
"""

from __future__ import annotations

from datetime import date

import structlog
from slugify import slugify
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.entities import Conference

log = structlog.get_logger("scout.extraction.dedup")


def build_slug(name: str, year: int | None) -> str:
    """``conferences.slug`` value for ``(name, year)``.

    ``year`` may be ``None`` for conferences without confirmed dates — those
    use a ``-unknown`` suffix so we don't accidentally merge two undated
    conferences with the same name.
    """
    base = slugify(name, max_length=160, lowercase=True)
    suffix = str(year) if year else "unknown"
    return f"{base}-{suffix}"


def year_for(start_date: date | None) -> int | None:
    return start_date.year if start_date else None


async def find_duplicate(db: AsyncSession, *, slug: str) -> Conference | None:
    """Return an existing conference row with this slug, or None."""
    result = await db.execute(select(Conference).where(Conference.slug == slug))
    return result.scalar_one_or_none()
