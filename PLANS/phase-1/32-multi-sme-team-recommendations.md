# 32 — Multi-SME Team Recommendations

## Goal
For high-fit conferences, recommend **complementary teams** of 2 or 3 SMEs
instead of just ranked individuals. The selection rewards topic diversity
(no two team members redundant) while keeping individual fit high. Pure
algorithmic — no LLM calls, no extra cost.

## Prereqs
- 18 (mechanical SME matcher provides candidate ranking)
- 19 (per-SME fit narratives — surfaced alongside team recs)

## Why this matters
For a big conference like KubeCon, DAAM typically sends multiple people:
one to give a talk, one to engage attendees, one to attend deeply. Currently
plan 18 just ranks individuals. Picking the second-ranked SME is often a
poor team choice — they may have nearly identical expertise to the first
(both RAG experts), leaving other relevant topics (e.g., MLOps) uncovered.

## Algorithm

1. From `rank_smes_for_conference`, take **top-K** candidates (default K=10).
2. Score every candidate **team** of size n ∈ {1, 2, 3}:
   ```
   team_score(team)
     = avg_individual_fit * α
     + topic_coverage_breadth * β
     - topic_redundancy * γ
     - location_redundancy * δ
   ```
   Defaults: α=0.5, β=0.35, γ=0.10, δ=0.05. Env-tunable.
3. **Topic coverage breadth**: count of distinct conference topics that AT
   LEAST ONE team member is `expert_in`, divided by total conference topics.
4. **Topic redundancy**: Jaccard similarity between pairs of team members'
   topic sets, averaged across the team. High value = members cover the
   same ground; penalized.
5. **Location redundancy**: same-city penalty if 2+ members based in same
   city for an in-person event (trivial signal; can be zeroed).
6. Combinatorial selection is cheap at K=10:
   - C(10,1) = 10
   - C(10,2) = 45
   - C(10,3) = 120
   Total ~175 candidate teams. Sub-millisecond to score.
7. Return **top-1 individual**, **top-1 pair**, **top-1 triple**.

## Persisted output

Add to `matches` (or a new `match_teams` table):

```sql
-- new table preferred
CREATE TABLE app.match_team_recommendations (
  match_id        uuid REFERENCES app.matches(id) ON DELETE CASCADE,
  team_size       smallint NOT NULL CHECK (team_size IN (1, 2, 3)),
  sme_ids         uuid[] NOT NULL,
  team_score      real NOT NULL,
  coverage_breadth real NOT NULL,
  redundancy      real NOT NULL,
  rationale_text  text,
  computed_at     timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (match_id, team_size)
);
```

## Tasks

### Backend
- [ ] Migration adds `match_team_recommendations`.
- [ ] `app/services/matcher/teams.py`:
  - `recommend_teams(conference, k=10) -> dict[int, TeamRecommendation]`
  - Returns team-of-1, team-of-2, team-of-3
- [ ] Enqueued automatically after `run_fit_match` completes (step 17 pipeline).
- [ ] Idempotent: re-running for same `(conference, algorithm_version)` skips.
- [ ] **No new LLM calls** for the team rec itself. We do generate a short
      rationale string ("**Why this pair?** Sarah covers RAG; Marcus covers
      MLOps; together they cover 5 of the conference's 6 topics.") — this
      can be templated (no LLM) for Phase 1.
- [ ] `GET /api/v1/conferences/{id}/team-recommendations` returns all three.

### Frontend (extends step 20 conference detail page)
- [ ] SME panel updated to show a **team selector**:
  - Tab: "1 person" | "2 people" | "3 people"
  - Each tab shows the recommended team for that size, with:
    - Each member's name + role hint (e.g., "primary speaker", "secondary")
    - Per-member fit narrative (from step 19, only for top-3 individuals)
    - Templated team rationale (one sentence)
    - Coverage visualization: which conference topics each member covers
      (small chips, colored)
- [ ] Default tab depends on conference signal (presence of multiple
      deadlines, multiple session types) — but always recoverable to "1 person."

## Edge cases
- **Fewer than K candidates**: with only 5 active SMEs, the algorithm runs
  on what's available; team-of-3 may not be feasible (returns null).
- **All candidates from same team (DAAM-only)**: that's fine — diversity
  is on topic, not on org.
- **External SMEs included**: same scoring; UI labels them clearly.

## Security notes
- Pure computation over existing validated data; no new attack surface.
- Templated rationale text — no LLM, no prompt injection vector.
- `match_team_recommendations` audit-logged like other matcher outputs.

## Acceptance criteria
- [ ] After `run_fit_match` completes on a fixture conference with 8 candidates,
      `match_team_recommendations` contains entries for team_size 1, 2, 3.
- [ ] For a conference whose topics are {RAG, MLOps, GitOps}, the team-of-2
      contains one RAG-expert + one MLOps-or-GitOps-expert — not two
      RAG-experts.
- [ ] Topic redundancy penalty visibly drops scores for redundant pairs in tests.
- [ ] UI tabs render the three team recs with coverage chips.
- [ ] Setting `MATCH_TEAM_REDUNDANCY_WEIGHT=0` in env makes the algorithm
      degrade to "top-N individuals" (verifies the knob works).

## Open questions for the user
- **Default team sizes** — 1/2/3. Add 4-5 for huge conferences? Recommend
  cap at 3 for Phase 1; rare team needs more.
- **Weight defaults** — `0.5/0.35/0.10/0.05`. Tune after first 20 conferences.
- **External-SME inclusion logic** — recommend: include if their individual
  score clears `MATCH_S_GATE`. The team rationale clarifies the external
  recommendation. Confirm.

## Risks
- A "complementary" pair on paper may be a poor fit in practice if the two
  members don't actually collaborate well. We can't model interpersonal
  dynamics; the team applies judgment. The recommendation is a starting point.
- Coverage breadth can over-reward niche topic coverage. Mitigated by
  individual-fit weight (α=0.5) staying dominant.
