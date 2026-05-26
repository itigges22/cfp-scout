# Scout — Operational Runbook

Common ops procedures. **Start here when something breaks.** Each section
is a self-contained recipe: symptom → diagnosis → fix → verify.

Cross-references:
- `docs/ops/backups.md` — dump + restore SOP
- `docs/ops/secrets.md` — `.env` management + LLM key rotation
- `docs/ops/migrations.md` — Alembic daily workflow
- `docs/ops/database.md` — schemas + roles
- `docs/ops/data-guardrails.md` — what gets rejected on input + why
- `docs/security/SECURITY_REVIEW.md` — per-control status matrix

---

## Stack lifecycle

### `make up` succeeded but the dashboard is empty

This is the expected state on a fresh install — Scout has no data yet.

1. Create at least one source: `POST /api/v1/sources` (or via the UI once
   `/settings/sources` lands in plan 20 pass 2). Default `kind=page` is safest.
2. Trigger it: `POST /api/v1/sources/<id>/crawl-now`. Watch
   `app.ingest_jobs` for the scrape + per-page parse rows.
3. Once a conference appears, run the matcher:
   `POST /api/v1/admin/matcher/run-now/<conference_id>`. The status
   pill should move from `discovered`/`needs_review` to `approved` if
   it passes all three gates.

### api container won't start

Check the logs: `make logs SERVICE=api`. The most common boot failures:

- **`POSTGRES_PASSWORD is the placeholder 'changeme'`** — edit `.env`,
  set a real value, `make down && make up`.
- **`db.unreachable`** — Postgres isn't ready yet. Healthcheck retries
  for 30s; if it's still failing after that, check `make logs SERVICE=postgres`.
- **`LLM_API_KEY is still set to the placeholder 'changeme'`** —
  provision an LLM API key OR set `LLM_DRY_RUN=true` for offline work.
- **uvicorn import error** — usually means a Python dep change wasn't
  picked up. `make rebuild` (cache-aware, ~30-60s) reinstalls deps via uv.

### Postgres volume is full

Symptoms: writes fail, `make migrate` hangs, `pg_size_pretty(...)` in
`/diagnostics` System panel approaches the disk cap.

1. **Back up first**: `make db-dump` (writes to `./backups/`).
2. **Vacuum**: `make db-psql` → `VACUUM (FULL, ANALYZE);`. Reclaims space
   from deleted rows + index bloat.
3. **Audit large tables**:
   ```sql
   SELECT schemaname, relname, n_live_tup, pg_size_pretty(pg_total_relation_size(relid))
   FROM pg_stat_user_tables
   ORDER BY pg_total_relation_size(relid) DESC LIMIT 10;
   ```
   Likely suspects: `vectors.document_chunks`, `app.raw_pages`,
   `audit.content_versions`.
4. **Decay-archive**: confirm `DECAY_ENABLED=true` so old conferences
   get archived; otherwise trigger manually:
   `POST /api/v1/admin/jobs/run_decay_pass/trigger`.
5. **Last resort**: `make nuke && make up && make migrate` (DESTROYS all
   data — only after a verified backup).

### Container "no space left on device" during rebuild

Podman VM disk fills up over many image builds.

```bash
podman system prune -af   # reclaims orphaned image layers (often 100+ GB)
make rebuild               # retry
```

### PDF upload OOM-kills the api container

Symptoms: a PDF upload hangs, the api container restarts with no clear
error, or `/uploads/pdf` returns 500. Common on slide decks > 10 MB or
docs > 50 pages because Docling's layout + table-structure pipeline holds
~2 GB resident plus working memory per page.

Three-layer defense already in code (`apps/api/app/services/pdf/parser.py`):

1. **Size-aware tier selection** — `< 4 MB` runs the full pipeline; `4–10 MB`
   drops OCR; `> 10 MB` runs Docling text-only.
2. **Cascading fallback** — if the chosen tier raises, it walks DOWN
   (medium → large → text_only).
3. **Text-only via pypdfium2** — final fallback uses no model weights at
   all (~100 MB RSS). One chunk per page, no layout, but guarantees a
   non-empty result.

