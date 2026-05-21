# 06 — Backend FastAPI Skeleton

## Goal
A running FastAPI service inside its container, talking to Postgres via
async SQLAlchemy + Alembic, serving the built SPA at `/`, with structured
logging and a published OpenAPI schema the frontend type generator consumes.

## Prereqs
- 01, 02 (repo + compose)
- 03 (Postgres)
- 04 (schema design)
- 05 (Pydantic schemas — guardrails)

## Stack inside `/apps/api`
- FastAPI
- SQLAlchemy 2.x (async) + asyncpg
- Alembic
- Pydantic v2 + `pydantic-settings`
- structlog (JSON logs to stdout)
- httpx (LLM client in step 10)
- uvicorn
- APScheduler (wired in step 13's lifespan)

## Tasks
- [ ] `pyproject.toml` with deps locked via `uv lock`. Dev deps separated.
- [ ] App layout:
  ```
  apps/api/
    app/
      main.py                 # FastAPI app, lifespan, middleware, routers, StaticFiles mount
      settings.py             # pydantic-settings
      logging.py              # structlog config
      db/
        session.py
        base.py
        models/
      api/v1/                 # routers per resource
      services/
      schemas/                # Pydantic DTOs (incl. guardrails from step 05)
      prompts/                # jinja templates
    alembic/
      env.py
      versions/
    static/                   # SPA build output (populated by step 08 build)
    tests/
    Containerfile             # multi-stage (spa-builder + py-builder + runtime)
  ```
- [ ] Async Alembic configured. Initial migration encodes step 04 schema.
- [ ] Endpoints:
  - `GET /api/v1/healthz` — liveness
  - `GET /api/v1/readyz` — readiness (DB + embedding model row present)
- [ ] Static SPA serving: `app.mount("/", StaticFiles(directory="static", html=True))`.
      Fall-through to `index.html` for SPA routes (`html=True` handles this).
- [ ] Middleware:
  - request_id (creates or honors `X-Request-ID`)
  - structured logs include `request_id`, `path`, `method`, `status`, `duration_ms`
  - Global exception handler → RFC 7807 `application/problem+json`
- [ ] CORS: locked to the same-origin in production (since SPA + API share
      origin via StaticFiles mount). Dev override allows `http://localhost:5173`
      for the Vite dev server.
- [ ] OpenAPI: served at `/api/openapi.json` (custom path; not the default `/openapi.json`)
      to avoid collision with SPA routes.
- [ ] `Containerfile`:
  - Stage 1: nodejs-22 builds `apps/web` → `dist/`
  - Stage 2: python-312 runs `uv sync --frozen`
  - Stage 3: python-312 minimal runtime; non-root; copies venv + source + `dist` → `static/`
  - `CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "2"]`
- [ ] Compose `api` service:
  - `depends_on: { postgres: { condition: service_healthy } }`
  - env: `DATABASE_URL`, `LLM_*`, `LOG_LEVEL`, `STORAGE_PATH`, `SCHEDULER_TIMEZONE`
  - dev override mounts `apps/api/app` for reload
- [ ] Makefile targets:
  - `make migrate`, `make migrate-create MSG="..."`, `make seed`
  - `make sh-api`, `make test-api`
  - `make build-spa` (rebuilds `apps/web` and copies to `apps/api/static`)

## Security notes
- Default-deny on routes — every router uses an `APIRouter(prefix=...)`
  and is explicitly included.
- All inputs validated by Pydantic (`extra='forbid'`).
- Lint rule forbids `text("...")` SQL without `.bindparams()`.
- Error responses never leak stack traces in non-dev `ENV`.
- StaticFiles mounted with `html=True` but Python's path-traversal protection
  in StaticFiles is sound; no manual path joining.
- The api binds to `0.0.0.0` inside the container; the compose port mapping
  binds it to `127.0.0.1:8000` on the host (configurable).

## Acceptance criteria
- [ ] `make up` → `curl http://localhost:8000/api/v1/healthz` returns 200.
- [ ] `http://localhost:8000/` returns the SPA `index.html`.
- [ ] `http://localhost:8000/api/openapi.json` is valid OpenAPI 3.1.
- [ ] `/api/v1/readyz` returns 503 when Postgres down, 200 when up.
- [ ] `make migrate` runs `alembic upgrade head`.
- [ ] `make logs SERVICE=api` shows JSON, one line per record, with `request_id`.
- [ ] `pytest` passes via `make test-api`.

## Open questions for the user
- **Worker count** — `--workers 2` for one local user. Bump in `.env` if needed.
- **API versioning** — `/api/v1/...` from day one. Confirm.

## Risks
- Async SQLAlchemy + Alembic has setup ceremony. Worth it because LLM client,
  scraper, and APScheduler are all async-friendly downstream.
- SPA + API sharing origin means CORS is irrelevant in prod; great for security,
  removes a class of misconfigurations.
