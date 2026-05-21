# 25 — Data Lifecycle: Ebbinghaus Decay + Content Versioning

## Goal
Two data-hygiene features:

1. **Ebbinghaus decay** — old, untouched data half-lifes; influences ranking
   without hiding content.
2. **Git-blame-style versioning** — every edit to a versioned entity records
   a diff with `actor_label`; user-viewable history with restore.

## Prereqs
- 04 (`content_versions`, `freshness_score`, `last_used_at` columns)
- 13 (decay runs as daily APScheduler job)
- 20 (history viewer UI lives in detail panels)

## Decay

### Formulas
- Chunks: `freshness = exp(-(now - max(created_at, last_used_at)) / HALF_LIFE)`,
  `HALF_LIFE_CHUNK = 60d`.
- Conferences: `HALF_LIFE_CONFERENCE = 365d`, floor `0.5` for future events.
- Effective rank: `cosine * (alpha + (1-alpha)*freshness)`, `alpha = 0.85`.
- Toggleable via `DECAY_ENABLED` env (default true).

### Tasks
- [ ] Service helpers bump `last_used_at` on retrieval; write-behind buffered every 30s.
- [ ] Daily cron `run_decay_pass`:
  - Bulk-update `freshness_score` on chunks + conferences
  - Archive conferences with `end_date < now - 90d` (`status='archived'`)
- [ ] Retrieval API multiplies cosine × freshness; gated by `DECAY_ENABLED`.

## Content versioning ("git blame")

### Tasks
- [ ] SQLAlchemy `before_update` event listener for versioned entities:
  - `messaging_documents`, `audience_profiles`, `smes`, `conferences`,
    `conference_series` (step 23), `decisions`, `topics`
  - Inserts `content_versions` row with `diff jsonb` (jsonpatch),
    `actor_label` (defaults `"system"` if not provided), `changed_at`, `reason`
- [ ] Listener is the source of truth; feature code can't bypass it.
- [ ] UI: "History" button on every editable entity (already wired into
      step 20 detail page; also present on SME, messaging, audience edit screens)
- [ ] History panel shows:
  - Version list (most-recent first), with actor + timestamp + reason
  - Click → diff view (added/removed/changed fields, jsonpatch ops rendered legibly)
  - "Restore this version" action — creates a NEW version that re-applies
    the older state. Never destructive.
- [ ] Bulk imports (CSV in step 09) produce one version per affected row,
      with `actor_label = "csv_import:<filename>"`.

## Security notes
- `content_versions` in the `audit` schema with append-only role permissions.
- `diff jsonb` may contain previously-stored content; same redaction rules apply
  when surfacing in UI (no PII leak).
- Decay never deletes content. Hard delete is admin-only and out of Phase 1 scope;
  flagged for Phase 2 with a 30-day grace period model.

## Acceptance criteria
- [ ] After 7d simulated decay (test clock jump), an unused conference's
      effective rank is measurably lower than a frequently-used one.
- [ ] Editing an SME's bio twice produces two `content_versions` rows;
      applying both diffs in order reconstructs the current state.
- [ ] Restoring a previous version is auditable — produces a NEW diff row.
- [ ] Archived conferences (end_date past 90d) drop from default dashboard.
- [ ] `DECAY_ENABLED=false` returns the system to pure cosine ranking; no code change.
- [ ] History viewer renders diff legibly on every supported entity.

## Open questions for the user
- **Half-lives** — 60d / 365d are starting points; tune after a quarter of real use.
- **Hard delete policy** — recommend admin-only with 30-day grace; defer
  implementation to Phase 2.

## Risks
- Mis-tuned decay hides useful old data. Feature-flagged; `/diagnostics`
  (step 26) shows the freshness distribution histogram for visibility.
- `content_versions` grows. Phase 2: partition by month if it crosses a few million rows.
