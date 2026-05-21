# Scout

**Scout** is a locally-installed web app for the your team that finds
AI conferences, scores them against the team's messaging and four-pillar
strategy, and recommends which SME should attend. It runs entirely on your
machine; chat and embedding inference are served by your LLM endpoint over the
OpenAI-compatible API.

## Quickstart

Prerequisites: Docker Desktop, **or** Podman + podman-compose.

```bash
git clone https://github.com/<org>/scout
cd scout
cp .env.example .env   # add your your LLM endpoint key
make up
```

Open <http://localhost:8000>.

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

## Documentation

- [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) — system overview, data flow, glossary
- [`PLANS/phase-1/00-INDEX.md`](PLANS/phase-1/00-INDEX.md) — the full Phase 1 plan
- [`PLANS/STATUS.md`](PLANS/STATUS.md) — current build progress
- [`docs/ADR/`](docs/ADR/) — architecture decision records
- [`docs/ops/`](docs/ops/) — operational runbooks (added in step 30)

## Reporting a security issue

Please open an issue tagged `security` or email the your team lead directly.
Do not include sensitive payloads in public issues.

## License

[Apache 2.0](LICENSE)
