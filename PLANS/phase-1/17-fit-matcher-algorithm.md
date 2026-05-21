# 17 — Fit Matcher Algorithm

## Goal
Multi-stage match: messaging → pillars → SME, with explicit exits.
Produces overall score, recommended SMEs, and short written rationale.

## Prereqs
- 11 (embeddings)
- 16 (graph for SME stage)

## Algorithm (per the PDF, formalized)

### Stage A — Messaging fit (gate)
- Top-K similarity search of conference text chunks against
  `document_chunks WHERE owner_type='messaging'`.
- `messaging_score = mean(top_k_cosines)`, k=10.
- Threshold `MATCH_M_GATE` (env, default 0.55).
- **Exit:** below gate → status `low_messaging_fit`. Excluded from default views, not deleted.

### Stage B — Four-pillar alignment
- For each pillar: top-K similarity between conference chunks and the
  pillar description + supporting messaging docs.
- `pillar_score = max(per_pillar_scores)`. Record which pillar(s) matched.
- Threshold `MATCH_P_GATE` (env, default 0.55).
- **Exit:** below gate AND above messaging gate → status `needs_review_pillar`.
  Surface in review queue.

### Stage C — SME match
- Delegates to step 18. Returns ranked `(sme_id, score)` list.
- Threshold `MATCH_S_GATE` (env, default 0.5 for top SME).
- **Exit:** no SME above gate → status `needs_sme_review`. Still in dashboard.

### Final score
```
overall = MATCH_W_MESSAGING * messaging_score
        + MATCH_W_PILLAR    * pillar_score
        + MATCH_W_SME       * sme_score
```
Defaults: `0.35 / 0.35 / 0.30`. Tunable **via env vars only** — no UI page
for editing weights (step 20 reflects this).

### Rationale text
One LLM call summarizes the why:
- Inputs: top-k messaging snippets, top pillar match excerpt with name,
  top-3 SMEs with relevant expertise.
- Output: 2–3 sentences. Structured: "Aligns with X. Strongest pillar tie:
  P because Y. Recommended SMEs: A (reason), B (reason)."
- Stored in `matches.rationale_text`.

## Tasks
- [ ] `app/services/matcher/`:
  - `messaging.py` (Stage A)
  - `pillars.py` (Stage B)
  - `smes.py` → delegates to step 18
  - `rationale.py` (LLM call)
  - `pipeline.py` — orchestrates → `MatchResult`
- [ ] Persist in `matches`; `algorithm_version` tracks code revision.
- [ ] Auto-enqueue `run_fit_match(conference_id)` after ingest or when
      source data changes.
- [ ] Bulk recompute triggered by:
  - messaging changes
  - pillar definition changes
  - SME roster changes
  - `algorithm_version` bump
  - manual admin trigger
- [ ] Thresholds + weights in `.env`. No UI editor.
- [ ] Tests (`LLM_DRY_RUN=true`) verify:
  - off-topic → excluded
  - clearly-aligned → high score
  - borderline → `needs_review`

## Security notes
- Rationale prompt receives snippets that could contain hostile instructions.
  Same delimiting + system prompt as step 15.
- Rationale must quote evidence. Post-validation: if rationale references
  content not in passed-in snippets (fuzzy substring), retry once; if still
  bad, store `"<unverified>"` and flag for review.
- All scores bounded to `[0, 1]` before persistence.

## Acceptance criteria
- [ ] New conference flows through all three stages without manual intervention.
- [ ] `matches` row stored with breakdown; `algorithm_version` set.
- [ ] Changing weights in `.env` + restart updates downstream scores after
      `recompute_all_matches`.
- [ ] Rationale low-temperature consistent; references real evidence.
- [ ] No conference reaches dashboard ranking without a `matches` row.

## Open questions for the user
- **Threshold defaults** — `0.55 / 0.55 / 0.5` starting points for nomic;
  expect tuning after first 50 conferences.
- **Score display** — 0–100 with 5-bucket badge (poor/weak/okay/good/strong).
  Confirm.

## Risks
- Cosine on small chunks is noisy. Top-K mean smooths it. Switchable to
  Top-K max via `MATCH_TOPK_AGG` env if needed.
- "Rationale" call can hallucinate evidence. Post-validation catches most.
