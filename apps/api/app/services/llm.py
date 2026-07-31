"""The one way this app talks to a language model.

WHAT THIS DOES
    Chat and embeddings through a single client, with everything a call
    needs wrapped around it: a token-bucket throttle before it goes, a
    retry policy around it, a price lookup and monthly budget check, and a
    ledger row per call. Plus a dry-run mode that returns deterministic
    fake answers so the whole pipeline can be exercised without a key.

HOW IT CONNECTS
    Called by   services/matcher, services/extraction.py, services/agent.py,
                services/embeddings.py, services/positioning.py,
                services/positioning.py, services/people.py, services/diagnostics.py
    Writes      app.llm_calls
    Tuning      LLM_* settings, LLM_PRICES_JSON

WORTH KNOWING
    Every one of these pieces existed only to serve the client three lines
    away, and none had a consumer outside the package. ``dry_run`` and
    ``client`` even defined the same ``_estimate_tokens`` twice, character
    for character.

    The API key is never read from config — it is entered from the UI
    after deployment and stored as a setting override.

    Recording happens on the caller's session, so a successful call and
    the write it feeds commit together; a rollback discards both. That is
    why FAILURE records go to a separate, committed session.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import time
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, Literal
from uuid import uuid4

import structlog
from openai import APIConnectionError, APITimeoutError, AsyncOpenAI, RateLimitError
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from tenacity import (
    AsyncRetrying,
    before_sleep_log,
    retry_if_exception_type,
    stop_after_attempt,
    wait_random_exponential,
)

from app.db.models import LLMCall
from app.db.session import get_session_factory
from app.settings import Settings, get_settings

log = structlog.get_logger("scout.llm")


# ==========================================================================
# models.py
# ==========================================================================


class ChatMessage(BaseModel):
    """One turn in a chat completion call."""

    role: Literal["system", "user", "assistant", "tool"]
    content: str


class ChatRequest(BaseModel):
    """Inputs to LLMClient.chat. Provider-agnostic on purpose; the client
    translates this to the OpenAI-compatible wire format."""

    model_config = ConfigDict(extra="forbid")

    messages: list[ChatMessage]
    purpose: str = Field(
        ...,
        description="Tag for cost-tracking (e.g. 'extract_conference', 'rationale').",
    )
    model: str | None = None
    temperature: float = 0.2
    max_tokens: int | None = None
    response_format: dict[str, Any] | None = None  # e.g. {"type": "json_object"}
    stream: bool = False


class ChatResponse(BaseModel):
    """What LLMClient.chat returns. Streaming responses produce a
    different shape (an async iterator) and are not represented here."""

    content: str
    model: str
    prompt_tokens: int
    completion_tokens: int
    cost_usd: float
    latency_ms: int
    request_id: str
    raw: dict[str, Any] | None = None


class EmbeddingRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    texts: list[str]
    purpose: str
    model: str | None = None


class EmbeddingResponse(BaseModel):
    """A flat aligned list of vectors (same order as inputs)."""

    vectors: list[list[float]]
    model: str
    prompt_tokens: int
    cost_usd: float
    latency_ms: int


class BudgetExceeded(Exception):
    """Raised when a non-forced call would push monthly spend past the cap.

    The api route layer maps this to HTTP 503 with a problem+json body that
    tells the user to bump LLM_MONTHLY_BUDGET_USD or wait until next month.
    """

    def __init__(self, *, month_spend: float, budget: float):
        super().__init__(
            f"Month-to-date LLM spend ${month_spend:.2f} would exceed "
            f"the configured budget ${budget:.2f}."
        )
        self.month_spend = month_spend
        self.budget = budget


# ==========================================================================
# throttle.py
# ==========================================================================


_stdlib_log = logging.getLogger("scout.llm.throttle")


class TokenBucket:
    """Simple async token bucket: a refilling pool of `capacity` units."""

    def __init__(self, *, capacity: float, refill_per_second: float):
        self._capacity = capacity
        self._tokens = capacity
        self._refill_per_second = refill_per_second
        self._last_refill = time.monotonic()
        self._lock = asyncio.Lock()

    async def acquire(self, cost: float = 1.0) -> None:
        """Wait until ``cost`` tokens are available, then consume them.

        Two things here are load-bearing and were both wrong before.

        **The sleep happens outside the lock.** Holding it while sleeping
        turns a throttle into a queue: every other caller blocks for the
        full wait of whoever got there first, so one slow reservation
        serialises the whole process.

        **A cost above capacity cannot be waited for.** ``_refill`` caps the
        pool at ``capacity``, so ``tokens >= cost`` is unreachable and the
        old loop span forever — while holding the lock, which wedged every
        chat and embedding call in the process until the pod restarted. One
        oversized document was enough. Such a request now drains what is
        there and proceeds, loudly: the bucket is an advisory pre-call
        estimate (see the module docstring), and letting one call through
        under-throttled is strictly better than never returning.
        """
        while True:
            async with self._lock:
                self._refill()
                if self._tokens >= cost:
                    self._tokens -= cost
                    return
                if cost > self._capacity:
                    # Unsatisfiable by construction. Take what exists and go.
                    log.warning(
                        "rate_limit.cost_exceeds_capacity",
                        cost=cost,
                        capacity=self._capacity,
                        hint=(
                            "one request asked for more than the whole budget "
                            "window; the caller should split the batch"
                        ),
                    )
                    self._tokens = 0.0
                    return
                shortfall = cost - self._tokens
                wait_s = shortfall / max(self._refill_per_second, 0.01)
            log.debug("rate_limit.wait", wait_s=wait_s, shortfall=shortfall)
            await asyncio.sleep(wait_s)

    def _refill(self) -> None:
        now = time.monotonic()
        delta = now - self._last_refill
        self._tokens = min(self._capacity, self._tokens + delta * self._refill_per_second)
        self._last_refill = now


_REQUESTS_BUCKET = TokenBucket(capacity=20, refill_per_second=10)  # 10 rps sustained, 20 burst


_TOKENS_BUCKET = TokenBucket(capacity=100_000, refill_per_second=2000)  # ~120k tokens/min


async def acquire_request_slot() -> None:
    await _REQUESTS_BUCKET.acquire(1.0)


async def acquire_tokens(estimated_tokens: int) -> None:
    """Reserve token budget BEFORE the call. We use the prompt size as
    an estimate; the actual consumption may differ but the bucket recovers."""
    await _TOKENS_BUCKET.acquire(float(estimated_tokens))




WAIT = wait_random_exponential(multiplier=1, min=1, max=30)


RETRYABLE_TYPES = (
    APIConnectionError,
    APITimeoutError,
    RateLimitError,
    # InternalServerError lives in openai.InternalServerError but inheritance
    # chains differ across versions; the generic APIError covers 5xx too.
)


def get_retry() -> AsyncRetrying:
    """Create a fresh AsyncRetrying configured per the policy above."""
    return AsyncRetrying(
        stop=stop_after_attempt(get_settings().llm_max_attempts),
        wait=WAIT,
        retry=retry_if_exception_type(RETRYABLE_TYPES),
        before_sleep=before_sleep_log(_stdlib_log, logging.WARNING),
        reraise=True,
    )


# ==========================================================================
# spend.py
# ==========================================================================


@dataclass(frozen=True)
class Price:
    """USD per million tokens, input + output."""

    input_per_million: float
    output_per_million: float


_DEFAULT_PRICES: dict[str, Price] = {
    # --- currently configured models -------------------------------------
    # These must stay in step with LLM_CHAT_MODEL / LLM_EMBEDDING_MODEL. An
    # unpriced model records $0.00, which silently disables the monthly
    # budget guardrail — it can never reach a cap it cannot measure.
    # tests/unit/test_spend.py asserts the active defaults are priced.
    "Qwen3.6-35B-A3B": Price(0.60, 0.60),
    "Nomic-embed-text-v2-moe": Price(0.02, 0.00),  # embeddings are input-only
    # --- other open-weight models, example prices ------------------------
    "deepseek-r1-distill-qwen-14b": Price(0.80, 0.80),
    "openai/deepseek-r1-distill-qwen-14b": Price(0.80, 0.80),
    "qwen3-14b": Price(0.80, 0.80),
    "llama-scout-17b": Price(1.07, 1.07),
    "codellama-7b-instruct": Price(0.40, 0.40),
    "microsoft-phi-4": Price(0.00, 0.00),
    "nomic-embed-text-v1-5": Price(0.02, 0.00),
}


def _load_overrides() -> dict[str, Price]:
    """Parse LLM_PRICES_JSON if set. Format: ``{"model-name": {"input": 0.5, "output": 0.5}}``."""
    raw = os.environ.get("LLM_PRICES_JSON")
    if not raw:
        return {}
    try:
        data = json.loads(raw)
        return {name: Price(float(p["input"]), float(p["output"])) for name, p in data.items()}
    except (json.JSONDecodeError, KeyError, ValueError, TypeError) as exc:
        log.warning("llm_prices_json.invalid", error=str(exc))
        return {}


_PRICES: dict[str, Price] = {**_DEFAULT_PRICES, **_load_overrides()}


def compute_cost(model: str, prompt_tokens: int, completion_tokens: int) -> float:
    """Return cost in USD for a single call. Unknown model → 0.0 with a warn log."""
    price = _PRICES.get(model)
    if price is None:
        log.warning("llm.cost.unknown_model", model=model)
        return 0.0
    return (
        prompt_tokens * price.input_per_million / 1_000_000
        + completion_tokens * price.output_per_million / 1_000_000
    )


async def month_to_date_spend(db: AsyncSession) -> float:
    """Sum cost_usd over llm_calls.created_at in the current calendar month (UTC)."""
    now = datetime.now(tz=UTC)
    month_start = datetime(now.year, now.month, 1, tzinfo=UTC)
    result = await db.execute(
        select(func.coalesce(func.sum(LLMCall.cost_usd), 0)).where(
            LLMCall.created_at >= month_start
        )
    )
    return float(result.scalar_one() or 0.0)


async def check_budget(db: AsyncSession, *, planned_cost: float, budget_usd: float | None) -> None:
    """Raise ``BudgetExceeded`` if `(month-to-date + planned_cost)` exceeds the budget.

    Pass ``budget_usd=None`` to disable the check (the ``LLM_MONTHLY_BUDGET_USD``
    env var being unset means "unlimited"; we warn at startup if it is).
    """
    if budget_usd is None:
        return
    spent = await month_to_date_spend(db)
    if spent + planned_cost > budget_usd:
        raise BudgetExceeded(month_spend=spent + planned_cost, budget=budget_usd)


async def record_call(
    db: AsyncSession,
    *,
    model: str,
    purpose: str,
    prompt_tokens: int,
    completion_tokens: int,
    cost_usd: float,
    latency_ms: int,
    request_id: str | None,
    error: str | None,
) -> None:
    """Append a row to ``app.llm_calls``. Caller commits the surrounding transaction."""
    db.add(
        LLMCall(
            model=model,
            purpose=purpose,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            cost_usd=Decimal(f"{cost_usd:.6f}"),
            latency_ms=latency_ms,
            request_id=request_id or str(uuid4()),
            error=error,
        )
    )
    log.debug(
        "llm.recorded",
        model=model,
        purpose=purpose,
        cost_usd=cost_usd,
        latency_ms=latency_ms,
    )


# ==========================================================================
# py
# ==========================================================================


DRY_RUN_DIM = 768


def fake_chat(req: ChatRequest) -> ChatResponse:
    """Deterministic chat response. Echoes a short summary + a request id.

    Extraction needs valid JSON output even in dry-run, so the
    ``extract:conference`` purpose dispatches to a canned JSON envelope
    derived from the page text fingerprint. Real LLM calls require
    LLM_DRY_RUN=false.
    """
    fingerprint = _hash_messages(req.messages)
    if req.purpose == "extract:conference":
        content = _canned_extract_conference(req, fingerprint)
    elif req.purpose == "extract:talk":
        content = _canned_extract_talk(req, fingerprint)
    elif req.purpose == "rationale:match":
        content = _canned_match_rationale(req, fingerprint)
    elif req.purpose == "agent_chat":
        content = _canned_agent_chat(req, fingerprint)
    else:
        content = (
            f"[dry-run] chat response for purpose={req.purpose!r}, "
            f"fingerprint={fingerprint[:10]}. "
            "Real LLM calls require LLM_DRY_RUN=false and a valid LLM_API_KEY."
        )
    prompt_tokens = sum(_estimate_tokens(m.content) for m in req.messages)
    completion_tokens = _estimate_tokens(content)
    return ChatResponse(
        content=content,
        model=req.model or "dry-run",
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        cost_usd=0.0,
        latency_ms=1,
        request_id=str(uuid.uuid4()),
    )


def _canned_agent_chat(req: ChatRequest, fingerprint: str) -> str:
    """Deterministic agent-chat reply in dry-run mode.

    Extracts the user's question + counts the [n] snippets in the user
    prompt so the canned reply cites real indices. Echoes the question
    + a non-committal answer + citation marks per surviving snippet (max 3
    cited). Honors the "say I don't know" rule when there are no snippets.
    """
    user_msg = next((m.content for m in req.messages if m.role == "user"), "")
    # Pull the original question line.
    question = ""
    for line in user_msg.splitlines():
        if line.startswith("User question:"):
            question = line.split(":", 1)[1].strip()
            break
    # Count how many [n] snippets the prompt actually included.
    import re as _re

    indices = sorted({int(m.group(1)) for m in _re.finditer(r"^\[(\d{1,3})\]\s", user_msg, _re.M)})
    if not indices:
        return (
            "[dry-run] I don't have that information in Scout's data. "
            "(Real answers land when LLM_DRY_RUN=false.)"
        )
    citation_marks = " ".join(f"[{i}]" for i in indices[:3])
    q_preview = (question[:140] + "…") if len(question) > 140 else question
    return (
        f"[dry-run agent reply] Looking at the available context, here's what "
        f"Scout sees for your question {q_preview!r}: the retrieved snippets "
        f"cover the relevant entities {citation_marks}. (Real responses with "
        f"reasoned citations land when LLM_DRY_RUN=false; fingerprint {fingerprint[:8]}.)"
    )


def _canned_match_rationale(req: ChatRequest, fingerprint: str) -> str:
    """Deterministic rationale text in dry-run mode.

    Echoes a couple of facts from the prompt so a human reading the dry-run
    output can verify the pipeline wired the right snippets, without needing
    a real LLM.
    """
    # Peek at the user message for the conference name and pillar mention so
    # the canned text feels grounded.
    user_msg = next((m.content for m in req.messages if m.role == "user"), "")
    conf_name = "the conference"
    for line in user_msg.splitlines():
        if line.startswith("Conference:"):
            conf_name = line.split(":", 1)[1].strip()
            break
    return (
        f"[dry-run rationale] {conf_name} aligns with the product's messaging "
        f"based on the supplied evidence snippets (fingerprint {fingerprint[:8]}). "
        "Recommended SMEs come from topic + audience overlap. "
        "Real LLM rationale lands when LLM_DRY_RUN=false."
    )


def _canned_extract_conference(req: ChatRequest, fingerprint: str) -> str:
    """Deterministic ExtractedConference JSON in dry-run mode.

    Derives a fake but plausible conference name from the page-text hash so
    different pages produce different rows downstream (drives dedupe and
    routing without needing a real LLM). Year is fixed to next year so the
    same-year dedup logic still gets exercised.
    """
    # 16-char hex slug from the fingerprint — different pages, different
    # conferences.
    slug = fingerprint[:16]
    payload = {
        "name": f"Dry-Run Conference {slug.upper()}",
        "start_date": "2027-04-15",
        "end_date": "2027-04-17",
        "location_city": "Boston",
        "location_country": "US",
        "is_virtual": False,
        "venue": "Hynes Convention Center",
        "website": None,
        "cfp_open_at": "2026-09-01",
        "cfp_close_at": "2026-12-15",
        "cfp_deadlines": [
            {
                "kind": "submission",
                "deadline_date": "2026-12-15",
                "description": "Main track papers",
                "applies_to": "talks",
            }
        ],
        "cfp_topics_of_interest": ["large language models", "RAG", "inference"],
        "topics": ["llm", "inference", "rag"],
        "acceptance_rate_percent": 22,
        "estimated_cost_usd": 1200,
        "confidence": 0.78,
    }
    return json.dumps(payload)


def _canned_extract_talk(req: ChatRequest, fingerprint: str) -> str:
    """Deterministic talk extraction for extract:talk purpose in dry-run mode.

    Returns a valid ExtractedTalk JSON envelope derived from the fingerprint
    so different texts produce different titles without a real LLM.
    """
    slug = fingerprint[:12]
    payload = {
        "title": f"[dry-run] Talk {slug.upper()}",
        "abstract": (
            "This is a dry-run abstract. The talk explores key concepts in "
            "cloud-native infrastructure and developer productivity. "
            "Real extraction lands when LLM_DRY_RUN=false."
        ),
        "key_themes": ["cloud-native", "developer experience", "automation"],
        "suggested_topics": ["Kubernetes", "CI/CD", "DevOps"],
        "suggested_pillar_name": None,
        "target_audience_description": "Platform engineers and SREs",
        "suggested_duration_minutes": 30,
        "talk_format": "talk",
    }
    return json.dumps(payload)


def fake_embed(req: EmbeddingRequest) -> EmbeddingResponse:
    """Deterministic embeddings. Each input text maps to the same vector
    every time, derived from sha256(text) seeded into a normal-ish distribution."""
    vectors = [_text_to_vector(t) for t in req.texts]
    prompt_tokens = sum(_estimate_tokens(t) for t in req.texts)
    return EmbeddingResponse(
        vectors=vectors,
        model=req.model or "dry-run",
        prompt_tokens=prompt_tokens,
        cost_usd=0.0,
        latency_ms=1,
    )


def _hash_messages(messages: list) -> str:
    blob = json.dumps([m.model_dump() for m in messages], sort_keys=True)
    return hashlib.sha256(blob.encode()).hexdigest()


def _text_to_vector(text: str) -> list[float]:
    """Deterministic 768-dim vector. Same text → same vector across calls."""
    digest = hashlib.sha256(text.encode("utf-8")).digest()
    # Stretch the 32-byte digest into 768 floats by repeating + sliding.
    raw = (digest * ((DRY_RUN_DIM // len(digest)) + 1))[:DRY_RUN_DIM]
    # Map bytes 0..255 to roughly [-1, 1] for sensible cosine behavior.
    return [(b / 127.5) - 1.0 for b in raw]


_ = time


# ==========================================================================
# client.py
# ==========================================================================


async def _record_failure_isolated(**kwargs: Any) -> None:
    """Record a failed LLM call on a DEDICATED session.

    Error paths used to record on the caller's session — but a failing
    task rolls that session back, taking the error row with it. The
    diagnostics panel then shows nothing while jobs die (exactly how the
    matcher's ContextWindowExceededError stayed invisible). A separate
    committed session survives the caller's rollback. Best-effort: a
    recording failure must never mask the original exception.
    """
    try:

        async with get_session_factory()() as err_db:
            await record_call(err_db, **kwargs)
            await err_db.commit()
    except Exception as rec_exc:
        log.warning("llm.record_failure_failed", error=str(rec_exc))


_llm_call_sem: asyncio.Semaphore | None = None


_llm_call_sem_size: int | None = None


def _gate() -> asyncio.Semaphore:
    """Lazy + settings-aware semaphore. Rebuilds when the cap setting
    changes (e.g. operator bumped from 3 → 8 in /settings/tunables)."""
    global _llm_call_sem, _llm_call_sem_size
    desired = max(1, get_settings().llm_max_concurrent_calls)
    if _llm_call_sem is None or _llm_call_sem_size != desired:
        _llm_call_sem = asyncio.Semaphore(desired)
        _llm_call_sem_size = desired
    return _llm_call_sem


class LLMNotConfiguredError(RuntimeError):
    """No API key has been entered yet.

    Distinct from an authentication failure. The key is entered through
    Settings after deployment rather than baked into cluster config, so
    "not configured yet" is an ordinary first-day state — and it should say
    so, not surface as a 401 from the provider that reads like an outage.
    """


class LLMClient:
    """Singleton-friendly LLM client. Get one via :func:`get_llm_client`."""

    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()
        # Placeholder when no key is configured yet. The OpenAI SDK raises
        # from its CONSTRUCTOR on missing credentials, which crashed the
        # request before chat()/embed()'s llm_is_configured() gate could
        # return its clean "enter a key in Settings" error — surfacing to
        # the operator as a bare 502 from the oauth proxy. The placeholder
        # never reaches the wire: the gate raises first on every real call.
        _key = (
            self._settings.llm_api_key.get_secret_value()
            if _has_secret(self._settings.llm_api_key)
            else "not-configured"
        )
        self._openai = AsyncOpenAI(
            base_url=normalize_openai_base_url(self._settings.llm_base_url),
            api_key=_key,
            # Default timeout. Long enough for slow LLM responses; short
            # enough that hung connections don't tie up workers forever.
            timeout=120.0,
        )
        # Optional dedicated embedding client. Many LLM providers issue
        # per-model keys, so the chat-model key can't access the
        # embedding model. When ``llm_embedding_api_key`` is set we
        # build a separate AsyncOpenAI for embedding calls; otherwise
        # embeddings reuse the chat client.
        embed_key = getattr(self._settings, "llm_embedding_api_key", None)
        embed_base = getattr(self._settings, "llm_embedding_base_url", "") or ""
        # Truthiness, not `is not None`. Clearing the optional field in the
        # settings UI stores "", which is not None — so the old check built
        # a client with a BLANK api key and every embedding call failed
        # authentication upstream, instead of falling back to the chat key
        # as the operator intended.
        if _has_secret(embed_key):
            self._embed_openai = AsyncOpenAI(
                base_url=normalize_openai_base_url(
                    embed_base or self._settings.llm_base_url
                ),
                api_key=(
                    embed_key.get_secret_value()
                    if hasattr(embed_key, "get_secret_value")
                    else str(embed_key)
                ),
                timeout=120.0,
            )
        else:
            self._embed_openai = self._openai

    # ------------------------------------------------------------------
    # Chat
    # ------------------------------------------------------------------
    async def chat(
        self,
        req: ChatRequest,
        *,
        db: AsyncSession,
        force: bool = False,
    ) -> ChatResponse:
        """Single-shot chat completion.

        Args:
            req: the request body.
            db: an open AsyncSession (caller commits).
            force: skip the monthly-budget check. Reserved for admin jobs.

        Returns:
            A ChatResponse with token counts + cost + the assistant content.

        Raises:
            BudgetExceeded: if non-forced and over-budget.
            openai.APIError + subclasses: on unrecoverable upstream errors.
        """
        model = self._resolve_chat_model(req)
        purpose = req.purpose

        # Dry-run path skips network + budget. Useful for tests/demos.
        if self._settings.llm_dry_run:
            fake = fake_chat(req)
            await record_call(
                db,
                model=fake.model,
                purpose=purpose,
                prompt_tokens=fake.prompt_tokens,
                completion_tokens=fake.completion_tokens,
                cost_usd=fake.cost_usd,
                latency_ms=fake.latency_ms,
                request_id=fake.request_id,
                error=None,
            )
            return fake

        # Real call. Budget guard uses a coarse pre-estimate (input tokens
        # only; we don't know the completion length yet). Worst case the
        # next call catches us going over.
        if not self._settings.llm_dry_run and not self._settings.llm_is_configured():
            raise LLMNotConfiguredError(
                "No LLM API key is set. Enter one in Settings, or turn on "
                "LLM_DRY_RUN to work offline against canned responses."
            )
        estimated_input_tokens = sum(_estimate_tokens(m.content) for m in req.messages)
        estimated_cost = compute_cost(model, estimated_input_tokens, 0)
        if not force:
            await check_budget(
                db,
                planned_cost=estimated_cost,
                budget_usd=self._settings.llm_monthly_budget_usd,
            )

        await acquire_request_slot()
        await acquire_tokens(estimated_input_tokens)

        started = time.perf_counter()
        request_id: str | None = None
        try:
            response = await self._call_chat(model, req)
        except Exception as exc:
            elapsed_ms = int((time.perf_counter() - started) * 1000)
            await _record_failure_isolated(
                model=model,
                purpose=purpose,
                prompt_tokens=estimated_input_tokens,
                completion_tokens=0,
                cost_usd=0.0,
                latency_ms=elapsed_ms,
                request_id=None,
                error=f"{type(exc).__name__}: {exc}",
            )
            raise

        elapsed_ms = int((time.perf_counter() - started) * 1000)
        usage = response.usage
        prompt_tokens = usage.prompt_tokens if usage else estimated_input_tokens
        completion_tokens = usage.completion_tokens if usage else 0
        cost = compute_cost(model, prompt_tokens, completion_tokens)
        choice = response.choices[0]
        request_id = getattr(response, "id", None)
        content = choice.message.content or ""
        if not content.strip() and choice.finish_reason == "length":
            # Reasoning models (Qwen3 et al.) stream their thinking into a
            # separate channel; when max_tokens is exhausted mid-think, the
            # answer channel comes back EMPTY and the caller sees a silent
            # no-op (this is how "Ask Scout returns nothing" presented).
            # llm_disable_thinking (default on) prevents this — surface it
            # loudly in case an operator turned that off.
            log.warning(
                "llm.chat.empty_content_reasoning_truncated",
                model=model,
                purpose=purpose,
                completion_tokens=completion_tokens,
                hint="model spent the whole max_tokens budget on reasoning; "
                "enable llm_disable_thinking or raise max_tokens",
            )

        await record_call(
            db,
            model=model,
            purpose=purpose,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            cost_usd=cost,
            latency_ms=elapsed_ms,
            request_id=request_id,
            error=None,
        )

        return ChatResponse(
            content=content,
            model=model,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            cost_usd=cost,
            latency_ms=elapsed_ms,
            request_id=request_id or str(uuid4()),
            raw=None,
        )


    # ------------------------------------------------------------------
    # Embeddings
    # ------------------------------------------------------------------
    async def embed(
        self,
        req: EmbeddingRequest,
        *,
        db: AsyncSession,
        force: bool = False,
    ) -> EmbeddingResponse:
        model = req.model or self._settings.llm_embedding_model

        # Hard guard against the embedding model's serving context window
        # (Nomic-embed-text-v2-moe on LiteMaaS caps at 512 tokens). The
        # chunking pipeline already sizes its chunks, but ad-hoc QUERY
        # embeds — matcher stages, agent retrieval — pass raw text
        # straight through and a long enriched description 400s the whole
        # task. Truncation is the only option under a hard cap, and for
        # similarity queries the head of the text carries the signal.
        max_chars = int(getattr(self._settings, "embed_chunk_max_chars", 1400))
        if any(len(t) > max_chars for t in req.texts):
            n_over = sum(1 for t in req.texts if len(t) > max_chars)
            log.warning(
                "llm.embed.texts_truncated",
                n_texts=len(req.texts),
                n_truncated=n_over,
                max_chars=max_chars,
                purpose=req.purpose,
            )
            req = req.model_copy(
                update={"texts": [t[:max_chars] for t in req.texts]}
            )

        if self._settings.llm_dry_run:
            fake = fake_embed(req)
            await record_call(
                db,
                model=fake.model,
                purpose=req.purpose,
                prompt_tokens=fake.prompt_tokens,
                completion_tokens=0,
                cost_usd=fake.cost_usd,
                latency_ms=fake.latency_ms,
                request_id=None,
                error=None,
            )
            return fake

        if not self._settings.llm_dry_run and not self._settings.llm_is_configured():
            raise LLMNotConfiguredError(
                "No LLM API key is set. Enter one in Settings, or turn on "
                "LLM_DRY_RUN to work offline against canned responses."
            )
        estimated_tokens = sum(_estimate_tokens(t) for t in req.texts)
        estimated_cost = compute_cost(model, estimated_tokens, 0)
        if not force:
            await check_budget(
                db,
                planned_cost=estimated_cost,
                budget_usd=self._settings.llm_monthly_budget_usd,
            )
        await acquire_request_slot()
        await acquire_tokens(estimated_tokens)

        started = time.perf_counter()
        try:
            response = await self._call_embed(model, req)
        except Exception as exc:
            elapsed_ms = int((time.perf_counter() - started) * 1000)
            await _record_failure_isolated(
                model=model,
                purpose=req.purpose,
                prompt_tokens=estimated_tokens,
                completion_tokens=0,
                cost_usd=0.0,
                latency_ms=elapsed_ms,
                request_id=None,
                error=f"{type(exc).__name__}: {exc}",
            )
            raise

        elapsed_ms = int((time.perf_counter() - started) * 1000)
        usage = response.usage
        prompt_tokens = usage.prompt_tokens if usage else estimated_tokens
        cost = compute_cost(model, prompt_tokens, 0)
        vectors = [item.embedding for item in response.data]
        await record_call(
            db,
            model=model,
            purpose=req.purpose,
            prompt_tokens=prompt_tokens,
            completion_tokens=0,
            cost_usd=cost,
            latency_ms=elapsed_ms,
            request_id=None,
            error=None,
        )
        return EmbeddingResponse(
            vectors=vectors,
            model=model,
            prompt_tokens=prompt_tokens,
            cost_usd=cost,
            latency_ms=elapsed_ms,
        )

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------
    def _resolve_chat_model(self, req: ChatRequest) -> str:
        """Per-call override > Settings.model_for(req.purpose) > default."""
        if req.model:
            return req.model
        # Best-effort purpose mapping: 'extract' / 'extract_*' use extraction model, etc.
        if req.purpose.startswith("extract"):
            return self._settings.model_for("extraction")
        # "narrative" was a second purpose routed here; the SME-narrative
        # feature and its only caller are gone, so rationale is the whole set.
        if req.purpose.startswith("rationale"):
            return self._settings.model_for("narrative")
        if req.purpose.startswith("agent"):
            return self._settings.model_for("agent")
        return self._settings.llm_chat_model

    async def _call_chat(self, model: str, req: ChatRequest) -> Any:
        """Make the actual LLM call with retries.

        Gated by the process-wide semaphore so a bulk rescore can't fan
        out to dozens of parallel LLM calls and trip the rate limit.
        """
        retry = get_retry()
        async with _gate():
            async for attempt in retry:
                with attempt:
                    kwargs: dict[str, Any] = {
                        "model": model,
                        "messages": [m.model_dump() for m in req.messages],
                        "temperature": req.temperature,
                    }
                    if req.max_tokens is not None:
                        kwargs["max_tokens"] = req.max_tokens
                    if req.response_format is not None:
                        kwargs["response_format"] = req.response_format
                    if getattr(self._settings, "llm_disable_thinking", False):
                        # Reasoning models (Qwen3 family) otherwise burn the
                        # max_tokens budget on their thinking channel and can
                        # return an EMPTY answer. vLLM honours this via the
                        # chat template; LiteLLM forwards it. Backends that
                        # don't know the kwarg simply ignore it.
                        kwargs["extra_body"] = {
                            "chat_template_kwargs": {"enable_thinking": False}
                        }
                    return await self._openai.chat.completions.create(**kwargs)
        raise RuntimeError("unreachable")  # tenacity reraise prevents this

    async def _call_embed(self, model: str, req: EmbeddingRequest) -> Any:
        retry = get_retry()
        async with _gate():
            async for attempt in retry:
                with attempt:
                    # Use the dedicated embedding client when configured.
                    # Many providers require per-model keys for embeddings.
                    return await self._embed_openai.embeddings.create(
                        model=model,
                        input=req.texts,
                    )
        raise RuntimeError("unreachable")


_instance: LLMClient | None = None


_instance_settings_fingerprint: tuple | None = None


_OPENAI_ENDPOINT_SUFFIXES = (
    "/chat/completions",
    "/completions",
    "/embeddings",
    "/models",
)


def _has_secret(value: object) -> bool:
    """True when an optional credential is actually set.

    Pydantic SecretStr, a plain string, or None — all three reach here, and
    an empty one of any of them means "not configured".
    """
    if value is None:
        return False
    raw = value.get_secret_value() if hasattr(value, "get_secret_value") else str(value)
    return bool(raw.strip())


def normalize_openai_base_url(url: str) -> str:
    """Strip trailing slashes + known OpenAI endpoint suffixes."""
    if not url:
        return url
    u = url.rstrip("/")
    for suffix in _OPENAI_ENDPOINT_SUFFIXES:
        if u.lower().endswith(suffix):
            u = u[: -len(suffix)]
            u = u.rstrip("/")
            break
    return u


def _settings_fingerprint(s: Settings) -> tuple:
    """Cheap snapshot of the settings the client depends on. If any of
    these changed since the singleton was built, the singleton is stale.

    Model names and the budget cap are included because the client reads
    them from its captured ``self._settings`` snapshot on every call —
    without them here, a model swap via /admin/settings (or the periodic
    DB-overrides refresh) would keep hitting the old model until restart.
    """
    return (
        s.llm_base_url,
        s.llm_api_key.get_secret_value() if s.llm_api_key else "",
        s.llm_dry_run,
        getattr(s, "llm_embedding_base_url", "") or "",
        (
            s.llm_embedding_api_key.get_secret_value()
            if getattr(s, "llm_embedding_api_key", None) is not None
            else ""
        ),
        s.llm_chat_model,
        s.llm_embedding_model,
        s.llm_extraction_model,
        s.llm_narrative_model,
        s.llm_agent_model,
        s.llm_monthly_budget_usd,
        getattr(s, "llm_disable_thinking", False),
    )


def get_llm_client() -> LLMClient:
    """Return the process-wide LLMClient singleton, creating it on first call.

    Rebuilds the singleton if the relevant settings have changed since
    the last call — required because ``/admin/settings`` PATCHes can
    flip ``llm_dry_run``, swap ``llm_api_key``, or add an
    ``llm_embedding_api_key`` at runtime, and a stale client snapshot
    would silently keep using the old values.
    """
    global _instance, _instance_settings_fingerprint
    settings = get_settings()
    fingerprint = _settings_fingerprint(settings)
    if _instance is None or _instance_settings_fingerprint != fingerprint:
        log.info(
            "llm.client.rebuilt",
            reason="initial" if _instance is None else "settings_changed",
            dry_run=settings.llm_dry_run,
            embed_key_set=bool(getattr(settings, "llm_embedding_api_key", None)),
        )
        _instance = LLMClient(settings)
        _instance_settings_fingerprint = fingerprint
    return _instance


def _estimate_tokens(text: str) -> int:
    """Rough char-based estimate for pre-call budget math."""
    return max(1, len(text) // 4)


ChatMessage
