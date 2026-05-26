"""LLM-driven enrichment of conference text for the matcher's embedder.

Conferences imported via the bulk JSON feed arrive with just a name + a
handful of topic tags + a location. That's 14 words median per row —
nowhere near enough semantic content for the matcher's cosine similarity
to surface alignment with 200-word product messaging documents.

This module asks the LLM to expand each conference into a factual 2-3
sentence "what this event is likely about" description grounded in
common AI/ML/dev vocabulary. The result is stored on
``Conference.enriched_description`` and the embedder uses it in place
of (or alongside) the raw name+topics blob.

Cost: ~150 input + ~80 output tokens per conference. At chat-model
pricing this is well under $1 for a full 583-conference backfill.

Idempotency: the helper is a pure function of (name, topics, location).
The backfill skips rows that already have a non-null
``enriched_description`` unless ``force=True``.
"""

from __future__ import annotations

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.llm import ChatMessage, ChatRequest, get_llm_client

log = structlog.get_logger("scout.enrichment")

PROMPT_VERSION = "conference.enrichment.v1"

_SYSTEM_PROMPT = """\
You expand a tech/AI conference's name + topics + location into a 2–3
sentence factual description of what the event is about, in plain
neutral English.

Rules (non-negotiable):
- Use specific technical vocabulary when the name signals it. Examples:
  "vLLM Meetup" → mention vLLM (the open-source LLM inference engine),
  distributed LLM serving, GPU inference, llm-d if the name mentions it.
  "Kubeflow Day" → Kubernetes-native machine learning, MLOps, model
  training pipelines.
  "PyTorch Conference" → the PyTorch deep learning framework, model
  training, fine-tuning, the broader PyTorch ecosystem.
  "DevOpsDays Prague" → DevOps practices, CI/CD, platform engineering,
  cloud-native deployment.
  "AgentCamp" → agentic AI, agent frameworks, MCP, tool use.
  "RAG Day" → retrieval-augmented generation, vector databases,
  embeddings, document chunking.
- If the name is generic ("Tech Summit 2026"), describe it as a broad
  software engineering / developer event without inventing specifics.
- NEVER invent specific speakers, dates, attendee counts, sponsors, or
  award winners. Stick to "likely covers" / "typically focuses on".
- NEVER use marketing language (no "premier", "world-class", "leading",
  "cutting-edge", "revolutionary").
- DO use common AI/ML technical terms when relevant: LLMs, inference,
  fine-tuning, RAG, embeddings, vector databases, MLOps, observability,
  agentic AI, tool use, MCP, model serving, Kubernetes, hybrid cloud,
  open source AI, training pipelines.
- Length: 2–3 sentences, ~50–100 words total.

Output: just the description text. No preamble, no quotes, no
"This conference is about…" — start with a noun phrase like
"A community meetup on…" or "An annual conference covering…".
"""


def _build_user_prompt(*, name: str, topics: list[str], country: str | None, city: str | None, is_virtual: bool) -> str:
    location_parts: list[str] = []
    if is_virtual:
        location_parts.append("Virtual")
    elif city or country:
        location_parts.append(", ".join(p for p in (city, country) if p))
    location = location_parts[0] if location_parts else "Location TBD"
    topic_str = ", ".join(topics) if topics else "(no topics tagged)"
    return (
        f"Conference name: {name}\n"
        f"Topics: {topic_str}\n"
        f"Location: {location}\n\n"
        "Write the 2-3 sentence description now."
    )


async def enrich_conference(
    *,
    db: AsyncSession,
    name: str,
    topics: list[str],
    country: str | None = None,
    city: str | None = None,
    is_virtual: bool = False,
) -> str | None:
    """Generate a factual 2-3 sentence description for a conference.

    Returns None on LLM failure — caller can leave the row's
    ``enriched_description`` NULL and the matcher will fall back to the
    bare name+topics text. We don't raise so a single bad row doesn't
    poison a bulk backfill.
    """
    user_prompt = _build_user_prompt(
        name=name,
        topics=topics or [],
        country=country,
        city=city,
        is_virtual=is_virtual,
    )
    req = ChatRequest(
        messages=[
            ChatMessage(role="system", content=_SYSTEM_PROMPT),
            ChatMessage(role="user", content=user_prompt),
        ],
        purpose="enrich:conference",
        temperature=0.2,
        max_tokens=180,
    )
    try:
        resp = await get_llm_client().chat(req, db=db)
    except Exception as exc:  # noqa: BLE001 — non-fatal
        log.warning(
            "enrichment.llm_failed",
            name=name[:60],
            error=str(exc)[:200],
        )
        return None
    text = (resp.content or "").strip()
    if not text:
        return None
    # Sanity bound: anything over 600 chars is the LLM rambling.
    if len(text) > 600:
        text = text[:600].rsplit(".", 1)[0] + "."
    return text
