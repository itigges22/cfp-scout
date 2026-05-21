# 02 — Containerization Foundation (Docker + Podman)

## Goal
The minimum 2-container stack that runs Scout locally on either Docker
Compose or Podman Compose. No host-installed Python or Node required.

## Prereqs
- 01 (repo, Makefile, tooling)

## The stack

```
[ api (FastAPI + APScheduler + built SPA, :8000) ] -> [ postgres (:5432) ]
                                                    \-> Red Hat MaaS (external)
```

That's it. Two containers. The api serves both `/api/v1/...` JSON endpoints
and the built static SPA at `/`. No Redis, no separate web service, no
worker, no graph DB, no observability stack.

## Tasks
- [ ] Use **`Containerfile`** as the filename. Optionally symlink
      `Dockerfile` → `Containerfile` per service.
- [ ] Base image: `registry.access.redhat.com/ubi9/python-312` (UBI, Red Hat-aligned).
- [ ] `apps/api/Containerfile` is **multi-stage**:
  - **Stage 1 (spa-builder)**: `registry.access.redhat.com/ubi9/nodejs-22`.
    `pnpm install --frozen-lockfile`, `pnpm build`. Output: `apps/web/dist/`.
  - **Stage 2 (py-builder)**: UBI python-312. `uv sync --frozen`.
  - **Stage 3 (runtime)**: UBI python-312 minimal. Copies venv from py-builder,
    copies `dist/` from spa-builder to `/app/static/`, copies api source.
    Runs as **non-root user**.
- [ ] FastAPI mounts the SPA via `app.mount("/", StaticFiles(directory="static", html=True))`
      (configured in step 06).
- [ ] `infra/compose/compose.yaml`:
  ```yaml
  services:
    postgres:     # step 03
    api:          # step 06 (FastAPI + APScheduler + built SPA)
  ```
- [ ] `infra/compose/compose.override.podman.yaml` for Podman-only:
      `:z` volume labels for SELinux, network mode tweaks.
      `podman compose -f compose.yaml -f compose.override.podman.yaml up`.
      Makefile auto-detects and uses the right invocation.
- [ ] `infra/compose/compose.override.dev.yaml`:
  - Exposes Postgres 5432 to host for DB tools
  - Live-reload for the api: mounts source, runs `uvicorn --reload`
  - **For SPA dev**: run Vite dev server on the host (`pnpm dev` in `apps/web`)
    against the api container. Doc this in `docs/ARCHITECTURE.md`. The production
    container build still bundles the SPA into the api image.
- [ ] **Named volumes** for state: `postgres_data`, `pdf_uploads`,
      `scraper_raw_pages`. No host bind mounts for state.
- [ ] Every service declares:
  - `healthcheck:` block
  - `restart: unless-stopped`
  - `depends_on:` with `condition: service_healthy`
  - `deploy.resources.limits` (cpu + memory)
- [ ] Single user-defined bridge network.
- [ ] `.env.example` at repo root drives compose.
- [ ] No `:latest` tags. Explicit versions only.
- [ ] Image tagging: `scout/api:<git-sha>` in CI; `scout/api:dev` locally.

## Security notes
- Containers run as non-root.
- Read-only root filesystem where possible; tmpfs for `/tmp`.
- Drop all Linux capabilities; add back only what's needed.
- Postgres port not exposed to host in default `compose.yaml`.
- The api binds to `127.0.0.1:8000` by default (configurable). User reaches it via localhost.
- SPA assets served by FastAPI use proper `Content-Type` headers; no path traversal
  (StaticFiles handles this correctly by default).

## Acceptance criteria
- [ ] `make up` works on Docker Desktop (macOS) and Podman (Linux + Podman Desktop).
- [ ] Both services healthy within 30s of `make up`.
- [ ] `http://localhost:8000` loads the SPA.
- [ ] `http://localhost:8000/api/v1/healthz` returns 200 JSON.
- [ ] `make nuke && make up` is fully reproducible.
- [ ] `docker exec scout-api id` returns non-zero UID.
- [ ] Rootless Podman works without elevated privileges.

## Open questions for the user
- **UBI vs slim** — UBI is policy-aligned for Red Hat; slim is smaller. Recommend UBI.
- **Dev workflow for SPA** — Vite dev server on host vs in-container live reload?
  Recommend host Vite + container api; faster iteration. Confirm.

## Risks
- A frontend change requires rebuilding the api image. Accepted: `make up` rebuilds
  cleanly; the `dev` override has live reload to mitigate during active work.
- Podman compose feature drift. Commit to compose spec features only; Docker-specific
  extensions go in the Docker override file.
