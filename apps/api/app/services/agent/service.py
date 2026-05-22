"""Single-turn agent orchestrator (plan 22).

Flow:
  1. Persist the user's :class:`ChatMessage`.
  2. Pull the recent N turns from this session (oldest first) for context.
  3. Retrieve numbered snippets via :func:`retrieve_for_question`.
  4. Build the user prompt and call the LLM (purpose=``agent_chat``).
  5. Parse the assistant's ``[n]`` citation marks back to source rows.
  6. Persist the assistant :class:`ChatMessage` with citations in
     ``metadata_json``.
  7. Return a typed :class:`AgentReply`.

This is sync-response (not SSE) — pass 2 will add streaming. Per-process
concurrency cap is enforced via :data:`_inflight_sem` so a runaway page
can't blow the LLM budget faster than the per-call accounting can react.
"""

from __future__ import annotations

import asyncio
import re
from dataclasses import asdict, dataclass, field
from uuid import UUID

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.ops import ChatMessage, ChatSession
from app.services.agent.prompts import (
    PROMPT_VERSION,
    SYSTEM_PROMPT,
    build_user_prompt,
)
from app.services.agent.retrieval import (
    DEFAULT_OWNER_TYPES,
    RetrievedSnippet,
    retrieve_for_question,
)
from app.services.llm import ChatMessage as LLMChatMessage
from app.services.llm import ChatRequest, get_llm_client

log = structlog.get_logger("scout.agent.service")

# How many prior turns to feed back in. Conservative — the corpus is in
# the retrieved snippets; conversation memory is a UX nicety.
HISTORY_TURNS = 6

# Per-process concurrency cap (plan 22 risk: cost burst).
_inflight_sem = asyncio.Semaphore(5)


# ---------------------------------------------------------------------------
# Types
# ---------------------------------------------------------------------------
@dataclass(slots=True, frozen=True)
class Citation:
    """One ``[n]`` mark in the assistant's reply, resolved back to its source."""

    index: int
    chunk_id: str
    owner_type: str
    owner_id: str
    label: str
    similarity: float


@dataclass(slots=True)
class AgentReply:
    session_id: str
    user_message_id: str
    assistant_message_id: str
    role: str
    content: str
    citations: list[Citation] = field(default_factory=list)
    prompt_tokens: int = 0
    completion_tokens: int = 0
    cost_usd: float = 0.0
    latency_ms: int | None = None
    prompt_version: str = PROMPT_VERSION

    def to_dict(self) -> dict:
        return {
            **{k: v for k, v in asdict(self).items() if k != "citations"},
            "citations": [asdict(c) for c in self.citations],
        }


# ---------------------------------------------------------------------------
# Entry
# ---------------------------------------------------------------------------
async def ask(
    db: AsyncSession,
    *,
    session_id: UUID,
    user_message: str,
    owner_types: list[str] | None = None,
    k: int = 6,
) -> AgentReply:
    """Run one turn of the agent. Caller commits."""
    if not user_message.strip():
        raise ValueError("user_message must be non-empty")

    session = await db.get(ChatSession, session_id)
    if session is None:
        raise LookupError(f"No chat_session {session_id}")
    if session.archived:
        raise RuntimeError(f"chat_session {session_id} is archived")

    # 1. Persist the user turn.
    user_row = ChatMessage(
        session_id=session.id,
        role="user",
        content=user_message,
        metadata_json={"prompt_version": PROMPT_VERSION},
    )
    db.add(user_row)
    await db.flush()
    await db.refresh(user_row)

    # 2. Recent history (oldest first, exclude the row we just added).
    history = await _recent_history(db, session.id, exclude=user_row.id)

    # 3. Retrieval.
    snippets = await retrieve_for_question(
        db,
        question=user_message,
        owner_types=owner_types or DEFAULT_OWNER_TYPES,
        k=k,
    )

    # 4. LLM call.
    prompt_user = build_user_prompt(
        history=[(m.role, m.content) for m in history],
        question=user_message,
        snippets=[s.text for s in snippets],
    )
    req = ChatRequest(
        messages=[
            LLMChatMessage(role="system", content=SYSTEM_PROMPT),
            LLMChatMessage(role="user", content=prompt_user),
        ],
        purpose="agent_chat",
        temperature=0.2,
        max_tokens=700,
    )

    async with _inflight_sem:
        resp = await get_llm_client().chat(req, db=db)

    # 5. Parse citations.
    citations = _extract_citations(resp.content, snippets)

    # 6. Persist the assistant turn.
    asst_row = ChatMessage(
        session_id=session.id,
        role="assistant",
        content=resp.content,
        metadata_json={
            "prompt_version": PROMPT_VERSION,
            "citations": [asdict(c) for c in citations],
            "n_snippets": len(snippets),
            "prompt_tokens": resp.prompt_tokens,
            "completion_tokens": resp.completion_tokens,
            "cost_usd": float(resp.cost_usd),
            "latency_ms": resp.latency_ms,
        },
    )
    db.add(asst_row)
    await db.flush()
    await db.refresh(asst_row)

    # Auto-title once: if the session has no title yet, snapshot the first
    # 80 chars of the user message.
    if not session.title:
        session.title = user_message.strip()[:80]

    log.info(
        "agent.turn.done",
        session_id=str(session.id),
        n_snippets=len(snippets),
        n_citations=len(citations),
        prompt_tokens=resp.prompt_tokens,
        completion_tokens=resp.completion_tokens,
    )

    return AgentReply(
        session_id=str(session.id),
        user_message_id=str(user_row.id),
        assistant_message_id=str(asst_row.id),
        role="assistant",
        content=resp.content,
        citations=citations,
        prompt_tokens=resp.prompt_tokens,
        completion_tokens=resp.completion_tokens,
        cost_usd=float(resp.cost_usd),
        latency_ms=resp.latency_ms,
    )


# ---------------------------------------------------------------------------
# Internals
# ---------------------------------------------------------------------------
async def _recent_history(
    db: AsyncSession, session_id: UUID, *, exclude: UUID
) -> list[ChatMessage]:
    """Most-recent N turns (oldest first, excluding the just-added user row)."""
    rows = (
        (
            await db.execute(
                select(ChatMessage)
                .where(ChatMessage.session_id == session_id)
                .where(ChatMessage.id != exclude)
                .order_by(ChatMessage.created_at.desc())
                .limit(HISTORY_TURNS)
            )
        )
        .scalars()
        .all()
    )
    rows.reverse()
    return list(rows)


_CITATION_RE = re.compile(r"\[(\d{1,3})\]")


def _extract_citations(text: str, snippets: list[RetrievedSnippet]) -> list[Citation]:
    """Map [n] marks in the assistant's reply back to RetrievedSnippet rows.

    Indices outside the snippet range are dropped silently (model
    hallucinated a citation number); duplicates are surfaced once each.
    """
    if not text or not snippets:
        return []
    by_index = {s.index: s for s in snippets}
    seen: set[int] = set()
    out: list[Citation] = []
    for m in _CITATION_RE.finditer(text):
        idx = int(m.group(1))
        if idx in seen or idx not in by_index:
            continue
        seen.add(idx)
        s = by_index[idx]
        out.append(
            Citation(
                index=s.index,
                chunk_id=s.chunk_id,
                owner_type=s.owner_type,
                owner_id=s.owner_id,
                label=s.label,
                similarity=s.similarity,
            )
        )
    return out