If you're STILL seeing OOM kills on macOS Podman, the bottleneck is
typically the **podman-machine VM size** — it has its own memory cap
independent of the container's cgroup limit:

```bash
podman machine list             # shows current VM memory
podman machine stop
podman machine set --memory 8192 --cpus 4   # 8 GiB
podman machine start
make up
```

The compose file sets the container cgroup limit to 6 GB (see
`infra/compose/compose.yaml`), so any VM ≥ 8 GiB gives Docling room to
work; smaller VMs will silently cap at the VM size.

---

## Jobs

### A job is stuck "running" for hours

Symptoms: `/diagnostics` Jobs panel shows a row with `elapsed_seconds`
in the thousands.

1. Inspect: `make db-psql` →
   ```sql
   SELECT id, kind, started_at, stats FROM app.ingest_jobs
   WHERE status='running' ORDER BY started_at;
   ```
2. APScheduler's `max_instances=1` means a hung job blocks future fires of
   the same task. Mark it failed:
   ```sql
   UPDATE app.ingest_jobs SET status='failed', error_text='manually marked hung'
   WHERE id='<uuid>';
   ```
3. Restart the api container (clears in-process scheduler state):
   `make api-restart`. The scheduler reconciles from the Postgres jobstore
   on next boot.

### Retry a failed job

UI: `/diagnostics` → Jobs panel → "Retry" next to the failed row.

API: `POST /api/v1/diagnostics/jobs/<ingest_job_id>/retry`. Rate-limited
to 1/10s per job-id. Recognizes: scrape_source, parse_raw_page,
run_fit_match, sme_fit_narrative, build_cfp_digest, run_decay_pass,
heartbeat. Other kinds return 409.

### Cron job hasn't fired

Check: `GET /api/v1/admin/jobs` returns the registered jobs with
`next_run_time`. If the scheduler isn't running, the response is
`{running: false}`.

Common causes:
- The leader-election lock is held by another (now-dead) worker — restart
  the api container.
- `WATCHFILES_FORCE_POLLING` env var or uvicorn `--reload` is repeatedly
  killing + restarting the scheduler. Only a concern in `make dev`; not
  prod.

---

## LLM

### Calls suddenly all failing

Symptoms: `/diagnostics` LLM panel "Recent errors" populated, every
matcher run logs `llm_call_failed`.

1. Check the error string. Common causes:
   - **401 / invalid key** — `.env` has a stale `LLM_API_KEY`. Rotate
     per `docs/ops/secrets.md`.
   - **429 / rate limited** — LLM provider quota exceeded. The client backs off
     automatically (tenacity, jittered exponential, 4 attempts) but
     bursty extraction passes can outrun it. Reduce concurrency by
     setting `LLM_DRY_RUN=true` temporarily.
   - **Budget cap hit** — `/diagnostics` shows `threshold_warn=true` and
     `pct_used` ≥ 1.0. Bump `LLM_MONTHLY_BUDGET_USD` or wait for the
     calendar month rollover.
   - **Network unreachable** — your machine can't reach the configured
     `LLM_BASE_URL`. VPN issue, DNS, etc.
2. Verify a single call: `POST /api/v1/admin/llm/test-chat` with body
   `{"prompt":"ping","purpose":"smoke"}`.

### Rotate the LLM API key

See `docs/ops/secrets.md`. Short version:

```bash
# 1. Provision a new key from your LLM provider's dashboard
# 2. Edit .env: replace LLM_API_KEY
# 3. Restart so the new value is picked up
make api-restart
# 4. Verify
curl -X POST localhost:8000/api/v1/admin/llm/test-chat \
  -d '{"prompt":"ping","purpose":"smoke"}' -H 'Content-Type: application/json'
# 5. After confirming the new key works, revoke the old one with the provider.
```

---

## Scraper

### A source keeps failing

`/diagnostics` Scraper panel shows it in `disabled_sources` or with stale
`last_crawled_at`.

