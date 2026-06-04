"""Topic normalization and auto-approval (plan 15, updated).

LLM-extracted ``topics`` come as free text. Each candidate is:

  1. Noise-filtered — terms whose normalized name contains any substring from
     ``topic_noise_blocklist`` (settings-configurable) are dropped silently.
     This removes logistics entries (registration, networking, lunch, etc.)
     that appear on every conference page but carry no semantic signal.

  2. Matched against the existing ``app.topics`` vocabulary. Already-active
     topics flow through unchanged. Existing-but-pending topics skip until
     they are deactivated or cleared manually.

  3. Auto-approved — new topics that pass the noise filter are inserted
     directly as ``is_active=True, pending_review=False``. No human queue.

The pipeline calls :func:`normalize_topics` and gets back
``(canonical_names, newly_added_names, matched_topic_rows)``.
"""

from __future__ import annotations

import unicodedata

import structlog
from slugify import slugify
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.entities import Topic
from app.settings import get_settings

log = structlog.get_logger("scout.extraction.topics")


def _normalize_key(s: str) -> str:
    """Case-insensitive, accent-stripped match key."""
    s = unicodedata.normalize("NFKD", s)
    s = "".join(ch for ch in s if not unicodedata.combining(ch))
    return s.strip().lower()


def _is_noise(name: str, blocklist: list[str]) -> bool:
    """Return True if this topic should be silently dropped.

    Checks:
    - Too short (≤ 2 chars after normalization)
    - Too long (> 80 chars — probably a sentence fragment, not a topic)
    - Contains any blocklist substring (case-insensitive normalized match)
    """
    key = _normalize_key(name)
    if len(key) <= 2 or len(name) > 80:
        return True
    return any(_normalize_key(term) in key for term in blocklist)


async def normalize_topics(
    db: AsyncSession, candidates: list[str]
) -> tuple[list[str], list[str], list[Topic]]:
    """Match free-text topics to ``app.topics``, auto-approving new ones.

    Returns ``(canonical_names, newly_added_names, matched_topic_rows)``:
      * ``canonical_names`` — names to store in ``conferences.topics``.
      * ``newly_added_names`` — names that were inserted as active topics
        (passed the noise filter and weren't in the vocabulary yet).
      * ``matched_topic_rows`` — active Topic ORM rows; the pipeline uses
        these to insert ``conference_topics`` junction rows.
    """
    if not candidates:
        return [], [], []

    blocklist = get_settings().topic_noise_blocklist

    # Single-pass index of existing topics by every name + alias key.
    result = await db.execute(select(Topic))
    by_key: dict[str, Topic] = {}
    for t in result.scalars():
        by_key[_normalize_key(t.name)] = t
        for alias in t.aliases or []:
            by_key[_normalize_key(alias)] = t

    canonical: list[str] = []
    newly_added: list[str] = []
    matched: list[Topic] = []
    seen_keys: set[str] = set()

    for raw in candidates:
        key = _normalize_key(raw)
        if not key or key in seen_keys:
            continue
        seen_keys.add(key)

        # Drop logistics / noise terms.
        if _is_noise(raw, blocklist):
            log.debug("extraction.topics.noise_dropped", name=raw)
            continue

        existing = by_key.get(key)
        if existing is not None:
            if existing.is_active:
                canonical.append(existing.name)
                matched.append(existing)
            # pending-but-existing: leave it; operator can deactivate via UI.
            continue

        # New topic — auto-approve directly.
        new_topic = Topic(
            name=raw[:60],
            slug=slugify(raw, max_length=80, lowercase=True),
            aliases=[],
            is_active=True,
            pending_review=False,
        )
        db.add(new_topic)
        canonical.append(new_topic.name)
        matched.append(new_topic)
        newly_added.append(new_topic.name)
        by_key[key] = new_topic

    if newly_added:
        log.info("extraction.topics.auto_approved", names=newly_added)

    return canonical, newly_added, matched
