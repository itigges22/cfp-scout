"""Lexical (keyword-overlap) co-signal for the matcher.

Why this exists: ``nomic-embed-text-v1-5`` cosines on
short-form-vs-long-form text saturate in a narrow band (typical p95
~0.05 in this corpus), so the embedding alone can't separate
"PyTorch Conference" (matches our LLM messaging) from "AWS Community
Day Bulgaria" (doesn't). Concrete words like ``vLLM``, ``llm-d``,
``MLOps`` and ``Kubernetes`` are far more discriminative than their
sentence-vector embeddings.

Approach (deliberately simple, no extra dependency):

1. Pull every active messaging chunk and extract a vocabulary of
   distinctive 1- and 2-token terms (tech jargon, product names,
   methodology names). A short, hand-curated stoplist drops generic
   English so we don't credit conferences for words like "the" or
   "platform".
2. For each conference, count weighted hits against that vocabulary
   in its name + enriched description + topics.
3. Normalize against a saturation point so a handful of strong hits
   maxes out at 1.0.

This file is intentionally framework-free (just stdlib + sqlalchemy)
so it can be unit-tested in isolation.
"""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.entities import Conference, MessagingDocument
from app.db.models.vectors import DocumentChunk

log = structlog.get_logger("scout.matcher.lexical")

# Above this many active messaging chunks, swap the curated lexical
# scorer for proper BM25 (rank_bm25). Below it, IDF statistics are
# too noisy to be useful and the hand-tuned weights here win.
_BM25_THRESHOLD_DOCS = 30

# Word characters + hyphen so "llm-d" / "fine-tuning" stay as one token.
_TOKEN_RE = re.compile(r"[a-z][a-z0-9-]{1,}")

# Generic English + generic business/tech words that would otherwise
# get picked up as "keywords" and hand free credit to every conference.
# Kept short on purpose; auto-IDF would over-engineer this.
_STOPWORDS: frozenset[str] = frozenset(
    {
        "the", "and", "for", "with", "that", "from", "this", "into",
        "their", "they", "have", "will", "are", "any", "all", "but",
        "not", "out", "use", "uses", "used", "using", "via", "such",
        "your", "you", "our", "its", "more", "most", "other", "than",
        "also", "across", "across", "than", "able", "based", "over",
        # Generic biz/tech words that aren't discriminative
        "platform", "product", "products", "solution", "solutions",
        "enterprise", "enterprises", "business", "businesses", "team",
        "teams", "users", "user", "data", "service", "services",
        "system", "systems", "software", "hardware", "company",
        "organization", "organizations", "community", "developer",
        "developers", "engineer", "engineers", "professional",
        "professionals", "world", "global", "annual", "event",
        "events", "conference", "conferences", "summit", "summits",
        "meetup", "meetups", "day", "days", "week", "year", "years",
        "open", "source", "free", "online", "virtual", "in-person",
        "topic", "topics", "covering", "cover", "covers", "focus",
        "focused", "focusing", "focuses", "likely", "include",
        "includes", "including", "discussion", "discussions",
        "technology", "technologies", "tech", "ecosystem", "tools",
        "tool", "best", "practice", "practices", "knowledge",
        "experience", "experiences", "share", "sharing", "share",
        "approach", "approaches", "method", "methods", "topic",
        "various", "broad", "broader", "field", "fields", "industry",
        "industries", "applications", "application", "application",
        "implementation", "implementations", "development",
        "ai", "artificial", "intelligence",  # too generic — every conf has these
        "new", "key", "core", "main", "primary", "general", "specific",
        "first", "second", "third", "fourth", "fifth",
        "real", "real-time", "real-world", "real-life",
        "session", "sessions", "track", "tracks", "talk", "talks",
        "workshop", "workshops", "presentation", "presentations",
        "speaker", "speakers", "attendee", "attendees", "audience",
        "audiences", "participant", "participants",
        "research", "researcher", "researchers", "advance",
        "advances", "advanced", "advancements",
    }
)

# Bonus weight for terms we know are highly discriminative when
# they appear (multi-word tech names, specific product names,
# narrow methodologies). The base weight is 1.0 — these get extra.
#
# Important: this list contains only vendor-neutral open-source projects
# and methodology names. Vendor-specific product names (anything you'd
# call by a company's brand) belong in the operator's messaging-document
# corpus, not in this file — the lexical scorer already auto-extracts
# vocabulary from the active messaging chunks, so vendor terms an
# operator uses in their own messaging will still light up (at the
# generic 1.0 weight). Keeping this list vendor-neutral means the code
# stays portable across organizations.
_HIGH_VALUE_TERMS: dict[str, float] = {
    "vllm": 3.0,
    "llm-d": 3.0,
    "kubeflow": 2.5,
    "kubernetes": 2.0,
    "mlops": 2.5,
    "rag": 2.0,
    "retrieval-augmented": 2.5,
    "agentic": 2.5,
    "mcp": 2.0,
    "fine-tuning": 2.0,
    "inference": 2.0,
    "embedding": 2.0,
    "embeddings": 2.0,
    "llm": 1.5,
    "llms": 1.5,
    "gpu": 2.0,
    "pytorch": 2.5,
    "tensorflow": 2.0,
    "langchain": 2.0,
    "ollama": 2.0,
    "hugging": 1.5,
    "huggingface": 2.5,
    "raft": 2.0,
    "jupyterlab": 2.0,
    "jupyter": 1.5,
    "linux": 1.0,
    "ci/cd": 1.5,
    "devops": 1.5,
    "observability": 2.0,
    "edge": 1.5,
    "hybrid": 1.5,
    "cloud-native": 2.0,
    "serverless": 1.5,
    "fastapi": 2.0,
    "pgvector": 2.5,
    "postgres": 1.5,
    "postgresql": 1.5,
    "react": 1.5,
    "python": 1.0,
    "vector": 1.5,
    "transformer": 2.0,
    "transformers": 2.0,
    "model": 1.0,
    "models": 1.0,
    "training": 1.0,
    "deployment": 1.0,
    "serving": 1.5,
    "fine": 0.5,  # only matters as part of "fine-tuning"
    "tuning": 1.0,
    "rag,": 2.0,  # tolerant of comma-adjacency
}

