# 16 — Knowledge Graph (NetworkX over Postgres)

## Goal
Capture relationships between conferences, topics, audiences, SMEs, pillars,
and messaging documents. Facts live in Postgres junction tables; graph is
built in-memory with NetworkX. The Obsidian model: facts in storage, graph
derived in RAM.

## Prereqs
- 04 (entities + junction tables)
- 11 (embeddings)

## Tasks

### Service layer
- [ ] `app/services/graph/`:
  - `loader.py` — `load_graph(filter=None) -> nx.Graph`. Reads all junctions
    in one shot via async SQLAlchemy; assembles typed graph. **In-process
    cache, 60s TTL**, invalidated by explicit `graph.invalidate()` after writes.
  - `query.py` — typed helpers for the queries we actually need.
  - `viz.py` — produces JSON node-link payload for the frontend.

### Node & edge types
Nodes: `Conference`, `Topic`, `Audience`, `SME`, `Pillar`, `MessagingDoc`, `Source`, `ConferenceSeries` (step 23).

Edges:
- `Conference -[:ABOUT]- Topic`
- `Conference -[:TARGETS]- Audience`
- `Conference -[:ALIGNS_WITH]- Pillar` (weight=pillar_score)
- `Conference -[:SUITS]- SME` (weight=match_score)
- `Conference -[:DERIVED_FROM]- Source`
- `Conference -[:EDITION_OF]- ConferenceSeries` (step 23)
- `SME -[:EXPERT_IN]- Topic`
- `SME -[:SPEAKS_TO]- Audience`
- `MessagingDoc -[:SUPPORTS]- Pillar`

### Queries we build
- [ ] `candidate_smes_for_conference(conference_id, k=5)` — topic + audience
      overlap as graph neighbors; merged with bio similarity in step 18.
- [ ] `upcoming_conferences_for_sme(sme_id, days=180)` — neighbor traversal
      filtered by `start_date`.
- [ ] `pillar_coverage()` — count messaging docs + conferences per pillar.
      Surfaces gaps.
- [ ] `neighborhood(node_id, depth=2)` — for the conference detail viz (step 20).
- [ ] `full_graph_for_view(filters={...})` — for the dashboard exploration view (step 21).

### Visualization endpoint
- [ ] `GET /api/v1/graph/neighborhood?node_id=...&depth=2` → node-link JSON.
- [ ] `GET /api/v1/graph/full?type=...&since=...` → bounded full-graph payload
      (cap at 500 nodes; if more, the response includes `truncated=true`).

### Cache + invalidation
- [ ] Loader caches in memory for 60s. Service-level invalidation triggered
      after any junction write.

## Security notes
- Graph computed from validated data already in Postgres; inherits its safety.
- Viz endpoint returns labels and edge types only — no chunk text, no PII.
- All loader queries parameterized.
- In-memory guard rail: refuses to load graphs exceeding configured node/edge cap
  (well above Phase 1 scale).

## Acceptance criteria
- [ ] After 10 ingested conferences, `candidate_smes_for_conference` returns
      results in < 50ms (excluding LLM calls).
- [ ] Writing a new `sme_topics` row invalidates the cache; next load sees it.
- [ ] `/api/v1/graph/neighborhood` returns valid node-link JSON for any
      existing entity.
- [ ] Conference detail (step 20) renders a small graph viz.

## Open questions for the user
- **Cache TTL** — 60s default. Bump to 5min if stale tolerance is high?
- **Node cap for full graph** — 500 default. Adjustable.

## Risks
- Two writes racing on cache invalidation. Acceptable single-user; document
  the invariant.
- If Phase 2 scales relationships massively, NetworkX in-memory becomes
  bottleneck. Junction-table contract doesn't change; we'd swap implementation.
