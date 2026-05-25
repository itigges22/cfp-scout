---
adr: "0001"
title: Route 1 (Hybrid API via hosted LLM), local install, 2-container architecture
status: accepted
date: 2026-05-21
supersedes: ""
superseded_by: ""
---

# 0001 — Route 1 (Hybrid API via hosted LLM), local install, 2-container architecture

## Context

The original Phase 1 plan (local-only design document; not in the repo)
outlined three possible routes:

- **Route 1** — Hybrid API cloud via a hosted LLM (FastAPI + Postgres + frontend +
  hosted models)
- **Route 2** — Locally hosted (Flask + llama.cpp + a single mid-sized open model)
- **Route 3** — Fully cloud hosted on a Kubernetes platform (multi-replica + a managed inference stack)

We need to pick one for Phase 1 and define how it deploys. The team's
priorities, stated in conversation, are: **compute efficient and easy to
maintain**. Each teammate will run their own copy locally and connect to
a hosted LLM API for inference.

## Decision

Use **Route 1** but locally installed:

- **Stack**: FastAPI + Postgres 16 (with pgvector) + Vite-built React SPA +
  an OpenAI-compatible hosted LLM API for chat and embeddings.
- **Topology**: **two containers** — `postgres` and `api`. The api serves
  both the JSON endpoints and the built SPA (via FastAPI `StaticFiles`).
  No separate web container, no Redis, no separate worker, no Prometheus stack.
- **Distribution**: end users `git clone`, copy `.env.example` to `.env`,
  add their LLM API key, and run `docker compose up` (or `podman compose up`).
  Updates are `git pull && make up`.
- **No authentication**: single-user, single-machine installs.

## Consequences

**Positive**
- Smallest possible operational surface; everyone can run a copy.
- The hosted LLM provider handles model hosting and observability; we never touch GPUs.
- Provider-agnostic LLM client (`openai` SDK + custom base_url) means we can
  swap the LLM endpoint for any other OpenAI-compatible endpoint without code changes.
- No multi-tenant complexity (auth, RBAC, audit-by-actor, etc.).
- 2-container stack means a single image to build, one DB to back up.

**Negative**
- Background jobs share the api process; heavy jobs can degrade request
  latency (mitigated with `uvicorn --workers 2`).
- Single-user means double-booking and cross-team coordination still live
  in Slack/Confluence; Scout is decision support, not workflow.
- A frontend change requires rebuilding the api image. Dev mode uses the
  Vite dev server on host to mitigate; prod is a one-shot rebuild.
- Local install means anyone with shell access to the user's machine has
  app access. README is explicit about this.

**Neutral**
- We may grow into Route 3 (fully cloud hosted) in Phase 2 if usage justifies it.
  The current architecture migrates cleanly because the api is one image
  and Postgres is portable; we'd add an ingress and a real auth layer.

## Alternatives considered

- **Route 2 (locally hosted models)** — Lost because: maintaining
  llama.cpp + a single 9B model means GPU/CPU tuning and model lifecycle
  ownership for every install. A hosted LLM API removes all of that.
- **Route 3 (fully cloud hosted)** — Lost for Phase 1 because:
  it requires real auth, multi-user state, and platform team coordination.
  Phase 2 candidate.
- **3-container topology (api + web + postgres)** — Considered. Lost because:
  Vite-built SPA served by FastAPI eliminates a whole container, a CORS
  story, and a deploy step, while giving up only SSR — which we don't need.
- **Redis + Arq + separate worker** — Considered (and was in an earlier
  draft). Lost because: for one user, APScheduler in-process with a
  Postgres jobstore gives us cron + persistence without the operational
  overhead of Redis or a second container.
- **Apache AGE for graph queries** — Considered. Lost because: the graph
  is small enough to compute in memory with NetworkX from junction tables.
  Same Postgres, fewer extensions to manage.
- **Next.js for the frontend** — Considered. Lost because: no SSR need,
  and shipping a Node runtime alongside our Python runtime doubles the
  image and the dependency surface.

## References

- [`docs/ARCHITECTURE.md`](../ARCHITECTURE.md) — current system overview
- Original Phase 1 plan + per-plan design docs lived under `PLANS/` but
  were scrubbed from the repo on 2026-05-23 (local-only artifacts).