# Minimum length so we don't pick up "a", "is", "in" as keywords even
# though the stoplist already filters most of them.
_MIN_TOKEN_LEN = 3

# Where we cap the weighted hit sum. Picked empirically so a conference
# with ~4-5 high-value matches (e.g. "vLLM, inference, MLOps") plus
# some generic credit lands near 1.0, while a conference with no
# high-value matches and only generic English overlap caps out around
# 0.2-0.3. Operators can tune via settings later if needed.
_SATURATION = 12.0

# Per-match credit for generic-vocabulary overlap (any messaging-corpus
# word that's not in _HIGH_VALUE_TERMS), and the total cap for that
# bucket so a conference can't max-out on generic word soup alone.
_GENERIC_PER_MATCH = 0.10
_GENERIC_CAP = 2.5


@dataclass(frozen=True)
class LexicalContext:
    """Pre-computed vocabulary from the active messaging chunks. Pass to
    :func:`lexical_score` for each conference we want to score."""

    vocabulary: frozenset[str]


def _tokenize(text: str) -> list[str]:
    """Lowercase + tokenize on word boundaries, preserving hyphenated
    compounds (``fine-tuning``, ``llm-d``)."""
    return _TOKEN_RE.findall(text.lower())


def _interesting(token: str) -> bool:
    if len(token) < _MIN_TOKEN_LEN:
        return False
    if token in _STOPWORDS:
        return False
    if token.isdigit():
        return False
    return True


async def build_context(db: AsyncSession) -> LexicalContext:
    """Build the vocabulary from active messaging chunks.

    Cheap enough to call per-rescore-batch (one query, a few KB of text,
    set operations). We deliberately don't cache at module level —
    operator messaging-doc edits via the admin UI must take effect on
    the next score run, not on the next process restart.

    When the corpus grows past ``_BM25_THRESHOLD_DOCS`` documents, a
    proper BM25 implementation (e.g. ``rank_bm25`` package) starts to
    have enough document-frequency statistics to beat this hand-tuned
    scorer — log a one-time recommendation so future-you knows when
    to revisit the design choice. Below the threshold, IDF is
    statistically noisy and the curated weights here win.
    """
    rows = (
        await db.execute(
            select(DocumentChunk.text)
            .join(
                MessagingDocument,
                MessagingDocument.id == DocumentChunk.owner_id,
            )
            .where(
                DocumentChunk.owner_type == "messaging",
                MessagingDocument.is_active.is_(True),
            )
        )
    ).scalars().all()
    if len(rows) > _BM25_THRESHOLD_DOCS:
        log.info(
            "lexical.corpus_size_threshold_exceeded",
            n_messaging_docs=len(rows),
            recommendation=(
                f"Messaging corpus has grown past {_BM25_THRESHOLD_DOCS} chunks — "
                "consider switching from the curated lexical scorer to proper "
                "BM25 (rank_bm25). The custom scorer's hand-tuned weights are "
                "tuned for small corpora; BM25's IDF statistics become "
                "meaningful at this scale."
            ),
        )
    vocab: set[str] = set()
    for text in rows:
        for token in _tokenize(text):
            if _interesting(token):
                vocab.add(token)
    return LexicalContext(vocabulary=frozenset(vocab))


def lexical_score(*, conference: Conference, ctx: LexicalContext) -> float:
    """Score how heavily a conference uses the messaging corpus's
    *distinctive* vocabulary, on [0, 1].

    Two paths add to the total:
      - High-value curated terms (vLLM, MLOps, Kubeflow, …) contribute
        their explicit weight when both the conference text uses them
        AND they're present in the messaging corpus.
      - Generic vocabulary overlap (other tokens in both corpora)
        contributes a small fixed weight per match, capped so generic
        word soup can't dominate.

    Combines the conference name, enriched description, and topic tags
    into one bag, then weights each matched term once (type-level, not
    token-level, so a single repeated word doesn't dominate)."""
    parts: list[str] = [conference.name or ""]
    if conference.enriched_description:
        parts.append(conference.enriched_description)
    if conference.topics:
        parts.append(" ".join(conference.topics))
    if conference.cfp_topics_of_interest:
        parts.append(" ".join(conference.cfp_topics_of_interest))
    bag = _tokenize(" ".join(parts))
    if not bag:
        return 0.0
    # Set, not Counter — type-level matching only.
    types: set[str] = {t for t in bag if _interesting(t)}
    high_value_total = 0.0
    generic_match_count = 0
    for token in types:
        if token not in ctx.vocabulary:
            continue
        if token in _HIGH_VALUE_TERMS:
            high_value_total += _HIGH_VALUE_TERMS[token]
        else:
            generic_match_count += 1
    # Cap generic credit so a conference with 50 random English nouns
    # can't max out without any technical vocabulary.
    generic_contribution = min(_GENERIC_CAP, generic_match_count * _GENERIC_PER_MATCH)
    total = high_value_total + generic_contribution
    return min(1.0, total / _SATURATION)


__all__ = ["LexicalContext", "build_context", "lexical_score"]
