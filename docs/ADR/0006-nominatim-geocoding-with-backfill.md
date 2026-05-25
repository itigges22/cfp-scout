---
adr: "0006"
title: Nominatim geocoding with rate-limited admin backfill, no PostGIS
status: accepted
date: 2026-05-23
supersedes: ""
superseded_by: ""
---

# 0006 — Nominatim geocoding with rate-limited admin backfill, no PostGIS

## Context

Plan 35 (on-demand discovery) surfaced ~500 conferences from the
`developers.events` feed. The first dashboard map clustered events by
country, but the user wanted city-level resolution with click-through:
"show me PyCon at Atlanta's location, clickable." The feed carries `city`
and `country` strings but no coordinates, so geocoding is mandatory before
the map can render anything more granular than country.

Three orthogonal questions:

1. **Which geocoder?** Paid commercial APIs vs free open data.
2. **How are coordinates stored?** Plain floats vs PostGIS geometry types.
3. **When does geocoding happen?** Inline on ingest vs explicit backfill.

The constraints: locally-installed app, single-user LLM API budget already
lean, no spatial-query needs beyond rendering markers, and ingest paths
that need to stay fast (the user clicks "Discover more" and waits on the
result).

## Decision

- **Geocoder**: OpenStreetMap **Nominatim** — free, no API key, 1 req/sec
  policy.
- **Storage**: plain `Float` columns `latitude` and `longitude` on
  `app.conferences`. No PostGIS.
- **Trigger**: explicit admin backfill, NOT inline on ingest. Endpoint
  `POST /api/v1/admin/discovery/geocode-backfill`. Idempotent — only
  touches rows with NULL `latitude`. Commits every 20 rows so progress
  survives interruption.

Nominatim policy is enforced in code, not hoped for: process-wide asyncio
lock + 1.05 s sleep between requests, plus a polite `User-Agent` header
that identifies the app and a contact email.

## Consequences

**Positive**
- **Zero recurring cost.** Nominatim is free and we are not at a scale
  that would strain its public instance (a few hundred to a few thousand
  rows per backfill run, with rate limiting).
- **No PostGIS in the container image.** Saves ~300 MB and one more
  Postgres extension to manage. Plain floats are sufficient at the
  city-level resolution we render.
- **Ingest stays fast.** The bulk feed (~500 rows) ingests in seconds;
  geocoding inline would push it to ~9 min at 1.05 s × 500 rows. The user
  doesn't wait on geocoding to see new conferences in `/conferences`.
- **Backfill is operator-controlled and resumable.** Crash mid-run? Re-run
  it; only NULL-`latitude` rows are touched. Commits every 20 rows means
  at most 20 rows of wasted work per interruption.
- **Provider-swap is one function.** `geocode_city()` is a single
  abstraction; replacing Nominatim with Mapbox or Google means changing a
  URL and adding an auth header.

**Negative**
- **The dashboard map shows N+1 truth** — only geocoded conferences appear
  as markers. The operator must remember to run the backfill periodically;
  the UI button to trigger it is a follow-up (currently curl-only).
  Non-geocoded events still appear in `/conferences`, so nothing is lost,
  just absent from the map.
- **Nominatim's data quality varies.** Cities outside North America and
  Europe are mostly fine; very small municipalities can resolve to the
  containing region. Acceptable for clustering on a world map.
- **Ambiguous city names disambiguate by Nominatim's heuristics**, not by
  our own logic. "San Jose, CA" vs "San Jose, Costa Rica" is handled by
  passing both `city` and `country` in the query; we trust Nominatim's
  result.

**Neutral**
- If we later need real spatial queries ("find events within X km of me"),
  adding PostGIS is a migration: enable extension, alter columns to
  `geography(POINT)`. Not free, but not a rewrite either.

## Alternatives considered

- **Paid geocoder (Google Maps, Mapbox)** — Lost because: introduces a
  billable third-party for a non-core feature; the user's LLM API budget is
  already lean; Nominatim's rate limit is not painful for our backfill
  cadence.
- **Static city centroid lookup table embedded in the SPA** — Lost
  because: 225 unique cities today and growing without bound; embedding
  ~50K centroids is megabytes of SPA bundle; no disambiguation for
  collisions like "San Jose, CA" vs "San Jose, Costa Rica".
- **PostGIS** — Lost because: ~300 MB container cost and an extra
  extension to manage, for zero current spatial-query need. We only render
  markers; we never query "within X km."
- **Geocode inline during ingest** — Lost because: would slow feed ingest
  from seconds to minutes (1.05 s × 500 rows = ~9 min); also Nominatim's
  usage policy explicitly discourages high-burst inline use.

## Implementation

- `apps/api/app/services/geocoding.py` — Nominatim wrapper, async,
  rate-limited. `User-Agent: Scout-CFP/0.1 (scout@example.invalid)` per policy.
  Process-wide asyncio lock + 1.05 s sleep between requests, documented in
  the module docstring.
- `apps/api/alembic/versions/20260523_0100_conferences_latlng.py` — adds
  `latitude` and `longitude` Float columns to `app.conferences`.
- `apps/api/app/api/v1/conferences.py` — `GET /api/v1/conferences/stats/by-location`
  returns aggregates over non-virtual, non-quarantined, non-rejected rows
  with non-null lat/lng.
- `apps/web/src/components/dashboard/WorldMap.tsx` — clusters by
  `(city, country)`; click a dot opens the list of conferences at that
  location; click a name opens the detail page.

## References

- [Nominatim usage policy](https://operations.osmfoundation.org/policies/nominatim/)
- [ADR-0001](0001-route-1-local-install-2-containers.md) — image-size and
  dep-surface constraints that ruled out PostGIS.
- [`docs/web-discovery.md`](../web-discovery.md) — the bulk feed ingest
  that motivated city-level geocoding.
