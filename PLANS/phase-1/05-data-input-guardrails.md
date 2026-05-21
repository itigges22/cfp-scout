# 05 — Data Input Guardrails

## Goal
**Force structured, validated, manual data entry for everything the user
inputs.** No paste-a-blob-and-we'll-parse-it patterns. The matcher quality
is bottlenecked by data quality; tight guardrails up front are cheaper
than tuning models around messy inputs later.

This plan defines the **contract** that step 09 (manual data entry) and
step 12 (PDF ingestion) must enforce.

## Prereqs
- 04 (schema columns to validate against)

## Principles
1. **Strict typed schemas, not freeform JSON.** Where the schema column
   is `text[]`, the API enforces a closed shape: max items, max length per
   item, allowed characters.
2. **Required fields are actually required.** A messaging document without
   a clear elevator pitch is rejected, not auto-filled.
3. **Enums everywhere a value is bounded.** No "type the team name as a string."
4. **Server-side validation is the source of truth.** Client validation
   is UX; server rejection is the law.
5. **No LLM-parse-then-store paths for user inputs.** The PDF flow exists
   for content the user produced themselves; even there, the structured
   metadata fields are manually entered. The PDF text powers embeddings
   only.
6. **Reject silently-truncating writes.** If a value exceeds the cap, the
   API returns 422 with field-level errors; it never trims and saves.

## Per-entity guardrails

### Messaging documents
- `title` required, 3–120 chars, unique per `is_active=true`.
- `source_type` enum: `structured` | `pdf`.
- If `source_type='structured'` (the recommended path):
  - `elevator_pitch` required, 50–600 chars
  - `target_personas` required, 1–8 items, each 2–80 chars
  - `key_themes` required, 3–12 items, each 2–60 chars
  - `talking_points` required, 3–15 items, each 5–200 chars
  - `differentiators` optional, 0–8 items, each 5–200 chars
  - `competitive_position` optional, 0–600 chars
  - `file_path` MUST be null
- If `source_type='pdf'`:
  - PDF uploaded via step 12 endpoint; metadata above STILL required
  - PDF provides `raw_content` for embedding; metadata fields drive matching weights
  - The PDF upload UI nudges users toward structured entry first

### Audience profiles
- `name` required, 3–80 chars, unique
- `description` required, 50–500 chars
- `industry` from a controlled enum (configurable in code; e.g. `Financial Services`, `Healthcare`, `Government`, `Tech`, etc.)
- `role_seniority` enum: `executive`/`director`/`manager`/`ic`/`mixed`
- `primary_pain_points` required, 2–8 items, each 10–200 chars
- `key_messages` required, 2–8 items, each 10–200 chars
- `exclusion_criteria` optional, 0–5 items, each 10–200 chars

### SMEs
- `full_name` required, 3–100 chars
- `email` optional, RFC5322 validation
- `team` from a configurable closed list (`DAAM`, plus known sibling teams)
- `expertise_areas` required, 2–10 items, each 3–60 chars
- `primary_topics` required, 2–15 topic_ids; **all must exist in `topics` table**
  (no on-the-fly topic creation here)
- `audience_focus` required, 1–8 audience_ids; **all must exist**
- `location_country` required, ISO-3166-1 alpha-2 (validated against a built-in list)
- `location_city` optional, 2–100 chars
- `bio` required, 200–2000 chars (forces real content)
- `languages` optional, ISO-639-1 codes only
- `external_links` is a constrained dict with allowed keys only:
  `{"linkedin": "...", "github": "...", "website": "..."}`. Unknown keys rejected.

### Past conferences
- `name` required, 3–150 chars
- `year` required, integer, 1990 ≤ year ≤ current_year
- `attended_sme_ids` required, ≥1 item; all must exist + be `is_active=true`
- `role` enum: `attendee`/`speaker`/`sponsor`/`organizer`
- `session_type` enum (nullable): `keynote`/`talk`/`panel`/`workshop`/`poster`
- `notes` optional, ≤500 chars
- CSV import follows identical rules; bad rows are rejected with line + field details.

### Topics (admin-only flow)
- `name` required, 2–60 chars, unique (case-insensitive)
- `slug` auto-generated from name
- `aliases` optional, ≤10 items
- New topics created via discovery (step 15 extraction) are inserted with
  `pending_review=true` and **do not enter the matcher** until an admin
  marks them reviewed.

## Implementation tasks

### Backend (`apps/api/app/schemas/`)
- [ ] Pydantic v2 models for every entity, with `model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)`.
- [ ] Custom validators: ISO-3166, ISO-639-1, RFC5322 email, char range checks on text[] items.
- [ ] Enum types as Python `StrEnum`.
- [ ] Bulk-import validators that surface per-row errors with line numbers.
- [ ] Shared error response model returning RFC 7807 problem+json with `errors[]` array.

### Frontend (`apps/web/src/forms/`)
- [ ] **Step-by-step wizards** for messaging and audience profile creation —
      one logical group of fields per screen. Prevents users from saving
      half-finished entries.
- [ ] Inline validation as you type; submit button disabled until valid.
- [ ] Field-level help text on every field explaining what good content looks like.
- [ ] On 422 from the server, surface field-level errors next to the offending field.
- [ ] **No "smart paste" buttons.** No "drag in a doc, we'll fill the fields."
      Hard discipline: if we want quality, we make the user do the work.
- [ ] Auto-save drafts to localStorage so wizard progress survives accidental nav.
      Drafts are local-only and never persisted to the DB until the user submits a complete entry.

### Acceptance pattern
- [ ] Every entity has at least one frontend e2e test that:
  - tries to submit empty form → fails
  - tries to submit minimum-required form → succeeds
  - tries to submit over-length value → fails with field error
  - tries to submit unknown field via API (curl) → server rejects 422

## Security notes
- `extra='forbid'` blocks attribute-injection attempts.
- All text fields are stripped of leading/trailing whitespace; null bytes rejected.
- Enum and length checks prevent log-injection attempts.
- Email and ISO codes validated against authoritative lists (no regex-only).
- Bulk imports never commit partial transactions; all-or-nothing prevents
  corrupted state from script bugs.

## Acceptance criteria
- [ ] Every entity above has a strict Pydantic schema with `extra='forbid'`.
- [ ] Manual API call (curl) trying to omit a required field returns 422 with field name.
- [ ] Frontend wizards exist for messaging and audience entry; SMEs and
      past conferences have form-based (single screen acceptable for small forms) entry.
- [ ] CSV import on past_conferences: a single bad row in a 100-row file
      produces line-and-field error and zero inserts.
- [ ] A discovered topic from scraping does not enter the matcher until
      marked reviewed by an admin.

## Open questions for the user
- **Industry enum** — give me the list of industries to support, or recommend
  Red Hat's standard 6-8 industries?
- **Length caps** — calibrated for typical content; flag any too tight after first use.
- **Wizard or single-screen?** — wizards for the long ones (messaging,
  audience); single screen for SME (familiar form pattern). Confirm.

## Risks
- Tight guardrails create friction. We trade upfront UX cost for downstream
  match quality. Phase 1 success depends on the team accepting this trade.
- The "industry" enum may not cover edge cases. Make it admin-editable in
  a `lookup_values` table if churn proves too high.
