# 26 — Observability & Diagnostics (Local)

## Goal
Debuggability without a Prometheus/Grafana stack a single-user local
install doesn't need. **MaaS handles LLM-side metrics on their end.** We
focus on two things:

1. **Structured stdout logs** — JSON, request_id-tagged, viewable via `make logs`.
2. **`/diagnostics` page** — surfaces the operational state the user cares
   about, derived from data we already store.

## Prereqs
- 06 (structured logging in place)
- 10 (`llm_calls` populated)
- 13 (`ingest_jobs` populated)

## What `/diagnostics` shows

Front-end page, pulling from `GET /api/v1/diagnostics` (single denormalized response, cached 30s):

- **LLM panel**
  - Calls this month: count, total tokens, total cost
  - Calls today
  - Last 24h by purpose: table (extract, rationale, fit_narrative, agent_chat, embedding, topic_normalize)
  - Budget bar vs `LLM_MONTHLY_BUDGET_USD` (80% warn color)
  - Last 10 errors (model, purpose, status, when)
- **Jobs panel** (from `ingest_jobs` + APScheduler introspection)
  - Currently running (with elapsed time)
  - Recent failures (24h) with one-line error preview + retry button
  - Next-fire times for each cron
  - Throughput sparkline by hour
- **Scraper panel**
  - Per-source: last crawled, pages fetched, robots status, enabled flag
  - "Disabled by error" list
  - "Needs JS rendering" page count (from step 14's static-only mode)
- **Data panel**
  - Conferences by status
  - SME profile coverage (count with empty topics / bio / audiences)
  - Pending topics queue size (step 15) with quick-link to review
  - Pending series suggestions queue size (step 23)
  - Embedding model active (name + dim)
  - Freshness distribution histogram (for decay tuning)
- **Digest panel**
  - Last `cfp_digest` generation time + counts per bucket (step 24)
- **System panel**
  - Postgres connection ok, version, DB size
  - Disk usage on `pdf_uploads` and `raw_pages` volumes
  - Container uptime (process start time)

## Tasks
- [ ] `GET /api/v1/diagnostics` aggregator (single request, cached 30s).
- [ ] Frontend page `/diagnostics`: shadcn cards; refresh button + opt-in 30s auto-refresh.
- [ ] `POST /api/v1/diagnostics/jobs/{id}/retry` — re-enqueues same task.
- [ ] "Re-enable" action for auto-disabled sources.
- [ ] Quick-link buttons to: `/settings/topics` (pending), `/settings/series` (suggestions).
- [ ] Structured WARN events tied to user-visible thresholds:
  - Budget threshold crossed
  - Repeated source failure
  - Embedding model unset
  - Excessive quarantined conferences (configurable threshold)

## Optional
- [ ] OTel exporter that ships traces to a user-supplied OTLP endpoint when
      `OTEL_EXPORTER_OTLP_ENDPOINT` is set. Off by default. Lets power users
      send to Honeycomb/Tempo without baking in a stack.

## Security notes
- `/diagnostics` exposes operational data; no secrets, no chunk text.
- Retry rate-limited (1 per 10s per job).
- Logs go to stdout; never written to volumes.

## Acceptance criteria
- [ ] `/diagnostics` loads in < 500ms.
- [ ] A failing job appears in the failures list within 30s.
- [ ] Retry button re-enqueues; job appears in running.
- [ ] Approaching 80% of monthly budget changes color + emits WARN.
- [ ] `make logs SERVICE=api` is JSON, parsable by `jq`.

## Open questions for the user
- **Auto-refresh default** — recommend on at 30s.
- **OTel exporter ship-but-off-by-default** — recommend yes.

## Risks
- Can show "green" while masking structural issues. We balance with failure
  log + freshness histogram for honest partial-degradation signals.
