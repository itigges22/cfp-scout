# 31 — Configuration Workbook (XLSX) Import / Export

## Goal
A single XLSX workbook that holds all of Scout's seedable reference data —
pillars, audience profiles, SME profiles, messaging documents, past
conferences, topics, industries. **The team collaborates on this workbook in
Google Sheets**, exports it as XLSX, and uploads it to Scout. Round-trip
supported: "Download current configuration" produces an XLSX the team can
re-import after edits.

This is the recommended way to onboard a fresh install and to do bulk
updates. Ad-hoc single-row changes still happen through the wizards in step 09.

## Prereqs
- 04 (schema), 05 (guardrails — Pydantic schemas reused here), 09 (UI for
  the import/export page), 13 (background jobs for post-import embedding regeneration)

## The workbook structure

One XLSX file. Each sheet maps to one entity:

| Sheet name | Maps to | Notes |
|------------|---------|-------|
| `Reference` | (instructions, not data) | First sheet; formatting rules, semicolon-list convention, enum lookups, date format |
| `Pillars` | `strategic_pillars` | The four-pillar strategy |
| `Industries` | controlled vocab for `audience_profiles.industry` | Adminable enum |
| `Audiences` | `audience_profiles` | |
| `Messaging` | `messaging_documents` (structured source only — PDF source still uploaded separately via step 12) | |
| `SMEs` | `smes` | |
| `PastConferences` | `past_conferences` | Same shape as the CSV in step 09; superseded by this if both are present |
| `Topics` | `topics` (controlled vocabulary) | Pre-approved topics; eliminates the pending-review queue for these |
| `Series` | `conference_series` (step 23) | Maintain the known-series catalog (NeurIPS, ICML, KubeCon, etc.) collaboratively |

## Cell format conventions

| Type | Format | Example |
|------|--------|---------|
| Text | UTF-8 plain | `Senior ML Engineers` |
| Array (`text[]`) | Semicolon-separated, no trailing `;`, whitespace stripped | `RAG; Embeddings; Vector DBs` |
| Boolean | `TRUE` / `FALSE` (uppercase) | `TRUE` |
| Date | `YYYY-MM-DD` | `2026-09-15` |
| Enum | Exact-match (case-sensitive) against enum values | `executive` |
| ISO country | ISO-3166-1 alpha-2 | `US` |
| ID (`_scout_id`) | UUID; optional; round-trip identifier | `8c1b...` |
| Action (`_action`) | `upsert` (default) / `delete` / `skip` | `upsert` |

All cells starting with `=`, `+`, `-`, `@` are quoted on import (formula
injection defense).

## Round-trip semantics

- **Export** (`GET /api/v1/config/export-workbook`):
  - Each row includes `_scout_id` (read-only UUID).
  - Inactive rows (`is_active=false`) included with a marker column.
- **Import** (`POST /api/v1/config/import-workbook`):
  - Row has `_scout_id` matching an existing record → **UPDATE**.
  - Row has no `_scout_id` → **INSERT**.
  - Row has `_scout_id` that doesn't exist → error (no silent inserts on bad UUIDs).
  - Row has `_action=delete` → **soft-delete** (`is_active=false`); requires
    typed-count confirmation in the UI preview before applying.
  - A row PRESENT in the DB but MISSING from the upload → **no-op** (never
    auto-deleted; prevents catastrophic "I accidentally deleted a sheet"
    accidents).

## Endpoints

- [ ] `GET /api/v1/config/workbook-template` — empty workbook with all sheets
      and a populated `Reference` sheet showing formatting rules and
      sample rows. The default download for new installs.
- [ ] `GET /api/v1/config/export-workbook` — current state of all entities.
- [ ] `POST /api/v1/config/preview-import` — dry-run; multipart upload returns:
  ```json
  {
    "summary": { "inserts": 12, "updates": 5, "deletes": 0, "errors": 3 },
    "by_sheet": {
      "Audiences": { "inserts": 2, "updates": 1, "errors": [
        { "row": 7, "field": "industry", "value": "TheckTech",
          "error": "Not in allowed Industries enum. Closest: 'Tech'." }
      ] },
      ...
    }
  }
  ```
- [ ] `POST /api/v1/config/import-workbook?confirm_deletes=N` — applies
      the upload. **Refuses if there are any errors.** If deletes exist,
      `confirm_deletes` must equal the count.

