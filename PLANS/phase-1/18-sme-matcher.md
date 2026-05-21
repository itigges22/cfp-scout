# 18 — SME Matcher (Mechanical Score)

## Goal
Given a conference, rank candidate SMEs by fit using mechanical signals.
Used inside step 17 as Stage C. The qualitative "fit narrative" (LLM-generated)
lives in step 19 and runs only for the top 3 candidates per conference.

## Prereqs
- 11 (embeddings)
- 16 (graph for topic/audience overlap)

## Dimensions

For each (conference, SME) pair:

1. **Topic overlap** — Jaccard between `conference_topics` and `sme_topics`. `[0,1]`.
2. **Audience overlap** — Jaccard between `conference_audiences` and `sme_audiences`.
3. **Bio similarity** — cosine between conference embedding and SME bio chunks (mean of top-3).
4. **Location proximity**:
   - Virtual → 1.0
   - Same country → 1.0
   - Same continent → 0.6
   - Different continent → 0.3
5. **Past attendance signal** — has the SME been to this conference's
   **series** (step 23) before? `+0.1` bonus.
6. **Availability** — Phase 1: `is_active=true`. Calendar integration is Phase 2+.

Composite:
```
sme_score = 0.30 * topic_overlap
          + 0.25 * audience_overlap
          + 0.30 * bio_similarity
          + 0.10 * location_score
          + 0.05 * past_attendance_bonus
```
Weights configurable via env: `SME_W_TOPIC`, `SME_W_AUDIENCE`, etc.

## Tasks
- [ ] `app/services/matcher/smes.py`:
  - `rank_smes_for_conference(conference, k=5) -> list[SmeMatch]`
  - Returns top-k with per-dimension breakdown
  - Filters out `is_active=false`
- [ ] If no SME above `MATCH_S_GATE`, conference status becomes `needs_sme_review` (set by step 17).
- [ ] When top SME is `team != 'DAAM'`, label clearly in rationale and UI ("external recommendation").
- [ ] `GET /api/v1/conferences/{id}/smes` returns ranked list + per-dimension breakdown + "near misses" (just below gate).

## Security notes
- Location uses ISO-3166 codes from the SME profile (validated at entry per step 05).
- "External recommendation" is a UI-side hint; score computation is identical regardless of team.

## Acceptance criteria
- [ ] Tagging an SME with conference topics moves them to or near the top.
- [ ] Location: in-person conference in Tokyo, Tokyo-based SME outranks
      equally-qualified Boston SME.
- [ ] Inactive SMEs never appear.
- [ ] Breakdown surfaced as a small bar chart per dimension in the UI.

## Open questions for the user
- **DAAM bonus** — equal weighting default. Soft bonus for `team='DAAM'`?
- **Location precision** — country only? Add city later if needed.

## Risks
- Sparse SME profiles always lose. `/diagnostics` (step 26) surfaces
  "low-coverage profiles" so the team can fix them.
- Bio similarity dominates when topics are missing. UI nudges tagging.
