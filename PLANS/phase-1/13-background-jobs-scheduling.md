# 13 — Background Jobs & Scheduling (APScheduler, in-process)

## Goal
Run slow work (scraping, embedding, OCR, fit matching, decay, CFP digest)
without blocking API requests. **No Redis, no separate worker container.**
APScheduler runs inside the API process via FastAPI's lifespan; jobs are
persisted in Postgres so they survive restarts.

## Prereqs
- 03 (Postgres reachable; `jobs` schema)
- 06 (API lifespan)

## Why APScheduler-in-process
- Single user = single host = no distributed queue needed
- Postgres jobstore = persistence across `make down/up`
- One fewer container to maintain
- Cron + ad-hoc jobs unified in one library
- AsyncIOExecutor pairs cleanly with FastAPI's event loop

## Tasks
- [ ] Add `apscheduler[sqlalchemy]` to api deps.
- [ ] `apps/api/app/scheduler.py`:
  - Module-level `AsyncIOScheduler` singleton
  - `SQLAlchemyJobStore` against `jobs` schema
  - `AsyncIOExecutor`
  - Defaults: `coalesce=True`, `max_instances=1` per job-id, `misfire_grace_time=300`
- [ ] Wire into FastAPI lifespan:
  ```python
  @asynccontextmanager
  async def lifespan(app: FastAPI):
      scheduler.start()
      register_cron_jobs(scheduler)
      yield
      scheduler.shutdown(wait=True)
  ```
- [ ] Task registry (`apps/api/app/tasks/`):
  - `embed_owner.py`
  - `parse_pdf.py`
  - `ocr_pdf.py`
  - `scrape_source.py`
  - `parse_raw_page.py`
  - `run_fit_match.py`
  - `recompute_all_matches.py`
  - `run_decay_pass.py`
  - `reindex_embeddings.py`
  - `compute_sme_fit_narrative.py` (step 19)
  - `build_cfp_digest.py` (step 24)
  - `link_conference_series.py` (step 23 — fuzzy match candidates)
- [ ] Enqueue helpers used by API services:
  ```python
  scheduler.add_job(embed_owner, kwargs={...})
  ```
- [ ] **Idempotency**: every task accepts a stable identifier.
- [ ] Cron jobs (registered at startup):
  - Every 15 min: `poll_sources_due_for_crawl()`
  - Daily 03:00 (TZ-configurable): `run_decay_pass`
  - Daily 04:00: `recompute_upcoming_matches`
  - Daily 09:00: `build_cfp_digest` (step 24)
  - Weekly Mon 02:00: `link_conference_series` (step 23)
- [ ] `ingest_jobs` row per task execution: created at start, terminal status on finish.
- [ ] Admin endpoint: `POST /api/v1/admin/jobs/{name}/trigger` (rate-limited 1/30s).
- [ ] `/diagnostics` page (step 26) shows running jobs, recent failures,
      queue depth, next-fire times.

## Security notes
- Tasks share the api process; no `eval`, no dynamic imports.
- Trigger endpoint logs loudly and rate-limits.
- Errored task tracebacks stored in `ingest_jobs.error_text` after passing
  through the structlog redaction filter.

## Acceptance criteria
- [ ] `make up` → scheduler starts; cron jobs visible via `GET /api/v1/admin/jobs`.
- [ ] `embed_owner` enqueued → chunks appear within seconds.
- [ ] Restart picks up unfinished jobs from the Postgres jobstore.
- [ ] Two simultaneous `embed_owner` calls for the same owner are serialized.
- [ ] `ingest_jobs` has one row per task run.

## Open questions for the user
- **Concurrency** — default `AsyncIOExecutor(max_workers=8)`. Bump if needed.
- **Cron timezone** — UTC default; `SCHEDULER_TIMEZONE` env override.

## Risks
- Tasks sharing the api process means heavy jobs can degrade API latency.
  Mitigation: `--workers 2` on uvicorn so one worker handles requests while
  the other absorbs scheduler load. Acceptable for single-user.
- APScheduler's SQLAlchemy jobstore expects `jobs` schema to exist. Alembic
  migration in step 06 creates it explicitly.
