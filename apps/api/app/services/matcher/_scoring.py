"""Shared scoring helpers (plan 17).

Cosine similarity is what every stage falls back to. pgvector gives us
``cosine_distance`` (1 - cosine_similarity); the helpers below convert to
similarity and aggregate the top-K.

Kept tiny — these are pure functions over numbers, easy to test independently
of the DB / LLM.
"""

from __future__ import annotations

from collections.abc import Iterable


def clamp01(x: float) -> float:
    """Clamp to [0, 1]. Plan 17 explicitly requires this on every score
    before persistence so a single bad cosine can't escape downstream."""
    if x < 0.0:
        return 0.0
    if x > 1.0:
        return 1.0
    return x


def topk_mean(similarities: Iterable[float], k: int) -> float:
    """Mean of the top-K similarities. Returns 0 if the iterable is empty."""
    values = sorted((float(s) for s in similarities), reverse=True)[:k]
    if not values:
        return 0.0
    return sum(values) / len(values)


def topk_max(similarities: Iterable[float]) -> float:
    """Single max — used for pillar alignment where the per-pillar max wins."""
    values = list(similarities)
    if not values:
        return 0.0
    return float(max(values))


def cosine_from_distance(distance: float) -> float:
    """pgvector returns cosine DISTANCE = 1 - cosine_similarity.

    Bounded to [0, 1] — cosine_similarity is in [-1, 1] but our embeddings
    (nomic-embed-text-v1-5) are normalized so negative similarities are
    rare; we treat them as 0.
    """
    return clamp01(1.0 - float(distance))


def apply_chunk_decay(raw_similarity: float, chunk) -> float:
    """Multiply a raw chunk-similarity by the chunk's freshness when decay
    is enabled (plan 25). Gated by ``settings.decay_enabled``.

    ``chunk`` is expected to be a ``DocumentChunk`` row or any object with
    ``created_at`` and ``last_used_at`` attributes. Freshness uses the
    more-recent of the two as the reference time (a chunk that's been
    retrieved recently stays fresh even if it was created long ago).
    """
    # Lazy import to avoid a circular ref through app.services.lifecycle.
    from app.services.lifecycle import (
        CHUNK_HALF_LIFE_DAYS,
        apply_decay_multiplier,
        compute_freshness,
    )
    from app.settings import get_settings

    if not get_settings().decay_enabled:
        return clamp01(raw_similarity)
    last_used = getattr(chunk, "last_used_at", None)
    created = getattr(chunk, "created_at", None)
    reference = max(last_used, created) if last_used and created else last_used or created
    freshness = compute_freshness(
        reference_time=reference,
        half_life_days=CHUNK_HALF_LIFE_DAYS,
    )
    return apply_decay_multiplier(raw_similarity, freshness)
