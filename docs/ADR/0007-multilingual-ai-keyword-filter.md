---
adr: "0007"
title: Multilingual AI keyword filter as an editable runtime setting
status: accepted
date: 2026-05-23
supersedes: ""
superseded_by: ""
---

# 0007 — Multilingual AI keyword filter as an editable runtime setting

## Context

Scout's bulk discovery pipeline ingests the `developers.events` feed (a few
thousand events per pull) and uses a coarse keyword filter to decide which
rows are AI-relevant enough to persist and score. The matcher does the
fine-grained ranking downstream; the keyword filter is a pre-filter.

The initial implementation was 16 hardcoded English keywords (`ai`, `ml`,
`machine learning`, `llm`, `gpt`, etc.) matched against the event's name
and tags. Two problems surfaced quickly:

1. **English-only.** Conferences in Spanish, Portuguese, Japanese, and
   Chinese with names like "Inteligencia Artificial Latam 2026" or
   "人工知能カンファレンス 2026" were being silently dropped. User feedback
   was explicit: *"find conferences in MULTIPLE different languages,
   there are none in LATAM, like 2 in Asia... We need to find more!"*
2. **Tag-only scan misses signal.** Many events tag themselves generically
   ("tech", "developer") with the AI signal living in the description. The
   filter couldn't see those.

The asymmetry that drives the design: **flooding the candidate set with
false positives is cheap** (the matcher ranks them down), **missed AI
events are expensive** (they never reach the user). The filter should err
toward letting too much through.

A third issue is operational: a hardcoded list means every iteration needs
a code change, a PR, and a redeploy. The vocabulary of AI events is
evolving fast ("MCP servers", "agentic protocols") and the operator —
not engineering — is the one who notices new terms in the feed.

## Decision

The AI-event filter is a **multilingual keyword list stored as an editable
runtime setting** (`discovery_ai_keywords`, `kind="list_str"`), NOT a
hardcoded constant. The filter scans **name + topics + description** (was
name + tags only).

A hardcoded default constant `_AI_KEYWORDS` lives in the same module as
the filter and is used when the runtime setting is empty (fresh install,
operator cleared it). The default ships **148 keywords** spanning:

- EN core (`ai`, `ml`, `llm`, `gpt`, `genai`, `agents`, `rag`, …)
- LLM ecosystem (`langchain`, `vector db`, `mcp`, `agentic`, …)
- Modalities (`vision`, `multimodal`, `speech`, …)
- Platforms (`pytorch`, `tensorflow`, `huggingface`, …)
- Adjacent terms (`alignment`, `fairness`, `responsible ai`)
- Spanish (`inteligencia artificial`, `aprendizaje automático`)
- Portuguese (`inteligência artificial`, `ciência de dados`)
- French, German
- Japanese (`人工知能`, `機械学習`, `深層学習`)
- Chinese (`人工智能`, `机器学习`, `大模型`)
- Korean (`인공지능`, `머신러닝`)

Editing happens at `/settings/tunables` as a textarea, one keyword per
line.

## Consequences

**Positive**
- **Recall improves immediately** on non-English regions. Latam, Brazil,
  Japan, China, Korea events that previously dropped now flow into the
  candidate set and get scored.
- **Operator-editable.** New emerging terms ("MCP servers", "agentic
  protocols") can be added without an engineering loop. The textarea is
  the interface; no redeploy.
- **Description-aware.** Catches events that tag themselves generically
  but describe AI content. Big recall win in absolute terms.
- **Fallback is safe.** Empty setting reverts to the hardcoded 148-item
  default; the system never enters a "no filter at all" state.

**Negative**
- **More events pass the filter → more matcher work per ingest.** Mitigated
  by the matcher's per-conference cost being small (~2 s) and one-shot
  per row. At ~500 rows/pull this is acceptable.
- **Substring matching is dumb.** "GPT" matches "GPTW Best Workplaces" if
  someone adds the substring `gpt` without word boundaries. We accept the
  occasional false positive — the matcher ranks it down — but the operator
  should prefer multi-character anchored terms over 2–3 letter tokens.
- **Operator can break the filter.** Clearing the setting reverts to
  default (safe). Pasting in a single overly-broad keyword like `event`
  would let everything through; the operator owns this.
- **Per-language nuance is shallow.** A keyword list isn't a stemmer or
  tokenizer; "aprendizaje automático" only matches that exact substring,
  not inflected forms. Acceptable as a pre-filter.

**Neutral**
- The matcher is unchanged. This decision is about widening the *funnel*
  feeding the matcher, not the matcher itself.

## Alternatives considered

- **Keep keywords hardcoded but expand the list** — Lost because: every
  iteration needs a code change + redeploy; no way for the operator to
  react to new terms without involving engineering. Solves the recall
  problem but not the operability problem.
- **Use an LLM call to classify each event as AI/not-AI** — Lost because:
  ~5,773 LLM calls per feed ingest is serious budget burn for a coarse
  pre-filter; the matcher already does the fine-grained scoring
  downstream; latency would multiply by ~1 s per row.
- **Embed a local multi-label classifier model** — Lost because: 50–200 MB
  model artifact for what is fundamentally substring matching against a
  known vocabulary. Disproportionate.

## Implementation

- **Setting**: `apps/api/app/settings.py` — `discovery_ai_keywords: list[str]`
- **Filter**: `apps/api/app/services/web_discovery/feeds.py` —
  `_looks_ai_related()` reads from `get_settings().discovery_ai_keywords`,
  falls back to `_AI_KEYWORDS` constant when empty. Scans
  `name + topics + description` (case-insensitive).
- **Admin schema**: `apps/api/app/api/v1/admin_settings.py` — a
  `SettingSpec` with `kind="list_str"` for newline-delimited textarea
  editing.
- **UI**: `apps/web/src/routes/settings_.tunables.tsx` — new `list_str`
  branch in the control switch renders a textarea bound to the setting.

## References

- [ADR-0005](0005-auto-run-matcher-on-first-view.md) — the matcher is
  fast and self-healing, which is what lets us be permissive at the
  pre-filter.
- [`docs/web-discovery.md`](../web-discovery.md) — the discovery pipeline
  this filter gates.
- `apps/api/app/services/web_discovery/feeds.py` — implementation
