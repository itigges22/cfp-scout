"""Few-shot calibration examples for the LLM-as-judge.

The judge starts out with a zero-shot prompt that explains the
calibration scale verbally (90-100 = laser-focused match, 0-29 =
off-topic, etc.). That's fine as a baseline but the model has no
way to learn what *this specific operator* considers a good match —
two reasonable orgs might both be "Agentic-AI-focused" and yet
disagree on whether KubeCon belongs in the top 20.

This module pulls the operator's recent approve/reject decisions
from ``app.decisions`` and formats them as concrete in-context
examples that get prepended to the judge prompt. After ~20 decisions,
the judge's calibration aligns to the operator's actual taste
without any LLM fine-tuning.

The research basis is in-context learning / few-shot prompting:
GPT-style models reliably pick up task-specific calibration from
a small number of examples in the prompt. For reranking tasks
specifically, [Sun et al. 2023] (arXiv:2305.14502) showed 4-6
examples is the sweet spot — more adds noise + cost.

Selection strategy: pull the most recent N decisions (capped at
6 examples — 3 approve + 3 reject) so the calibration tracks the
operator's evolving preferences rather than freezing on stale
early decisions.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.entities import Conference
from app.db.models.matching import Decision, Match

log = structlog.get_logger("scout.matcher.calibration")

# How many examples of each kind to surface in the prompt. Six total
# is the sweet spot per the arXiv:2305.14502 finding — more doesn't
# help and starts to bloat the prompt enough to hurt latency.
MAX_APPROVED_EXAMPLES = 3
MAX_REJECTED_EXAMPLES = 3


@dataclass(frozen=True, slots=True)
class CalibrationExample:
    """One few-shot example. ``decision`` is "approved" or "rejected";
    ``conference_name`` + ``enriched_description`` + previous
    ``judge_score`` give the LLM concrete pattern data to learn from."""

    decision: str
    conference_name: str
    enriched_description: str
    judge_score: float | None


@dataclass(frozen=True, slots=True)
class CalibrationContext:
    """Set of examples + a stable hash for cache-key generation. The
    hash captures the example set so that re-judging a conference
    with the SAME examples can be cached, but adding new decisions
    invalidates the cache and forces a fresh judge call."""

    examples: list[CalibrationExample]
    fingerprint: str


async def load_calibration_examples(db: AsyncSession) -> CalibrationContext:
    """Pull recent decisions + format as few-shot examples.

    Returns an empty list of examples on a cold-start install (no
    decisions yet). The judge falls back to its zero-shot prompt in
    that case — no error, just no calibration.
    """
    approved = await _load_kind(db, kind="approved", limit=MAX_APPROVED_EXAMPLES)
    rejected = await _load_kind(db, kind="rejected", limit=MAX_REJECTED_EXAMPLES)
    examples = approved + rejected

    # Fingerprint just the (decision, name, score) tuples — that's
    # enough to detect a meaningful change. Full text isn't needed in
    # the hash because changes to enriched_description on the example
    # conferences are rare and the fingerprint only matters for cache
    # invalidation granularity.
    payload = "|".join(
        f"{e.decision}:{e.conference_name}:{e.judge_score or '-'}"
        for e in examples
    )
    fingerprint = hashlib.sha256(payload.encode("utf-8")).hexdigest()
    log.debug(
        "calibration.loaded",
        n_examples=len(examples),
        n_approved=len(approved),
        n_rejected=len(rejected),
    )
    return CalibrationContext(examples=examples, fingerprint=fingerprint)


async def _load_kind(
    db: AsyncSession, *, kind: str, limit: int
) -> list[CalibrationExample]:
    """Fetch the N most-recent decisions of a given kind, joined with
    the conference + match for context."""
    rows = (
        await db.execute(
            select(
                Decision.decision,
                Conference.name,
                Conference.enriched_description,
                Match.judge_score,
            )
            .join(Conference, Conference.id == Decision.conference_id)
            .outerjoin(Match, Match.conference_id == Conference.id)
            .where(Decision.decision == kind)
            .order_by(Decision.decided_at.desc())
            .limit(limit)
        )
    ).all()
    out: list[CalibrationExample] = []
    for r in rows:
        # Skip examples with no enriched description — they'd give the
        # LLM no usable signal beyond the name.
        if not r.enriched_description:
            continue
        out.append(
            CalibrationExample(
                decision=r.decision,
                conference_name=r.name,
                enriched_description=r.enriched_description,
                judge_score=r.judge_score,
            )
        )
    return out


def format_examples_block(ctx: CalibrationContext) -> str:
    """Render the examples as a prompt fragment. Returns an empty
    string when the example set is empty so the caller can no-op
    the few-shot section gracefully."""
    if not ctx.examples:
        return ""
    lines: list[str] = [
        "PAST DECISIONS BY THIS OPERATOR (use these to calibrate your scoring):",
    ]
    for e in ctx.examples:
        verdict = "APPROVED" if e.decision == "approved" else "REJECTED"
        score_str = (
            f" (your prior judge score: {e.judge_score:.2f})"
            if e.judge_score is not None
            else ""
        )
        # Cap example descriptions at ~250 chars to keep the prompt
        # tight — the score + verdict carry most of the signal.
        snippet = e.enriched_description[:250].rsplit(" ", 1)[0]
        lines.append(f"- {verdict}{score_str}: {e.conference_name} — {snippet}")
    lines.append(
        "\nUse these examples to calibrate: prefer scores that agree with how "
        "the operator decided in similar cases."
    )
    return "\n".join(lines) + "\n\n"


__all__ = [
    "CalibrationContext",
    "CalibrationExample",
    "format_examples_block",
    "load_calibration_examples",
]
