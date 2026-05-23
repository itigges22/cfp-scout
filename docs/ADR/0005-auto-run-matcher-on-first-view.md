---
adr: "0005"
title: Auto-run the matcher on first conference detail view
status: accepted
date: 2026-05-23
supersedes: ""
superseded_by: ""
---

# 0005 — Auto-run the matcher on first conference detail view

## Context

The matcher (Stage A messaging cosine, Stage B pillar alignment, Stage C SME
composite) runs by default when a conference is ingested — both the LLM
extraction pipeline and the manual create wizard fire `run_fit_match()` on
write. That covers the common case.

The gap is conferences that arrive in bulk: the `developers.events` feed
ingest and the on-demand discovery pipeline (plan 35) mass-create rows and
defer matching to an APScheduler cron job. A user can easily race the cron
by opening a detail page or brief for a freshly-ingested conference before
the scheduled match has run.

Before this change, the detail page rendered a not-useful message:

> "No match row yet. Run the matcher from `/admin/matcher/run-now/<id>`"

That URL is an admin JSON endpoint, not a UI route — there was no clickable
way for the user to recover. Operationally hostile.

Two facts make a different design possible:

- The matcher is fast: typically ~2 s, ~30 s worst-case.
- `app.matches` is keyed by `(conference_id, algorithm_version)`, so we can
  cheaply check "is there a match row for the current version?" before
  doing any work.

## Decision

When `GET /api/v1/conferences/{id}/match` or `GET /api/v1/conferences/{id}/brief`
is hit and no Match row exists for the current `algorithm_version`, the
endpoint runs `run_fit_match()` inline, commits, then re-reads. The user
sees a 5–30 s page load on first view; the UI shows a skeleton state.
Subsequent views hit the persisted Match row and the brief's 5-minute cache,
so they are fast.

The auto-run is gated on `match is None` — re-opening a page that already
has a Match row is a no-op for the matcher.

## Consequences

**Positive**
- The "Match score" panel and the brief's "Why we're going" section never
  need a separate "run matcher" trigger from the UI.
- No new state machine, no polling, no admin endpoint exposed to non-admins.
- Idempotent and self-healing: any conference reachable through the UI
  acquires a match row the first time someone looks at it.
- Algorithm version bumps automatically re-trigger a match on next view, by
  virtue of the `(conference_id, algorithm_version)` gating.

**Negative**
- First view of a freshly-ingested conference is slow (5–30 s vs ~200 ms).
  Acceptable because subsequent views are fast and the user is already
  context-switching when they click into a detail page.
- The request handler holds a DB transaction and a LLM API embedding call for
  the duration. Under heavy concurrent first-view traffic this could starve
  the api workers; we accept this at single-user scale.
- Auto-match failures (no messaging documents, no SMEs, LLM API outage) need
  a graceful path. Caught and logged at `conference.match.auto_run_failed`;
  endpoint falls back to returning `match: null` with a UI message:
  "Matcher couldn't produce a score — usually means there are no active
  messaging documents or SMEs to compare against."

**Neutral**
- The scheduled matcher cron still exists and still backfills in the
  background. Auto-run-on-view is a latency optimization on top, not a
  replacement.

## Alternatives considered

- **UI calls `POST /api/v1/admin/matcher/run-now/{id}` when match is null,
  polls for completion** — Lost because: doubles the round-trips, exposes
  an admin endpoint to non-admin code paths, and requires a polling state
  machine in the SPA for what is fundamentally a synchronous read.
- **Always synchronously match on ingest** — Lost because: would slow bulk
  feed ingest from ~5,773 rows/min to ~50 rows/min, blocking the user on
  the "Discover more" action. The cron + on-view auto-run combo keeps bulk
  ingest fast and still gives every viewed conference a fresh score.
- **Background-queue the match on first detail view, return immediately,
  poll** — Lost because: more state (job rows, poll endpoint, UI polling
  hook) for marginal UX gain. The matcher itself is fast enough that
  inline blocking is fine.

## Implementation

- `apps/api/app/api/v1/conferences.py` — the GET match endpoint checks for
  a Match row, calls `run_fit_match()` inline if absent, commits, re-reads.
  Logged at `log.info("conference.match.auto_run")`.
- `apps/api/app/services/brief/builder.py` — the brief builder does the
  same check before assembling the "Why we're going" section. Logged at
  `log.info("brief.auto_match")`.
- Both import `from app.services.matcher import run_fit_match`.
- Errors caught around the inline call; logged at
  `conference.match.auto_run_failed` with the conference id and exception
  class; the endpoint returns `match: null` rather than 500.

## References

- [ADR-0001](0001-route-1-local-install-2-containers.md) — single-process,
  single-user constraints that make inline blocking acceptable.
- `apps/api/app/services/matcher/` — the matcher pipeline itself
- [`docs/web-discovery.md`](../web-discovery.md) — the bulk-ingest path
  that motivated this change