1. Inspect recent failed scrapes:
   ```sql
   SELECT started_at, stats, error_text FROM app.ingest_jobs
   WHERE kind='scrape_source' AND status='failed'
   ORDER BY started_at DESC LIMIT 5;
   ```
2. Common errors:
   - **`SSRFProtectionError`** — the URL or a redirect target resolves
     to a private IP. The source URL is bad or the operator inserted a
     hostile redirect; don't bypass — investigate the source.
   - **`HTTP 403/404`** — site changed, robots blocked us, or returned
     a tarpit. If robots: respect it. Otherwise disable the source.
   - **Page body too large** (5MB cap) — `body_too_large`. Probably a
     PDF or video served as HTML; mark the source disabled.
3. Re-enable a disabled source: `PATCH /api/v1/sources/<id>` with
   `{"enabled": true}`.

### "Needs JS render" count growing

The static scraper marks pages that returned < 500 chars of visible
text. They're persisted but never extracted. Plan 14's design is
intentional — we don't ship Playwright. Two options:

- Disable the source (UI: `DELETE /api/v1/sources/<id>`).
- Manually upload the conference info via the SME form or the XLSX
  workbook (plan 31).

---

## Data hygiene

### Approve a pending topic

LLM-discovered topics land in `app.topics` with `pending_review=true`,
`is_active=false`. They don't influence matching until approved.

