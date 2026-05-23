# apps/api — Scout FastAPI service

FastAPI app on Python 3.12 + async SQLAlchemy + asyncpg + Alembic. It hosts
both the JSON API (`/api/v1/...`) and the built React SPA (served from
`static/` at `/`), and runs APScheduler in-process for background jobs
(scraping, embedding, matching, decay, CFP digests).

## Layout

```
app/
  api/v1/          HTTP routers (one file per resource: conferences, smes,
                   agent, briefs, graph, diagnostics, admin_* ...)
  services/       Business logic — matcher/, brief/, embeddings/,
                   geocoding.py, web_discovery/, agent/, extraction/, ...
  db/models/      SQLAlchemy ORM (entities, junctions, matching, vectors,
                   audit, ops)
  tasks/          APScheduler job entrypoints (scrape, embed, match, decay,
                   digest, discovery)
  main.py         App factory + router registration + SPA mount
  settings.py     Pydantic Settings (env-driven)
  scheduler.py    APScheduler setup (Postgres jobstore)
alembic/versions/  DB migrations
```

## Run locally

From the repo root:

```bash
make dev               # builds SPA, starts api + postgres with bind mounts
```

uvicorn auto-reloads on edits under `app/`. For the SPA, run `make spa` to
rebuild and drop the bundle into `static/`.

## Configuration

Static config lives in `app/settings.py` (Pydantic Settings; read from
`.env`). A runtime-editable subset (AI keywords, thresholds, budget caps,
etc.) is exposed via `GET/PUT /api/v1/admin/settings` and edited from the
`/settings/tunables` page in the SPA.

## Adding an endpoint

1. Create a router file under `app/api/v1/` (one resource per file).
2. Register it in `app/main.py` with `app.include_router(...)`.
3. Define request/response Pydantic models inline at the top of the router,
   or in `app/schemas/` if shared.
4. Put non-trivial logic in `app/services/`; keep the router thin.
