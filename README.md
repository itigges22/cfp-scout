# Scout

**Scout** is a locally-installed web app for the your team that finds
AI conferences, scores them against the team's messaging and four-pillar
strategy, and recommends which SME should attend. It runs entirely on your
machine; chat and embedding inference are served by your LLM endpoint over the
OpenAI-compatible API.

## Quickstart

Prerequisites: Docker Desktop, **or** Podman + podman-compose.

```bash
git clone https://github.com/<your-org>/scout
cd cfp-scout
cp .env.example .env   # add your your LLM endpoint key
make up                # builds images + brings up the stack
make migrate           # runs Alembic + loads the 35-series seed catalog
```

Open <http://localhost:8000>.

Defaults you'll want to change before connecting to LLM API:

- `LLM_DRY_RUN=true` — set to `false` once you've added a real `LLM_API_KEY`.
  In dry-run mode the LLM client returns deterministic canned responses so
  the whole pipeline works offline.
- `LLM_MONTHLY_BUDGET_USD=50` — caps the monthly spend. Warns at 80% in
  `/diagnostics`; refuses calls at 100%.

## Daily dev loop

```bash
make dev               # one-time: builds SPA + brings up dev stack with bind mounts
# edit Python in apps/api/app/ → uvicorn auto-reloads in ~1s
# edit React in apps/web/src/ → run `make spa` → container picks it up

make test-unit         # 55 unit tests, ~2s
make logs SERVICE=api  # follow the structured JSON logs
```

`make spa` runs the SPA build inside a throwaway UBI node-22 container and
drops the output in `apps/api/static/` (~5s with cached deps). Hard-reload
the browser to drop the old bundle hash.

`make rebuild` is the cache-aware image rebuild for dep changes; `make
rebuild-nocache` is the nuclear option.

## What's inside

Two containers:

- **postgres** — Postgres 16 with `pgvector` for embeddings + `pg_trgm` for fuzzy dedup.
- **api** — FastAPI (serves both the JSON API and the built React SPA), with
  APScheduler running in-process for background jobs (scraping, embedding,
  matching, decay, CFP digests).

The frontend is a Vite-built React SPA. It's bundled into the api image at
build time, so production deploy is a single image talking to a single
database.

**Discovery.** Scout pulls events from the `developers.events` JSON feed
(~5,773 entries) and filters them with a multilingual AI keyword list
editable from `/settings/tunables`. Trigger a refresh with **Discover more**
on `/conferences`, or wait for the scheduled job.

## Layout

```
apps/
  api/         FastAPI service (includes the in-process scheduler)
  web/         Vite + React SPA (built into the api image)
  scraper/     Scraping helpers (Python package; not a separate service)
packages/
  shared-types/  OpenAPI-generated TS types
infra/
  compose/       compose.yaml + podman override
  containerfiles/
  postgres/      init SQL
db/seeds/        seed data
docs/            ARCHITECTURE.md, ADRs, ops runbooks
evals/           LLM evaluation fixtures
```

## Routes you'll use

The api serves both the JSON API at `/api/v1/...` and the React SPA at `/`.
Useful pages:

| Path | What's there |
|---|---|
| `/dashboard` | 3 stat cards (Upcoming approved, Pending review, CFP closing), top-5 ranked conferences, and a world map with one red dot per city hosting an AI event (click to open that city's conferences) |
| `/conferences` | Ranked list with status + sort filters; **Discover more** triggers a new pull from the events feed |
| `/conferences/$id` | Score panel, SME panel (per-dimension + narrative), sources, decision actions. Auto-runs the matcher inline on first open (5–30s; shows a skeleton) |
| `/conferences/$id/brief` | Print-optimized brief. Also auto-runs the matcher inline on first open |
| `/agent` | Read-only RAG chat (cites every claim) |
| `/graph` | Force-directed knowledge graph |
| `/diagnostics` | LLM spend, jobs, scraper health, freshness histogram, system info |
| `/smes`, `/audiences`, `/messaging`, `/messaging/new`, `/messaging/$id`, `/past-conferences`, `/topics` | Manual data entry |
| `/settings`, `/settings/tunables` | App config; runtime-editable knobs (AI keywords, thresholds, etc.) |

The map uses Nominatim for geocoding. To backfill coordinates for existing
events, hit `POST /api/v1/admin/discovery/geocode-backfill` (rate-limited).

## Documentation

- [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) — system overview, data flow, glossary
- [`docs/web-discovery.md`](docs/web-discovery.md) — how the events-feed pull, AI-keyword filter, and geocoding fit together
- [`docs/ops/runbook.md`](docs/ops/runbook.md) — common ops troubleshooting (start here when something breaks)
- [`docs/ops/`](docs/ops/) — per-topic runbooks (backups, secrets, migrations, database, data guardrails)
- [`docs/security/SECURITY_REVIEW.md`](docs/security/SECURITY_REVIEW.md) — threat model + per-control status
- [`docs/ADR/`](docs/ADR/) — architecture decision records

## Reporting a security issue

Please open an issue tagged `security` or email the your team lead directly.
Do not include sensitive payloads in public issues.

## License

[Apache 2.0](LICENSE)
