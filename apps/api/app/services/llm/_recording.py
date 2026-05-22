"""Persist each LLM call to ``app.llm_calls`` and enforce the monthly budget.

The recording happens in the same async session the caller passes in;
the LLMClient doesn't own a session. This keeps the LLM layer flushable in
the caller's transaction so a call + downstream DB write commit atomically.
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from uuid import uuid4

import structlog
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.ops import LLMCall
from app.services.llm.models import BudgetExceeded

log = structlog.get_logger("scout.llm.recording")


async def month_to_date_spend(db: AsyncSession) -> float:
    """Sum cost_usd over llm_calls.created_at in the current calendar month (UTC)."""
    now = datetime.now(tz=timezone.utc)
    month_start = datetime(now.year, now.month, 1, tzinfo=timezone.utc)
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