## Implementation tasks
- [ ] Add `openpyxl` to api deps.
- [ ] `apps/api/app/services/workbook/`:
  - `reader.py` — parse workbook → typed Pydantic models (reuses step 05 schemas)
  - `writer.py` — write workbook from current state
  - `diff.py` — compute insert/update/delete/error per sheet
  - `apply.py` — atomically apply a valid diff in one transaction
  - `template.py` — generate the empty template
- [ ] Post-apply jobs (enqueued via step 13):
  - `embed_owner` for every new or modified messaging document, SME bio, audience profile
  - Cache invalidation for the in-memory graph (step 16)
  - Recompute matches if pillars or audiences changed (heavy; rate-limited)
- [ ] All changes write to `audit_log` and `content_versions` (step 25),
      with `actor_label = "workbook_import:<filename>:<timestamp>"`.

## UI

- [ ] `/settings/import-export` page:
  - **Download empty template** button → `workbook-template`
  - **Download current configuration** button → `export-workbook`
  - **Import workbook** dropzone:
    1. File selection → POST to `preview-import`
    2. Preview pane: per-sheet diff with inserts/updates/deletes/errors
       (errors red-highlighted with row + field + message)
    3. If errors present: confirm button disabled, "Fix and re-upload" hint
    4. If clean: confirm button enabled; if any deletes, requires typing
       the delete count to confirm
    5. On confirm → POST to `import-workbook`; toast + redirect to dashboard

## Performance
- Validation pass is fast (no DB writes); preview returns in < 2s for typical workbooks.
- Apply pass is one transaction; can take longer due to embedding-regeneration
  jobs enqueued at the end.
- File size cap: 5 MB. Larger workbooks would mean we have bigger problems
  than file size.

## Security notes
- Same `extra='forbid'` strictness as the manual UI; same per-field validators.
- File size cap 5 MB; MIME sniff rejects non-XLSX.
- openpyxl reads cached values for formulas; never executes them. We
  additionally treat any cell with a `data_type='f'` as a hard error
  ("formulas not permitted in import").
- Formula-injection patterns at cell start (`=/+/-/@`) are quoted on
  export and rejected on import.
- The import endpoint is a privileged write; audit-logged with the uploader's
  `actor_label` (defaults to "workbook_import" since no auth, but the UI
  lets the user type a label for the import — appears in audit log).

## Acceptance criteria
- [ ] Downloading the template produces an XLSX with all sheets and a
      filled `Reference` sheet. Opens cleanly in Google Sheets.
- [ ] Uploading the unmodified template produces a preview with all-zero
      changes (no-op) — proves round-trip identity.
- [ ] A workbook with one malformed row in `SMEs` returns the row + field
      + error in the preview and refuses to apply.
- [ ] A workbook that adds 3 audiences and updates 1 SME applies in one
      transaction; `audit_log` shows 4 rows; embedding regeneration jobs
      enqueued.
- [ ] A workbook with `_action=delete` on an SME: requires typed-count
      confirmation; on confirm, soft-deletes; the SME no longer appears in
      matcher results.
- [ ] A workbook that removes a row that exists in DB: that row is **kept**
      in DB (no auto-delete from omission).
- [ ] An exported workbook re-imported with no edits is a no-op (round-trip identity).

## Open questions for the user
- **Action column behavior** — recommend `upsert` (blank/default), `delete`,
  `skip`. Confirm.
- **Empty-omission policy** — recommend "missing rows are kept; delete
  requires explicit `_action=delete`". Confirm. (This is the safe default.)
- **Workbook contains all entities or split into multiple workbooks?** —
  recommend one workbook with all sheets for collaboration simplicity. Confirm.
- **Audit attribution** — letting the user type a label like "May team review"
  on the upload screen so the audit log shows it. Useful?

## Risks
- A malformed workbook can be confusing. The preview's per-row error
  reporting is the primary mitigation. Document common patterns in `Reference` sheet.
- Conflicting concurrent edits between UI wizards and a pending import.
  Acceptable for single-user; the import is one transaction and the wizards
  use optimistic locks via `updated_at`.
- Large embedding-regeneration job after a big import. Show progress in
  `/diagnostics`; user can keep using the app while it runs.
