# 09 — Manual Data Entry (Guarded)

## Goal
Build the CRUD surface for the four manually-entered data types. **Every
field is enforced by the guardrails from step 05.** Wizards for the long
ones; structured forms for the short ones. No paste-and-parse.

This step covers **ad-hoc edits** through the UI. For **bulk seeding and
team collaboration via Google Sheets**, see plan [31](31-configuration-workbook-import-export.md) —
the XLSX workbook import/export reuses the exact same Pydantic schemas
defined in step 05, so guardrails apply equally to both paths.

## Prereqs
- 04 (schema), 05 (guardrails), 06 (API), 08 (frontend)

## Backend tasks (`/apps/api`)
- [ ] CRUD endpoints under `/api/v1/`:
  - `messaging-documents`
  - `audience-profiles`
  - `smes`
  - `past-conferences`
  - `topics` (admin: review/approve pending topics from extraction)
- [ ] Pydantic schemas reuse step 05 models with `extra='forbid'` everywhere.
- [ ] List endpoints: page-based pagination, `?q=` substring search, `?is_active=true`.
- [ ] Validators enforce step 05 rules — server-side rejection on any violation.
- [ ] CSV import for past_conferences:
  - `POST /api/v1/past-conferences/import` (multipart)
  - Canonical columns: `name, year, attended_by_names, role, session_type, notes`
  - `attended_by_names` semicolon-separated; matched case-insensitively against
    `smes.full_name` (with unaccent); unknown names → error with row number
  - Full transaction; rollback on any row error unless `?ignore_errors=true`
  - Response: `imported`, `skipped`, `errors[]`
- [ ] Soft delete only (`is_active=false`); never hard-delete.
- [ ] Any update to messaging or SME bio enqueues an embedding regeneration job (step 11).
- [ ] All writes produce `audit_log` + `content_versions` rows automatically
      (SQLAlchemy event listener, step 25).

## Frontend tasks (`/apps/web`)
- [ ] `/messaging`:
  - card list by title, active/inactive badges
  - **"New messaging document" → multi-step wizard**:
    1. Title + source_type (structured/pdf)
    2. Elevator pitch (with character counter + good-example placeholder)
    3. Target personas (chip-input, 1–8 items)
    4. Key themes + talking points (separate steps, chip-input)
    5. Optional: differentiators + competitive position
    6. Review screen showing everything before submit
  - PDF source variant inserts a PDF upload step (step 12) between #2 and the rest;
    the structured fields are STILL required even for PDF source
- [ ] `/audiences`:
  - table view: name, industry, role_seniority, status
  - **"New audience profile" → multi-step wizard**:
    1. Name + description
    2. Industry (select) + role_seniority (select)
    3. Pain points (chip-input)
    4. Key messages (chip-input)
    5. Optional exclusion criteria
    6. Review
- [ ] `/smes`:
  - tab switcher: DAAM | Non-DAAM | All
  - card layout: name, team, top topics, location flag
  - **Single-screen form** (well-known pattern) with sections:
    Identity / Expertise / Topics + Audiences / Location / Bio / Links
  - Bio has min-200 / max-2000 char counter
  - Topics autocomplete against approved `topics`; no inline creation
  - Audiences multi-select against existing audience_profiles
- [ ] `/past-conferences` (under `/settings`):
  - List + form-based manual add
  - **CSV import flow**: drop zone → preview parsed rows (with errors highlighted)
    → confirm → result toast. Download CSV template button.
- [ ] `/settings/topics`:
  - List active and pending topics
  - Approve / merge / reject pending topics (from extraction in step 15)
- [ ] **No "smart paste" shortcuts anywhere.** No "drag a CV here." Discipline.
- [ ] Autosave wizard progress to `localStorage` keyed by entity + UUID;
      cleared on submit. Drafts never reach the DB.

## Security notes
- All inputs validated server-side by Pydantic (step 05 schemas) with `extra='forbid'`.
- CSV import sanitizes formula-injection patterns at cell start (`=`, `+`, `-`, `@`).
- File uploads MIME-sniffed, not extension-trusted.
- Topic autocomplete uses parametrized server-side search; client never sends raw SQL.
- Free-form text fields rendered with React's default escaping.
- Audit log + content versions populated automatically on every write.

## Acceptance criteria
- [ ] All resources fully CRUD-able via the wizards/forms.
- [ ] Attempting curl POST with a missing required field → 422 with field name.
- [ ] Attempting curl POST with an extra unknown field → 422 (`extra='forbid'`).
- [ ] CSV import: bad row → exact line + field reported; zero inserts on failure.
- [ ] Refresh during wizard → progress restored from localStorage.
- [ ] No raw-string SQL anywhere; mypy --strict passes.

## Open questions for the user
- **Multi-step wizard vs single screen** — wizards for messaging + audience
  (heavy entries), single screen for SME (familiar pattern), CSV+form for past
  conferences. Confirm.
- **Topic review workflow** — single user, but recommend keeping the
  `pending_review=true` gate so newly-discovered topics don't silently pollute
  the matcher. Confirm.

## Risks
- Wizards add friction. We pay this cost on purpose. The team's time
  investment in good messaging directly drives match quality.
- Topic vocabulary discipline depends on the user actually reviewing
  pending topics. Diagnostics page (step 26) surfaces the queue size.
