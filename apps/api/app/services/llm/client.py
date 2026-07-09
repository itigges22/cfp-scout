"""LLMClient — single entry point for chat + embeddings.

Same client talks to the configured LLM endpoint for both. Switch providers
by changing 3 env vars (LLM_BASE_URL, LLM_API_KEY, LLM_CHAT_MODEL). No code
changes.

Every call:
  1. Resolves the model (per-purpose override -> default).
  2. Checks the monthly budget (raises BudgetExceeded on over).
  3. Acquires rate-limit slots (request + tokens).
  4. Calls the LLM via the openai SDK (or returns a dry-run fake).
  5. Computes cost from costs.py.
  6. Records the call to app.llm_calls.
  7. Returns a typed response.

Streaming chat returns an async iterator instead of a ChatResponse;
plan 22 (agent chat) is the only caller that uses it.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import AsyncIterator
from typing import Any
from uuid import uuid4

import structlog
from openai import AsyncOpenAI
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.llm import dry_run
from app.services.llm._recording import check_budget, record_call


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
        from app.db.session import get_session_factory

        async with get_session_factory()() as err_db:
            await record_call(err_db, **kwargs)
            await err_db.commit()
    except Exception as rec_exc:  # noqa: BLE001
        log.warning("llm.record_failure_failed", error=str(rec_exc))
from app.services.llm.costs import compute_cost
from app.services.llm.models import (
    ChatMessage,
    ChatRequest,
    ChatResponse,
    EmbeddingRequest,
    EmbeddingResponse,
)
from app.services.llm.rate_limit import acquire_request_slot, acquire_tokens
from app.services.llm.retries import get_retry
from app.settings import Settings, get_settings

log = structlog.get_logger("scout.llm.client")


# Process-wide concurrency cap on outbound LLM calls. Without this, a
# bulk rescore (recompute_all_matches → 500+ tasks) or the in-process
# scheduler firing multiple jobs at once fans out to dozens of parallel
# LLM requests and trips the provider's rate limit (429), causing every
# job to back off + retry simultaneously (thundering herd).
#
# Bound is set lazily from Settings.llm_max_concurrent_calls the first
# time _gate() is called. Default 3 — safe under the typical RPM budget;
# operators can bump it via /settings/tunables if they have a higher
# quota.
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


class LLMClient:
    """Singleton-friendly LLM client. Get one via :func:`get_llm_client`."""

    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()
        self._openai = AsyncOpenAI(
            base_url=_normalize_openai_base_url(self._settings.llm_base_url),
            api_key=self._settings.llm_api_key.get_secret_value(),
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
        if embed_key is not None:
            self._embed_openai = AsyncOpenAI(
                base_url=_normalize_openai_base_url(
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
            fake = dry_run.fake_chat(req)
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

    async def stream_chat(
        self,
        req: ChatRequest,
        *,
        db: AsyncSession,
        force: bool = False,
    ) -> AsyncIterator[str]:
        """Streaming chat. Yields content deltas as they arrive.

        Used only by the agent chat endpoint (plan 22). Recording happens
        once at the end with the accumulated totals.
        """
        if self._settings.llm_dry_run:
            fake = dry_run.fake_chat(req)
            await record_call(
                db,
                model=fake.model,
                purpose=req.purpose,
                prompt_tokens=fake.prompt_tokens,
                completion_tokens=fake.completion_tokens,
                cost_usd=fake.cost_usd,
                latency_ms=fake.latency_ms,
                request_id=fake.request_id,
                error=None,
            )
            # Chunk the fake content into a few pieces so the SSE flow on the
            # client is exercised.
            for chunk in _chunks(fake.content, 50):
                yield chunk
            return

        model = self._resolve_chat_model(req)
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
        accumulated = ""
        prompt_tokens = estimated_input_tokens
        completion_tokens = 0
        request_id: str | None = None
        try:
            stream_kwargs: dict[str, Any] = {}
            if getattr(self._settings, "llm_disable_thinking", False):
                # Same reasoning-channel guard as _call_chat: without it a
                # Qwen3-style model streams thinking (not content) until the
                # budget dies and the UI renders an empty reply.
                stream_kwargs["extra_body"] = {
                    "chat_template_kwargs": {"enable_thinking": False}
                }
            stream = await self._openai.chat.completions.create(
                model=model,
                messages=[m.model_dump() for m in req.messages],
                temperature=req.temperature,
                max_tokens=req.max_tokens,
                stream=True,
                stream_options={"include_usage": True},
                **stream_kwargs,
            )
            async for chunk in stream:
                if chunk.choices and chunk.choices[0].delta.content:
                    delta = chunk.choices[0].delta.content
                    accumulated += delta
                    yield delta
                if chunk.usage:
                    prompt_tokens = chunk.usage.prompt_tokens
                    completion_tokens = chunk.usage.completion_tokens
                if not request_id:
                    request_id = getattr(chunk, "id", None)
        except Exception as exc:
            elapsed_ms = int((time.perf_counter() - started) * 1000)
            await _record_failure_isolated(
                model=model,
                purpose=req.purpose,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                cost_usd=0.0,
                latency_ms=elapsed_ms,
                request_id=request_id,
                error=f"{type(exc).__name__}: {exc}",
            )
            raise

        elapsed_ms = int((time.perf_counter() - started) * 1000)
        cost = compute_cost(model, prompt_tokens, completion_tokens)
        await record_call(
            db,
            model=model,
            purpose=req.purpose,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            cost_usd=cost,
            latency_ms=elapsed_ms,
            request_id=request_id,
            error=None,
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
            fake = dry_run.fake_embed(req)
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
        if req.purpose.startswith("rationale") or req.purpose.startswith("narrative"):
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


# ---------------------------------------------------------------------------
# Singleton getter
# ---------------------------------------------------------------------------
_instance: LLMClient | None = None
_instance_settings_fingerprint: tuple | None = None

# OpenAI client appends its own endpoint suffix (/chat/completions,
# /embeddings, /models, /completions). Operators occasionally paste a
# URL that already ends in one of those — produces a doubled path
# like '.../v1/embeddings/embeddings'. Strip trailing endpoint
# suffixes so either form works.
_OPENAI_ENDPOINT_SUFFIXES = (
    "/chat/completions",
    "/completions",
    "/embeddings",
    "/models",
)


def _normalize_openai_base_url(url: str) -> str:
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


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _estimate_tokens(text: str) -> int:
    """Rough char-based estimate for pre-call budget math."""
    return max(1, len(text) // 4)


def _chunks(text: str, size: int) -> list[str]:
    return [text[i : i + size] for i in range(0, len(text), size)]


# Convenience: instantiating ChatMessage from plain dicts in callers
ChatMessage
