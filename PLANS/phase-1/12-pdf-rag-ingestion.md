# 12 — PDF / RAG Ingestion

## Goal
Allow users to upload PDFs (messaging decks, audience profile docs, past
conference summaries) for ingestion into the chunk + embedding pipeline.
**Structured metadata fields from step 05 are STILL required**; the PDF
contributes the embedding corpus, not the matching dimensions.

## Prereqs
- 11 (embeddings)
- 13 (background jobs)
- 05 (guardrails — metadata fields)

## Tasks

### Upload contract
- [ ] `POST /api/v1/uploads/pdf` (multipart):
  - max size: 25 MB
  - MIME sniff (reject non-PDF)
  - reject encrypted / password-protected
  - reject > 200 pages
  - `purpose` required enum: `messaging`, `audience`, `sme_bio`, `past_conference`
  - `owner_id` required — the structured entity it attaches to (created via step 09 first)
  - response: 202 + job id

### Parsing
- [ ] `pypdf` for native PDFs.
- [ ] If text yield < 100 chars/page average → fall back to **`ocrmypdf`** (Tesseract).
- [ ] Extract: full text, page-level text, PDF metadata.
- [ ] Persist:
  - Original PDF → `STORAGE_PATH/pdf_uploads/<uuid>.pdf`. Path stored on owner.
  - Extracted text → owner's `raw_content`.
  - Then `embed_owner` via step 11.

### Strict rules (PDF: "Only documents from which we need data.")
- [ ] Filename denylist (configurable regex; default blocks `*resume*`,
      `*confidential*`, `*pricing*`, `*offer-letter*`). Match triggers an
      explicit confirmation dialog.
- [ ] PII signal scan (emails, phones, SSN-like, CC-like):
  - For `purpose != sme_bio`: any match → quarantine + diagnostics notification
  - For `sme_bio`: names/emails expected; only SSN/CC patterns block
- [ ] Per-call size caps; oversized → reject with clear error.
- [ ] Parsing happens in APScheduler tasks (step 13), never in request thread.
- [ ] **PDF upload alone never creates an entity.** The user must have
      already created the structured row (messaging document with elevator
      pitch + themes; SME with bio sections; etc.) — the PDF augments, never
      replaces, structured input.

### Job tracking
- [ ] `ingest_jobs` row per upload with phases:
      `received → parsed → chunked → embedded → indexed → complete` (or `failed`)
- [ ] UI polls (or SSE) for status; toast on completion or failure.

### UI
- [ ] On `/messaging` and similar pages, the "Attach PDF" action only
      appears when an owner row exists.
- [ ] Dropzone with: file picker + purpose pre-filled from context + upload progress.
- [ ] Post-parse: shows first 1000 chars of extracted text for sanity check.
- [ ] "Confirm ingest" or "Discard" (discard removes file + clears `raw_content`).

## Security notes
- PDFs are hostile by default. Parsing has CPU + memory limits via
  `deploy.resources.limits` in compose.
- `pypdf` pure Python — small native surface. `ocrmypdf` runs as subprocess
  with hard timeout and a tmpfs temp dir.
- Files stored under generated UUID names; original filename kept only as metadata.
- Optional ClamAV sidecar deferred unless explicitly required.
- Denylist requires explicit confirm to override.

## Acceptance criteria
- [ ] A 10-page text PDF: chunks visible in DB and searchable in < 30s.
- [ ] A scanned PDF triggers OCR; chunks eventually present.
- [ ] A corrupt PDF returns clean error; no orphan rows; no leaked file.
- [ ] A PDF matching the denylist requires explicit confirm.
- [ ] A PDF with SSN-pattern in non-sme_bio context → quarantine.
- [ ] Attempting to upload without a structured owner entity → 400.
- [ ] Failed jobs visible in `/diagnostics` with retry.

## Open questions for the user
- **PII policy specifics** — confirm SME bios are exempt for name/email
  but always blocked on SSN/CC.
- **Max pages override** — 200 conservative; admin override per upload?
- **OCR languages** — Tesseract default English; add others later.

## Risks
- OCR is slow. UI shows estimated time; job runs in background.
- Worst-case PDF can hang `pypdf`. Hard timeout per parse.
