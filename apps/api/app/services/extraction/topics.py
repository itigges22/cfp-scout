"""Topic normalization (plan 15).

LLM-extracted ``topics`` come as free text. We match each item against the
controlled ``app.topics`` vocabulary (case-insensitive, accent-stripped,
matched against ``name`` + ``aliases``). Matched topics flow through to
``conferences.topics`` as the canonical name; unmatched ones get inserted
with ``pending_review=true, is_active=false`` so they don't influence
matching until an admin promotes them in ``/settings/topics`` (plan 09).

The pipeline calls :func:`normalize_topics` with the LLM's free-text list
and gets back ``(canonical_names_for_storage, newly_pending_topic_names)``.
"""

from __future__ import annotations

import unicodedata

import structlog
from slugify import slugify
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.entities import Topic

log = structlog.get_logger("scout.extraction.topics")


def _normalize_key(s: str) -> str:
    """Case-insensitive, accent-stripped match key.

    Mirrors Postgres' ``lower(unaccent(...))`` so future plans can move the
    match into SQL with confidence the keys agree.
    """
    s = unicodedata.normalize("NFKD", s)
    s = "".join(ch for ch in s if not unicodedata.combining(ch))
    return s.strip().lower()


async def normalize_topics(
    db: AsyncSession, candidates: list[str]
) -> tuple[list[str], list[str]]:
    """Match free-text topics to ``app.topics``.

    Returns ``(canonical_names, newly_pending_names)``:
      * ``canonical_names`` — the list to store in ``conferences.topics``;
        deduplicated, lower-cased canonical Topic names (preserves order).
      * ``newly_pending_names`` — the subset that didn't match anything
        and were inserted into ``app.topics`` with ``pending_review=true``.
    """
    if not candidates:
        return [], []

    # Single-pass index of existing topics by every name + alias key.
    result = await db.execute(select(Topic))
    by_key: dict[str, Topic] = {}
    for t in result.scalars():
        by_key[_normalize_key(t.name)] = t
        for alias in t.aliases or []:
            by_key[_normalize_key(alias)] = t

    canonical: list[str] = []
    pending_new: list[str] = []
    seen_keys: set[str] = set()

    for raw in candidates:
        key = _normalize_key(raw)
        if not key or key in seen_keys:
            continue
        seen_keys.add(key)

        match = by_key.get(key)
        if match is not None:
            if match.is_active:
                canonical.append(match.name)
            # pending-but-existing matches: don't surface yet; admin needs to
            # approve them first.
            continue

        # Not seen before — insert as pending-review.
        new_topic = Topic(
            name=raw[:60],
            slug=slugify(raw, max_length=80, lowercase=True),
            aliases=[],
            is_active=False,
            pending_review=True,
        )
        db.add(new_topic)
        pending_new.append(new_topic.name)
        # Cache in the local map so subsequent candidates with the same key
        # hit the in-flight insert instead of duplicating.
        by_key[key] = new_topic

    if pending_new:
        log.info("extraction.topics.pending_inserted", names=pending_new)

    return canonical, pending_new
