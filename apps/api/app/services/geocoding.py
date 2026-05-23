"""City → (latitude, longitude) lookup for the dashboard map.

Uses OpenStreetMap's Nominatim (free, no API key). Policy is 1 req/sec
max with a real User-Agent and an email contact — both are sent so we
play nice. Results are persisted into `Conference.latitude` /
`Conference.longitude` so we only ever hit Nominatim once per unique
(city, country) tuple.

Bulk backfill is offered via :func:`backfill_missing` which walks the
conferences table at the rate limit until everything's resolved.
"""

from __future__ import annotations

import asyncio
import time

import httpx
import structlog
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.entities import Conference

log = structlog.get_logger("scout.geocoding")

NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
NOMINATIM_USER_AGENT = "Scout-CFP/0.1 (scout@example.invalid)"

# Nominatim's usage policy is "absolute maximum of 1 request per second".
# We sleep slightly more than that to stay clear of the cliff.
RATE_LIMIT_SECONDS = 1.05

# Last-request timestamp shared across all calls in the same process.
# Module-global because Nominatim doesn't care which Scout coroutine is
# making the request, just how fast they arrive.
_last_request_at: float = 0.0
_lock = asyncio.Lock()


async def geocode_city(
    city: str | None,
    country: str | None,
    *,
    client: httpx.AsyncClient | None = None,
) -> tuple[float, float] | None:
    """Return (lat, lng) for (city, country) or None if unresolvable.

    Rate-limits internally so callers can fan this out across many rows
    without coordinating themselves. Returns None on any failure —
    network, parse, no results, country missing — rather than raising,
    so callers can simply skip rows that don't resolve.
    """
    if not city or not city.strip():
        return None

    q = city.strip()
    if country:
        q = f"{q}, {country.strip()}"

    own_client = client is None
    if client is None:
        client = httpx.AsyncClient(timeout=15.0, follow_redirects=True)

    try:
        async with _lock:
            global _last_request_at
            elapsed = time.monotonic() - _last_request_at
            if elapsed < RATE_LIMIT_SECONDS:
                await asyncio.sleep(RATE_LIMIT_SECONDS - elapsed)
            _last_request_at = time.monotonic()

            try:
                resp = await client.get(
                    NOMINATIM_URL,
                    params={"q": q, "format": "json", "limit": "1"},
                    headers={"User-Agent": NOMINATIM_USER_AGENT},
                )
            except httpx.HTTPError as exc:
                log.warning("geocode.http_error", q=q, error=str(exc)[:200])
                return None

        if resp.status_code != 200:
            log.warning("geocode.bad_status", q=q, status=resp.status_code)
            return None

        try:
            results = resp.json()
        except ValueError:
            return None

        if not isinstance(results, list) or not results:
            log.info("geocode.no_match", q=q)
            return None

        first = results[0]
        try:
            lat = float(first["lat"])
            lng = float(first["lon"])
        except (KeyError, TypeError, ValueError):
            return None
        return (lat, lng)
    finally:
        if own_client:
            await client.aclose()


async def geocode_and_persist(
    db: AsyncSession,
    *,
    conference_id,
    city: str | None,
    country: str | None,
) -> tuple[float, float] | None:
    """Geocode and update the row in-place. Caller commits.

    Returns the (lat, lng) tuple or None if unresolvable. Idempotent —
    re-running on a row that already has coordinates simply overwrites
    with fresh values (useful if the city was corrected after first run).
    """
    coords = await geocode_city(city, country)
    if coords is None:
        return None
    lat, lng = coords
    await db.execute(
        update(Conference)
        .where(Conference.id == conference_id)
        .values(latitude=lat, longitude=lng)
    )
    return coords


async def backfill_missing(
    db: AsyncSession,
    *,
    batch_limit: int | None = None,
) -> dict[str, int]:
    """Walk conferences with NULL coordinates and resolve them.

    Returns a count summary: ``{"attempted": int, "resolved": int,
    "skipped": int}``. Honors Nominatim's rate limit, so this can take a
    while for large backfills — expect ~1 second per conference.

    ``batch_limit`` caps how many rows to attempt this call. ``None``
    means "everything that needs resolving."
    """
    stmt = select(Conference).where(
        Conference.latitude.is_(None),
        Conference.location_city.is_not(None),
        Conference.is_virtual.is_(False),
    )
    if batch_limit is not None:
        stmt = stmt.limit(batch_limit)

    rows = (await db.execute(stmt)).scalars().all()
    log.info("geocode.backfill.start", n_rows=len(rows))

    summary = {"attempted": 0, "resolved": 0, "skipped": 0}
    # Commit periodically so progress survives if the run is interrupted
    # and the dashboard map starts populating mid-run (instead of only at
    # the end of a 9-minute call). 20 rows ≈ 20 sec — cheap snapshot.
    COMMIT_EVERY = 20
    async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as client:
        for row in rows:
            if not row.location_city:
                summary["skipped"] += 1
                continue
            summary["attempted"] += 1
            coords = await geocode_city(
                row.location_city, row.location_country, client=client
            )
            if coords:
                row.latitude, row.longitude = coords
                summary["resolved"] += 1
            else:
                summary["skipped"] += 1
            if summary["attempted"] % COMMIT_EVERY == 0:
                await db.commit()
                log.info("geocode.backfill.progress", **summary)

    await db.commit()
    log.info("geocode.backfill.done", **summary)
    return summary
