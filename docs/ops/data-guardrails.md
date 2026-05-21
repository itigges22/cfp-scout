# Data input guardrails — what's rejected and why

This page is what to consult when the api returns a 422 from a manual
form, a CSV import, or an XLSX workbook upload.

The schemas live in `apps/api/app/schemas/`. The design rationale is in
[plan 05](../../PLANS/phase-1/05-data-input-guardrails.md). This doc
exists for operators ("why was my row rejected?") rather than for
implementers.

## The core rules

Every input schema in Scout inherits from `StrictBase`, which sets:

| Behaviour | Effect |
|-----------|--------|
| `extra='forbid'` | Unknown keys are an error. `{"linked_in": "..."}` returns 422 — typos don't silently disappear. |
| `str_strip_whitespace=True` | Leading/trailing whitespace stripped on every string field. `"  RAG  "` is stored as `"RAG"`. |
| ISO validation | `location_country` must be a real ISO-3166-1 alpha-2 code (US, DE, JP, ...). `languages` are ISO-639-1 (en, de, ja). |
| Email validation | RFC5322 via `email-validator`. |

If something looks wrong, check this page first — most "why didn't it work" questions are answered here.

## Per-entity rules

### Messaging document

| Field | Rule |
|-------|------|
| `title` | 3-120 chars |
| `source_type` | `structured` or `pdf`. The structured-entry endpoint refuses `pdf` (use the upload endpoint instead, plan 12) |
| `elevator_pitch` | 50-600 chars. Forces real content; rejects "AI is great." |
| `target_personas` | 1-8 items, each non-empty |
| `key_themes` | 3-12 items |
| `talking_points` | 3-15 items, each 5-200 chars |
| `differentiators` | optional; up to 8 items |
| `competitive_position` | optional; up to 600 chars |

Rejection examples:

- `elevator_pitch` is 40 chars → "ensure this value has at least 50 characters"
- 2 items in `key_themes` → "List should have at least 3 items"
- `{"title": "..."}` only → "Field required: source_type", etc.

### Audience profile

| Field | Rule |
|-------|------|
| `name` | 3-80 chars, unique |
| `description` | 50-500 chars |
| `industry` | 2-80 chars freeform; the *service layer* (plan 09) further checks it against the team's `industries` vocabulary maintained via the XLSX workbook |
| `role_seniority` | one of `executive` / `director` / `manager` / `ic` / `mixed` |
| `primary_pain_points` | 2-8 items |
| `key_messages` | 2-8 items |
| `exclusion_criteria` | optional; up to 5 items |

### SME

| Field | Rule |
|-------|------|
| `full_name` | 3-100 chars |
| `email` | optional; RFC5322 |
| `team` | 2-60 chars (free-form for now; `DAAM` or a sibling team name) |
| `expertise_areas` | 2-10 items |
| `primary_topics` | 2-15 UUIDs — must exist in `topics` (FK check by service layer) |
| `audience_focus` | 1-8 UUIDs — must exist in `audience_profiles` |
| `location_country` | ISO-3166-1 alpha-2 (`US`, `DE`, `JP`, ...). Case is normalized to upper |
| `location_city` | optional; up to 100 chars |
| `bio` | **200-2000 chars**. The 200-char minimum is deliberate — empty / two-sentence bios produce poor embeddings and bad matches |
| `languages` | ISO-639-1 codes (`en`, `de`, `ja`, ...) |
| `external_links` | only `linkedin`, `github`, `website` keys are allowed. Unknown keys (e.g. `twitter`) → 422 |

### Past conference

| Field | Rule |
|-------|------|
| `name` | 3-150 chars |
| `year` | 1990 ≤ year ≤ current_year (no future events here — those go in `conferences`) |
| `series_id` | optional UUID; FK to `conference_series` |
| `attended_sme_ids` | at least one UUID |
| `role` | `attendee` / `speaker` / `sponsor` / `organizer` |
| `session_type` | optional; `keynote` / `talk` / `panel` / `workshop` / `poster` |
| `notes` | optional; up to 500 chars |

### CSV import (past_conferences)

Same as above with one twist: SMEs are matched by **name** rather than UUID
in the CSV. The service layer (plan 09) does case-insensitive matching
against `smes.full_name`; **unknown names error with the exact row + value**.

Canonical columns:

```
name,year,attended_by_names,role,session_type,notes
"NeurIPS 2024",2024,"Ian Tigges; Sarah Chen",attendee,,"led 1:1s with research labs"
```

`attended_by_names` is semicolon-separated. The full string is 600 chars max
in the schema; if you need more, that's already a sign you should split into
two rows.

### Topic vocabulary

| Field | Rule |
|-------|------|
| `name` | 2-60 chars, unique (case-insensitive) |
| `slug` | optional; auto-derived from name if absent. Lowercase + dash-separated |
| `aliases` | up to 10; each 2-60 chars |

LLM-discovered topics (plan 15) are inserted with `is_active=false` and
`pending_review=true`. They do **not** appear in dropdowns or influence
matching until an admin approves them via `/settings/topics`.

## Bulk import (CSV + XLSX)

Both bulk paths run inside a single transaction:

- **All rows valid** → commit; embedding-regen jobs enqueued; audit/version rows written
- **Any row invalid** → no inserts, no updates. The response lists row + field + reason.

To force-ignore bad rows (use sparingly), pass `?ignore_errors=true` on the
CSV endpoint. The XLSX endpoint refuses the equivalent — workbooks are
expected to be clean since the team collaborates on them in Google Sheets.

## What the schemas explicitly DO NOT do

- They don't write to the database. They validate input only. FK existence
  checks (does this `topic_id` exist?) live in the service layer with DB access.
- They don't run the LLM. Anything that uses an LLM is a separate plan
  (15 for extraction, 17 for rationale, 19 for narrative, 22 for chat).
- They don't enforce uniqueness across rows in a CSV. That's the service
  layer's job too (it batches the validated rows, then checks uniqueness
  before the transaction commits).

## Related plans

- [plan 05](../../PLANS/phase-1/05-data-input-guardrails.md) — design
- [plan 09](../../PLANS/phase-1/09-manual-data-entry.md) — UI wizards consuming these schemas
- [plan 15](../../PLANS/phase-1/15-data-validation-and-routing.md) — LLM extraction respects the same shape
- [plan 31](../../PLANS/phase-1/31-configuration-workbook-import-export.md) — XLSX import runs every row through these schemas
