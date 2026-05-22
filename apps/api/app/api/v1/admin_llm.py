"""/api/v1/admin/llm — small endpoints to exercise and inspect the LLM layer.

Single-user, no auth (per ADR-0001), but logged as ``admin.*`` events so any
out-of-band call is easy to spot in the logs. Real callers (the matcher,
embedder, agent chat) use the LLMClient directly; these endpoints exist for
manual testing + the ``/diagnostics`` LLM panel (plan 26 will swap in a
richer aggregator).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import structlog
from fastapi import APIRouter, HTTPException, status
from sqlalchemy import func, select

from app.db.models.ops import LLMCall
from app.db.session import DbSession
from app.services.llm import (
    BudgetExceeded,
    ChatMessage,
    ChatRequest,
    EmbeddingRequest,
    get_llm_client,
)

log = structlog.get_logger("scout.api.admin_llm")

router = APIRouter(prefix="/api/v1/admin/llm", tags=["admin.llm"])


@router.post("/test-chat")
async def test_chat(db: DbSession, prompt: str, purpose: str = "admin_test") -> dict:
    """Round-trip a chat call. With ``LLM_DRY_RUN=true`` returns a canned response."""
    log.info("admin.llm.test_chat", purpose=purpose, prompt_chars=len(prompt))
    try:
        resp = await get_llm_client().chat(
            ChatRequest(
                messages=[ChatMessage(role="user", content=prompt)],
                purpose=purpose,
            ),
            db=db,
        )
    except BudgetExceeded as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        ) from exc
    await db.commit()
    return resp.model_dump(mode="json")


@router.post("/test-embed")
async def test_embed(db: DbSession, text: str, purpose: str = "admin_test") -> dict:
    """Round-trip an embedding call. Returns the dimension + first few values
    so the response stays small."""
    log.info("admin.llm.test_embed", purpose=purpose, text_chars=len(text))
    try:
        resp = await get_llm_client().embed(
            EmbeddingRequest(texts=[text], purpose=purpose),
            db=db,
        )
    except BudgetExceeded as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        ) from exc
    await db.commit()
    vec = resp.vectors[0]
    return {
        "model": resp.model,
        "dimension": len(vec),
        "preview": vec[:5],
        "prompt_tokens": resp.prompt_tokens,
        "cost_usd": resp.cost_usd,
        "latency_ms": resp.latency_ms,
    }


@router.get("/stats")
async def stats(db: DbSession) -> dict:
    """Month-to-date + last-24h LLM usage summary.

    Plan 26 (/diagnostics) will surface this in a real UI; for now it's
    a JSON aggregator for ad-hoc inspection.
    """
    now = datetime.now(tz=UTC)
    month_start = datetime(now.year, now.month, 1, tzinfo=UTC)
    day_start = now - timedelta(hours=24)

    async def _sum(since: datetime) -> dict:
        result = await db.execute(
            select(
                func.count(LLMCall.id),
                func.coalesce(func.sum(LLMCall.cost_usd), 0),
                func.coalesce(func.sum(LLMCall.prompt_tokens + LLMCall.completion_tokens), 0),
            ).where(LLMCall.created_at >= since)
        )
        row = result.one()
        return {
            "calls": int(row[0]),
            "cost_usd": float(row[1]),
            "tokens": int(row[2]),
        }

    # Group purposes for the month
    by_purpose_q = await db.execute(
        select(
            LLMCall.purpose,
            func.count(LLMCall.id),
            func.coalesce(func.sum(LLMCall.cost_usd), 0),
        )
        .where(LLMCall.created_at >= month_start)
        .group_by(LLMCall.purpose)
        .order_by(func.sum(LLMCall.cost_usd).desc())
    )
    by_purpose = [
        {"purpose": row[0], "calls": int(row[1]), "cost_usd": float(row[2])}
        for row in by_purpose_q.all()
    ]

    return {
        "month_to_date": await _sum(month_start),
        "last_24h": await _sum(day_start),
        "by_purpose_mtd": by_purpose,
    }
