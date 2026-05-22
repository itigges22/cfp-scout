# Scout

**Scout** is a locally-installed web app for the Red Hat DAAM team that finds
AI conferences, scores them against the team's messaging and four-pillar
strategy, and recommends which SME should attend. It runs entirely on your
machine; chat and embedding inference are served by Red Hat MaaS over the
OpenAI-compatible API.

## Quickstart

Prerequisites: Docker Desktop, **or** Podman + podman-compose.

```bash
git clone https://github.com/itigges22/cfp-scout
cd cfp-scout
cp .env.example .env   # add your Red Hat MaaS key
make up                # builds images + brings up the stack
make migrate           # runs Alembic + loads the 35-series seed catalog
```

Open <http://localhost:8000>.

Defaults you'll want to change before connecting to MaaS:

- `LLM_DRY_RUN=true` — set to `false` once you've added a real `LLM_API_KEY`.
  In dry-run mode the LLM client returns deterministic canned responses so
  the whole pipeline works offline.
- `LLM_MONTHLY_BUDGET_USD=50` — caps the monthly spend. Warns at 80% in
  `/diagnostics`; refuses calls at 100%.

## Daily dev loop

```bash
make dev               # one-time: builds SPA + brings up dev stack with bind mounts
# edit Python in apps/api/app/ → uvicorn auto-reloads in ~1s
# edit React in apps/web/src/ → run `make spa` (~12s) → container picks it up

make test-unit         # 55 unit tests, ~2s
make logs SERVICE=api  # follow the structured JSON logs
```

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
PLANS/           Phase 1 implementation plans (see PLANS/phase-1/00-INDEX.md)
```

## Routes you'll use

The api serves both the JSON API at `/api/v1/...` and the React SPA at `/`.
Useful pages:

| Path | What's there |
|---|---|
| `/dashboard` | 4 stat cards + top-5 ranked conferences |
| `/conferences` | Ranked list with status + sort filters |
| `/conferences/<id>` | Score panel, SME panel (per-dimension + narrative), sources, decision actions |
| `/agent` | Read-only RAG chat (cites every claim) |
| `/graph` | Force-directed knowledge graph |
| `/diagnostics` | LLM spend, jobs, scraper health, freshness histogram, system info |
| `/smes`, `/audiences`, `/messaging`, `/past-conferences`, `/topics` | Manual data entry |

## Documentation

- [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) — system overview, data flow, glossary
- [`docs/ops/runbook.md`](docs/ops/runbook.md) — common ops troubleshooting (start here when something breaks)
- [`docs/ops/`](docs/ops/) — per-topic runbooks (backups, secrets, migrations, database, data guardrails)
- [`docs/security/SECURITY_REVIEW.md`](docs/security/SECURITY_REVIEW.md) — threat model + per-control status
- [`docs/ADR/`](docs/ADR/) — architecture decision records
- [`PLANS/phase-1/00-INDEX.md`](PLANS/phase-1/00-INDEX.md) — the full Phase 1 plan
- [`PLANS/STATUS.md`](PLANS/STATUS.md) — current build progress (every plan's status with changelog)

## Reporting a security issue

Please open an issue tagged `security` or email the DAAM team lead directly.
Do not include sensitive payloads in public issues.

## License

[Apache 2.0](LICENSE)
