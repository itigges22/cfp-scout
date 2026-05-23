"""LLMClient — single entry point for chat + embeddings.

Same client talks to the LLM API for both. Switch providers by changing 3 env vars
(LLM_BASE_URL, LLM_API_KEY, LLM_CHAT_MODEL). No code changes.

Every call:
  1. Resolves the model (per-purpose override -> default).
  2. Checks the monthly budget (raises BudgetExceeded on over).
  3. Acquires rate-limit slots (request + tokens).
  4. Calls LLM API via the openai SDK (or returns a dry-run fake).
  5. Computes cost from costs.py.
  6. Records the call to app.llm_calls.
  7. Returns a typed response.

Streaming chat returns an async iterator instead of a ChatResponse;
plan 22 (agent chat) is the only caller that uses it.
"""

from __future__ import annotations

import time
from collections.abc import AsyncIterator
from typing import Any
from uuid import uuid4

import structlog
from openai import AsyncOpenAI
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.llm import dry_run
from app.services.llm._recording import check_budget, record_call
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


class LLMClient:
    """Singleton-friendly LLM client. Get one via :func:`get_llm_client`."""

    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()
        self._openai = AsyncOpenAI(
            base_url=_normalize_openai_base_url(self._settings.llm_base_url),
            api_key=self._settings.llm_api_key.get_secret_value(),
            # Default timeout. Long enough for slow LLM API responses; short
            # enough that hung connections don't tie up workers forever.
            timeout=120.0,
        )
        # Optional dedicated embedding client. your LLM endpoint (and others)
        # often issue per-model keys, so the chat-model key can't access
        # the embedding model. When ``llm_embedding_api_key`` is set we
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
            await record_call(
                db,
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
            stream = await self._openai.chat.completions.create(
                model=model,
                messages=[m.model_dump() for m in req.messages],
                temperature=req.temperature,
                max_tokens=req.max_tokens,
                stream=True,
                stream_options={"include_usage": True},
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
            await record_call(
                db,
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
            await record_call(
                db,
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
        """Make the actual LLM API call with retries."""
        retry = get_retry()
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
                return await self._openai.chat.completions.create(**kwargs)
        raise RuntimeError("unreachable")  # tenacity reraise prevents this

    async def _call_embed(self, model: str, req: EmbeddingRequest) -> Any:
        retry = get_retry()
        async for attempt in retry:
            with attempt:
                # Use the dedicated embedding client when configured.
                # Per-model LLM keys (<vendor> + others) require this.
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
