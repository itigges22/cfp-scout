# 21 — Graph Exploration View (Obsidian-Style)

## Goal
A dashboard-level interactive graph for exploring the relationships between
conferences, topics, audiences, SMEs, pillars, and messaging documents.
Phase 1's full Obsidian-style "see the whole network" experience.

The conference detail page already has a small depth-2 neighborhood (step 16/20).
This is the bigger picture.

## Prereqs
- 16 (graph loader, viz endpoint)
- 08 (frontend with React Flow installed)

## Tasks

### Backend
- [ ] `GET /api/v1/graph/full` already exists from step 16. Reuse it here with:
  - `?include=conferences,topics,smes,audiences,pillars,messaging,series` (CSV of node types)
  - `?since=YYYY-MM-DD` (conferences after this start_date only)
  - `?status=approved,discovered,needs_review` (filter by conference status)
  - Returns `nodes[]`, `links[]`, `truncated boolean`
- [ ] Cap at 500 nodes per response. If filters produce more, `truncated=true`
      and we return the most-connected 500.
- [ ] Server-side computes basic node metrics for layout hints:
  - `degree` (used for node size)
  - `cluster_hint` (Louvain community id from networkx) for color grouping

### Frontend
- [ ] `/graph` route. Layout:
  - Left panel (collapsible): filters
    - Node type toggles
    - Date window
    - Conference status checkboxes
    - Pillar selector (single)
    - SME team filter (DAAM/Non-DAAM/All)
    - "Center on conference/SME/topic" search box (autocomplete)
  - Main canvas: React Flow
    - Force-directed layout (use `dagre` or `elk` plugin; recommend `d3-force-3d` via
      `reactflow-force-layout` for natural Obsidian-like motion)
    - Nodes color-coded by type and shape-coded by status
    - Edge thickness by weight
    - Hover: highlight neighborhood; dim rest
    - Click: open side drawer with entity summary + "Open detail page" link
    - Right panel (toggle): legend + selected node details
- [ ] Performance budget: smooth pan/zoom up to 500 nodes. Above 500 → show
      banner "truncated; narrow filters."
- [ ] Saved graph views: same `localStorage` pattern as dashboard saved views.
- [ ] "Export PNG" button (uses `react-flow`'s `toImage`).
- [ ] Empty state when no data ingested yet.

## Security notes
- Endpoint already validated in step 16. No new attack surface here.
- React Flow renders SVG; no untrusted HTML execution.
- "Export PNG" runs client-side; no upload of rendered image.

## Acceptance criteria
- [ ] `/graph` loads with a force-directed layout of all current data.
- [ ] Toggling node-type filters updates the canvas without a full page reload.
- [ ] Clicking a node opens a drawer with summary + link to its detail page.
- [ ] With > 500 nodes after filters, response is truncated and UI surfaces it.
- [ ] Pan/zoom remains smooth (>= 30fps) at 500 nodes on a typical laptop.

## Open questions for the user
- **Layout algorithm** — d3-force (Obsidian-like motion) vs ELK (structured)?
  Recommend d3-force for the explorer feel; offer ELK as a toggle later.
- **Default node-type filters on first load** — recommend `conferences + topics + smes`
  active by default; pillars/audiences/messaging off (less visual noise).
- **Cluster coloring** — Louvain hints help users see thematic groupings; confirm interest.

## Risks
- Performance can degrade past 500 nodes. Cap is enforced server-side.
- Force-directed layouts are non-deterministic; each render looks slightly
  different. Acceptable for an exploration view; deterministic layouts are
  uglier without manual tuning.