UI: `/topics` (filter: "Pending"). Approve buttons send
`POST /api/v1/topics/<id>/approve`. Reject sends `/reject` which leaves
`pending_review=true, is_active=false` (so it doesn't come back).

### Approve a series suggestion

The detector is opt-in: `GET /api/v1/conference-series/suggestions`
returns ranked (conference, suggested series, confidence) rows. Apply
each with `POST /api/v1/conference-series/<series_id>/assign` body
`{"conference_id": "..."}`. Triggers a matcher recompute for that
conference (past-attendance bonus may shift).

### Restore from backup

See `docs/ops/backups.md`. Short version:

```bash
make db-restore FILE=backups/scout-YYYY-MM-DD-HHMMSS.sql.gz
# Type 'restore' at the prompt.
```

This OVERWRITES the current DB. Take a fresh dump first if there's
anything worth saving.

### Re-run a failed cfp_digest

`POST /api/v1/admin/jobs/build_cfp_digest/trigger`. Idempotent within a
day — marks any prior un-seen digest as seen + writes a fresh one. UI
bell badge updates on the next poll (≤60s).

### Reset the embedding model

Only relevant when promoting a new model (e.g. when your LLM provider publishes a
successor to your current embedding model). Process:

1. Insert the new row in `vectors.embedding_models` (manual SQL today;
   plan 31 will surface this as a workbook sheet).
2. Toggle `is_active`: only one row is active at a time. The current
   active row continues to be used by old chunks; new chunks use the
   new active row.
3. Bulk re-embed everything by triggering re-extraction
   (`POST /admin/extraction/parse-now/<raw_page_id>` per page) or by a
   future `make reindex-embeddings` target (plan 25 pass 2).

---

## Decay

### Reading the freshness histogram

`/diagnostics` Data panel → "Conference freshness". 10 buckets; the
right-most is the freshest. Counts on the y-axis are the number of
conferences in each freshness band.

Healthy: bell-shape centered roughly mid-range, with the right tail
populated by recent additions.

Decay-too-aggressive: heavy left skew, lots of conferences at near-zero
freshness. Increase `CHUNK_HALF_LIFE_DAYS` / `CONFERENCE_HALF_LIFE_DAYS`
in `apps/api/app/services/lifecycle/decay.py` (env-tunable in a future
pass). Restart the api + trigger
`POST /admin/jobs/run_decay_pass/trigger`.

### Disable decay entirely

Set `DECAY_ENABLED=false` in `.env` and `make api-restart`. The matcher
falls back to pure cosine ranking; the daily cron short-circuits.

---

## Misc

### Where do logs go?

`stdout` of the api container, formatted as structured JSON (or
`LOG_FORMAT=console` in dev). View with `make logs SERVICE=api`. Pipe
through `jq` for filtering: `make logs SERVICE=api | jq -r 'select(.level=="error")'`.

Logs aren't written to disk in the container — by design (any sensitive
content stays in the structlog redactor's scrub pattern, not persisted).

### View OpenAPI spec

`http://localhost:8000/api/docs` for the Swagger UI, `/api/redoc` for
ReDoc, `/api/openapi.json` for the raw JSON.

### What's the algorithm version?

`GET /api/v1/admin/matcher/matches/recent` returns `algorithm_version`
on every row. When you bump it in
`apps/api/app/services/matcher/pipeline.py`, run
`POST /api/v1/admin/matcher/recompute-all` to re-score every conference
under the new version.

### How do I re-enrich conferences / pillars?

Three independent enrichment jobs, all idempotent:

| Job | Script | When to run |
|-----|--------|-------------|
| Conference text | `podman exec scout-api /app/.venv/bin/python /app/scripts/enrich_and_reembed.py` | After bulk-importing conferences that bypassed `enrich_and_match_task`; pass `--force` to redo everyone. |
| Pillar text | `podman exec scout-api /app/.venv/bin/python /app/scripts/enrich_pillars.py` | After editing strategic-pillar names/descriptions or adding/removing messaging documents; pass `--force` to redo. |
| LLM judge (Stage D) | `podman exec scout-api /app/.venv/bin/python /app/scripts/bulk_judge.py` | After enriching conferences or pillars; refreshes `matches.judge_score` and `matches.overall_score` for every row. |

The per-ingest auto-process hook (`enrich_and_match_task`) runs all
three steps inline for one new conference, so manual runs are only
needed for backfill or after corpus-wide changes.

### How do I disable the LLM judge to save cost?

Two settings on `app.app_setting_overrides`:

```sql
INSERT INTO app.app_setting_overrides (name, value, actor_label) VALUES
  ('enable_llm_judge', 'false', 'ops')
ON CONFLICT (name) DO UPDATE SET value=EXCLUDED.value;
```

Restart the api container; the next matcher run will skip Stage D
and `overall_score` will re-normalize across A/B/C only. Existing
`judge_score` values stay in the DB but are no longer used in
ranking. Re-enable by setting `enable_llm_judge=true`.

To rebalance without disabling, lower `match_w_judge` (default
`0.30`) via the same table or the `/settings/tunables` admin UI.

### Operator-facing tunables on the matcher

All settings live in `app.app_setting_overrides`; flip via the
`/settings/tunables` admin UI or direct SQL upsert. Restart the api
container after changing.

| Setting | Default | Purpose |
|---------|--------:|---------|
| `enable_llm_judge` | `true` | Master switch for Stage D. Off → matcher uses A/B/C only. |
| `match_w_judge` | `0.30` | Weight of Stage D in `overall_score`. |
| `enable_judge_few_shot` | `true` | Prepend recent decisions as in-context examples in the judge prompt. |
| `enable_judge_cache` | `true` | Skip the Stage D LLM call when inputs haven't changed since the last run. |
| `enable_cfp_urgency_boost` | `true` | +0.10 to overall if CFP closes in next 30 days. |
| `enable_recency_penalty` | `true` | -0.05 to overall if start date is >12 months out. |
| `enable_series_memory_boost` | `true` | +0.10 to overall if any past edition of the conference series was approved. |
| `primary_team_label` | `""` | Tag SMEs whose team doesn't match this as `is_external` for UI. Empty → all internal. |

### Why is pillar score 100% for everyone?

That was a pre-v2 bug — the v1 matcher took `max` across pillars
which always saturated. Symptom: every conference in
`app.matches` had `pillar_score = 1.0`. Fix: ensure your code
includes ADR-0008's distinctiveness-weighted aggregation
(`app/services/matcher/pillars.py`, softmax with `PEAK_T = 50.0`).
If you see saturation on a freshly-rolled-out v2 matcher, verify
the pillar `enriched_description` column is populated — without
the long-form text, the embedder collapses pillar cosines into a
narrow band where every conference looks identical.
