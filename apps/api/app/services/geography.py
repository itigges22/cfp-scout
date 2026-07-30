"""Places: turning a location string into coordinates, and comparing them.

WHAT THIS DOES
    Geocodes a conference's free-text location into coordinates and a
    country, and answers "how close is this SME to this conference?" —
    same city, same country, same continent, or nowhere near.

HOW IT CONNECTS
    Called by   api/v1/admin_discovery.py, services/agent.py,
                services/matcher/ (the location dimension)
    Reads       the geocoding provider; results are cached

WORTH KNOWING
    Two modules with no shared reference between them, but one subject.
    A reader asking "how does location work here" had to know that the
    lookup and the comparison lived apart.

    Location is one of five SME dimensions and it is DROPPED, not scored
    zero, when a conference has no usable location — see the matcher.
"""

from __future__ import annotations

import asyncio
import time
from typing import Final

import httpx
import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Conference
from app.settings import get_settings

log = structlog.get_logger("scout.geography")


# ==========================================================================
# geography.py
# ==========================================================================


REGIONS: Final[dict[str, frozenset[str]]] = {
    "europe": frozenset({
        "AL", "AT", "BE", "BG", "BY", "CH", "CZ", "DE", "DK", "EE", "ES",
        "FI", "FR", "GB", "GR", "HR", "HU", "IE", "IS", "IT", "LT", "LU",
        "LV", "MK", "NL", "NO", "PL", "PT", "RO", "RS", "RU", "SE", "SI",
        "SK", "TR", "UA",
    }),
    "north_america": frozenset({"CA", "MX", "US"}),
    "south_america": frozenset({
        "AR", "BO", "BR", "CL", "CO", "EC", "PE", "PY", "UY", "VE",
    }),
    "asia": frozenset({
        "BD", "CN", "HK", "ID", "IN", "JP", "KR", "KZ", "LK", "MY", "NP",
        "PH", "PK", "SG", "TH", "TW", "VN",
    }),
    "middle_east": frozenset({
        "AE", "IL", "IR", "JO", "KW", "LB", "QA", "SA", "TR",
    }),
    "africa": frozenset({
        "CI", "CM", "EG", "ET", "GH", "KE", "MA", "NG", "TN", "ZA",
    }),
    "oceania": frozenset({"AU", "NZ"}),
}


_REGION_TO_CONTINENT: Final[dict[str, str]] = {
    "europe": "EU",
    "north_america": "NA",
    "south_america": "SA",
    "asia": "AS",
    "middle_east": "AS",
    "africa": "AF",
    "oceania": "OC",
}


REGION_ALIASES: Final[dict[str, frozenset[str]]] = {
    "europe": REGIONS["europe"],
    "european": REGIONS["europe"],
    "eu": REGIONS["europe"],
    "emea": REGIONS["europe"] | REGIONS["middle_east"] | REGIONS["africa"],
    "north america": REGIONS["north_america"],
    "na": REGIONS["north_america"],
    "south america": REGIONS["south_america"],
    "latam": REGIONS["south_america"] | frozenset({"MX", "PR", "DO", "CR", "GT"}),
    "latin america": REGIONS["south_america"] | frozenset({"MX", "PR", "DO", "CR", "GT"}),
    "asia": REGIONS["asia"],
    "apac": REGIONS["asia"] | REGIONS["oceania"],
    "asia pacific": REGIONS["asia"] | REGIONS["oceania"],
    "middle east": REGIONS["middle_east"],
    "africa": REGIONS["africa"],
    "oceania": REGIONS["oceania"],
    # Single countries. The agent's location detector reads THIS dict, and
    # until these existed "conferences in the US" matched nothing — the
    # region keys above only knew continents, so the location filter
    # silently never fired and a Canadian event sat in a "US" answer.
    "us": frozenset({"US"}),
    "usa": frozenset({"US"}),
    "u.s.": frozenset({"US"}),
    "united states": frozenset({"US"}),
    "america": frozenset({"US"}),
    "uk": frozenset({"GB"}),
    "u.k.": frozenset({"GB"}),
    "united kingdom": frozenset({"GB"}),
    "britain": frozenset({"GB"}),
    "england": frozenset({"GB"}),
    "canada": frozenset({"CA"}),
    "germany": frozenset({"DE"}),
    "france": frozenset({"FR"}),
    "spain": frozenset({"ES"}),
    "italy": frozenset({"IT"}),
    "netherlands": frozenset({"NL"}),
    "belgium": frozenset({"BE"}),
    "sweden": frozenset({"SE"}),
    "norway": frozenset({"NO"}),
    "denmark": frozenset({"DK"}),
    "finland": frozenset({"FI"}),
    "poland": frozenset({"PL"}),
    "czechia": frozenset({"CZ"}),
    "czech republic": frozenset({"CZ"}),
    "austria": frozenset({"AT"}),
    "switzerland": frozenset({"CH"}),
    "ireland": frozenset({"IE"}),
    "portugal": frozenset({"PT"}),
    "greece": frozenset({"GR"}),
    "india": frozenset({"IN"}),
    "japan": frozenset({"JP"}),
    "china": frozenset({"CN"}),
    "south korea": frozenset({"KR"}),
    "korea": frozenset({"KR"}),
    "singapore": frozenset({"SG"}),
    "australia": frozenset({"AU"}),
    "new zealand": frozenset({"NZ"}),
    "brazil": frozenset({"BR"}),
    "mexico": frozenset({"MX"}),
    "argentina": frozenset({"AR"}),
    "israel": frozenset({"IL"}),
    "uae": frozenset({"AE"}),
    "dubai": frozenset({"AE"}),
    "turkey": frozenset({"TR"}),
    "south africa": frozenset({"ZA"}),
}


_PRIMARY_REGION: Final[dict[str, str]] = {
    # Straddles Europe and the Middle East. Europe for distance purposes:
    # Istanbul is a short hop from most of the continent.
    "TR": "europe",
}


_COUNTRY_TO_REGION: Final[dict[str, str]] = {
    **{code: region for region, codes in REGIONS.items() for code in codes},
    **_PRIMARY_REGION,
}


def region_for(country_code: str | None) -> str | None:
    """Region key for an ISO-3166 alpha-2 code, or None if unlisted."""
    if not country_code:
        return None
    return _COUNTRY_TO_REGION.get(country_code.upper())


def continent_for(country_code: str | None) -> str | None:
    """Coarse continent code (EU/NA/SA/AS/AF/OC), or None if unlisted.

    What the matcher's travel-distance scoring asks.
    """
    region = region_for(country_code)
    return _REGION_TO_CONTINENT.get(region) if region else None


def countries_in(name: str) -> frozenset[str]:
    """Country codes for a spoken region name, empty if unrecognised."""
    return REGION_ALIASES.get(name.strip().lower(), frozenset())


# ==========================================================================
# geocoding.py
# ==========================================================================


NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"


#: OSM's usage policy REQUIRES a User-Agent that identifies the operator and
#: gives a way to contact them. This was hardcoded to
#: "Scout-CFP/0.1 (scout@example.invalid)" — a fake address — and Nominatim
#: answered every request with 403 Access denied. Nothing surfaced it: the
#: backfill counted those as "skipped", so the world map simply stayed empty
#: and the summary looked like there was nothing to geocode.
#:
#: Reuses the existing scraper_user_agent rather than adding a second one:
#: it is the same question (who is making this request, and who do I email
#: about it) and one honest answer is better than two that can disagree.


RATE_LIMIT_SECONDS = 1.05


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
                    headers={"User-Agent": get_settings().scraper_user_agent},
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
