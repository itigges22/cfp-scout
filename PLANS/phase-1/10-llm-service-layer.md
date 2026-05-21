# 10 — LLM Service Layer (Red Hat MaaS)

## Goal
A provider-agnostic abstraction for talking to Red Hat MaaS via its
OpenAI-compatible API. Same client for chat and embeddings. Retries,
cost accounting, dry-run mode, budget guardrail.

## Prereqs
- 06 (API + settings)
- 07 (`LLM_*` env keys)

## Why one client for everything
Both chat and embeddings ride the same OpenAI-compatible HTTP API. One
client = one auth path, one retry policy, one cost meter, provider
portability via env vars.

## MaaS model catalog (locked in)

What MaaS exposes and what we use:

| Model | Role | Why |
|-------|------|-----|
| `granite-3-2-8b-instruct` | **Default chat** for all purposes | Red Hat–aligned, 4M context, $0.50/M, solid 8B instruction-following |
| `nomic-embed-text-v1-5` | **Embeddings** (only embedding model on MaaS) | 768 dim, $0.02/M input, $0.00/M output |
| `deepseek-r1-distill-qwen-14b` | Reserved override for reasoning-heavy steps | R1 distill = better structured reasoning; 500k context, $0.80/M, has function calling |
| `Llama-Guard-3-1B` | Optional safety classifier (step 29) | Cheap ($0.10/M), classifies hostile/harmful content; defense-in-depth |
| `granite-4-0-h-tiny` | Reserved fallback for low-priority bulk work | Dirt cheap ($0.05/M), 4M context; small model, quality TBD |
| Others (`codellama`, `qwen3-14b`, `llama-scout-17b`, `microsoft-phi-4`, `openai/deepseek-r1-distill-qwen-14b`) | Not used | Either redundant with our default or wrong shape for our needs |

Per-purpose overrides (env vars, default to `LLM_CHAT_MODEL`):
- `LLM_EXTRACTION_MODEL` — used by step 15 if reasoning quality matters
- `LLM_NARRATIVE_MODEL` — used by step 19 for SME fit narratives
- `LLM_AGENT_MODEL` — used by step 22 for the chat panel

The point: we ship with `granite-3-2-8b-instruct` everywhere. If a specific
step misbehaves, the override env var lets us swap to deepseek-r1 without
touching code.

## Tasks
- [ ] `app/services/llm/`:
  - `client.py` — `LLMClient` wrapping `openai` SDK with `base_url` set to MaaS
  - `models.py` — `ChatRequest`, `EmbeddingRequest`, response types
  - `costs.py` — per-model price table from env JSON; computes `cost_usd`
  - `retries.py` — tenacity-based retry on 429/5xx with jittered backoff
  - `rate_limit.py` — per-process token bucket
  - `dry_run.py` — deterministic fake responses when `LLM_DRY_RUN=true`
- [ ] Surface:
  ```python
  class LLMClient:
      async def chat(self, *, messages, model=None, purpose: str, stream=False, **kwargs) -> ChatResponse: ...
      async def embed(self, *, texts: list[str], model=None, purpose: str) -> list[list[float]]: ...
  ```
- [ ] Every call → `llm_calls` row:
  - `model`, `purpose` (`extract_conference`/`rationale`/`fit_narrative`/`agent_chat`/`embedding`/`topic_normalize`)
  - `prompt_tokens`, `completion_tokens`, `cost_usd`, `latency_ms`, `request_id`, `error`
- [ ] Streaming for the agent chat (step 22).
- [ ] Embeddings batched; order preserved.
- [ ] **Dry-run** (`LLM_DRY_RUN=true`): deterministic canned + hashed-input vectors.
- [ ] **Monthly budget guardrail**:
  - Sum `cost_usd` for the current calendar month before each call
  - Over `LLM_MONTHLY_BUDGET_USD` → `BudgetExceeded` → API returns 503
  - Soft warn at 80% (WARN log + surfaced in `/diagnostics`)
  - Per-call `force=True` override (admin-triggered jobs only)

## Security notes
- API key only in `.env`. Structlog redactor scrubs from all logs.
- httpx uses `verify=True`; never disable TLS.
- Per-call body cap (e.g., 100k chars for chat) prevents oversized prompts.
- MaaS endpoint configurable so corporate proxies / air-gapped vLLM endpoints
  work without code changes.

## Acceptance criteria
- [ ] Switching providers = 3 env vars (`LLM_BASE_URL`, `LLM_API_KEY`, `LLM_CHAT_MODEL`). No code changes.
- [ ] `LLM_DRY_RUN=true` runs the full match pipeline offline in tests.
- [ ] `llm_calls` accumulates rows with cost for every real call.
- [ ] Killing MaaS mid-call → backoff retry → eventual clean error.
- [ ] Over-budget calls return 503; admin-flagged jobs still run.

## Open questions for the user
- **Monthly budget per installer** — $20? $100? $500? Recommend $50 for typical
  use; bumpable per-install via `.env`.
- **MaaS endpoint URL** — confirm the literal URL so I can put it in
  `.env.example` as the default value.
- **Enable Llama-Guard-3-1B safety classifier by default?** Recommend off in
  Phase 1 (added complexity), on if the team wants the extra defense layer.
  Decision lives in step 29.

## Risks
- "OpenAI-compatible" varies. We commit to the lowest common denominator
  (chat + embeddings, no function calling, no provider-specific structured
  outputs). Provider extras behind feature flags only.
- Token counting differs across providers. Budget enforcement accepts ~5% slop.
