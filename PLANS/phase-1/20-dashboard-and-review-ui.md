# 20 — Dashboard & Conference Review UI

## Goal
The primary surface: ranked conferences, detail view, approve/reject actions.

## Prereqs
- 09 (manual data exists), 15 (conferences populating)
- 17, 18, 19 (matcher + SME + narratives populating)
- 16 (graph for neighborhood viz)

## Pages

### `/dashboard`
- Top: 4 stat cards
  - Upcoming approved conferences (next 90 days)
  - Pending review queue size
  - CFP closing within 30 days (also drives step 24's digest)
  - Low-coverage SME profiles count
- Filter bar: time window, status, pillar, audience, region, "has top SME above gate"
- Saved views dropdown (persisted in `localStorage`, LRU-capped at 20)
- Main: ranked conference list. Each row:
  name | dates | location | score badge (0-100 + bucket) | top pillar tag |
  recommended SME chip | status pill | actions

### `/conferences/[id]`
- Header: name, dates, location, website link, status pill
- Score panel: overall + breakdown bars (messaging / pillar / sme)
- Rationale text (step 17), with key phrases bolded against evidence
- Source panel: contributing `raw_pages` (links), `last_seen_at`, snippet excerpts
- **SME panel**: top 3 ranked, per-dimension bars, **narrative paragraph from step 19** in italics with "AI-generated" badge
- "Previous editions" panel (step 23): year-over-year history of this series, who from DAAM attended
- Topic + audience chips
- CFP block: open/close dates, "Apply" link if URL known, countdown
- Mini neighborhood graph (step 16) — depth-2 React Flow
- Decision panel: Approve / Reject / Needs Review + optional reason + optional `decided_by_label`
- Version history button → opens "git blame" panel (step 25)
- Print stylesheet

### `/conferences`
- Full filter + search list (no stat cards)
- Bulk actions: bulk approve/reject (typed-count confirmation for > 10)
- CSV export of current filter (formula-injection-safe)

### `/settings/sources`
- CRUD on scrape sources (step 14). "Crawl now" per source.

### `/settings/topics`
- Step 09's topic review queue (pending → approve/merge/reject).

### `/settings/review-queue`
- All `needs_review*` items in one place. Bulk-friendly.

### What is NOT here
- **No `/settings/algorithm` page.** Match thresholds and weights are
  env vars (step 07). Editing them is `.env` + `make up`. Saves us a
  settings table and a write surface. If we tune them often enough to
  miss a UI, we'll add one later.

## Tasks
- [ ] Build pages above with shadcn/ui primitives + TanStack Query + TanStack Router.
- [ ] Optimistic updates for approve/reject; rollback on server error.
- [ ] Toast on every write.
- [ ] Keyboard shortcuts on detail page: `a` approve, `r` reject, `n` next,
      `p` prev, `?` shortcut help.
- [ ] Pagination + server-side filtering throughout.
- [ ] Empty states for every collection.
- [ ] Accessibility: form labels, focus management, ARIA, contrast >= 4.5:1.

## Security notes
- All inputs validated client + server (server is source of truth).
- Free-form text fields (`decision.reason`, `decided_by_label`) HTML-escaped on render.
- CSV export quotes cell-leading `=/+/-/@` to defeat formula injection.

## Acceptance criteria
- [ ] Dashboard with 200+ conferences loads in < 1s p95.
- [ ] Approve action persists; row pill updates; `decisions`, `audit_log`,
      `content_versions` rows written.
- [ ] Saved views persist across reloads (localStorage).
- [ ] All buttons keyboard-accessible; alt text; tab order sane.
- [ ] Empty states for: no conferences, no SMEs, no audiences, no sources, no chat.

## Open questions for the user
- **Default sort** — recommend smart default: boost CFP-closing-soon when
  score >= "okay" bucket.
- **CSV export columns** — propose default; tunable later.

## Risks
- Dashboard perf with many filters + HNSW queries. Pre-compute filterable
  columns on `conferences` rather than embedding-search per request.
- Saved views can balloon; LRU cap of 20.
