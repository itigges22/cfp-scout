"""Series detector (plan 23).

Two-stage candidate suggester for unlinked conferences:

  1. **Name strip**: pull year + edition markers out of the conference
     name so "NeurIPS 2026" → "NeurIPS", "AAAI 2027 Spring" → "AAAI".
  2. **pg_trgm fuzzy match**: compare the stripped name to every
     ``conference_series.canonical_name`` and each alias via Postgres'
     ``similarity()`` function. Best match above a configurable threshold
     becomes a suggestion.

Returns ranked :class:`SeriesSuggestion` rows. The caller (admin route)
decides whether to commit any of them — there's no auto-link.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass

import structlog
from sqlalchemy import select, text as sql_text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.entities import Conference, ConferenceSeries

log = structlog.get_logger("scout.series.detector")

# Default similarity floor for a suggestion to show up. The plan's UI lets
# admins "bulk approve > 0.95"; ones in [SUGGEST_THRESHOLD, 0.95] still
# show but need manual review.
SUGGEST_THRESHOLD = 0.55

# Optional: ignore conferences in these statuses (no point linking
# something that's already inert).
_INELIGIBLE_STATUSES = {"quarantined", "rejected"}

_YEAR_RE = re.compile(r"\b(19|20)\d{2}\b")
# Edition / season markers we strip alongside years.
_EDITION_RE = re.compile(
    r"\b(spring|summer|fall|autumn|winter|"
    r"vol(?:ume)?\.?\s*\d+|"
    r"edition\s*\d+|"
    r"v\d+(?:\.\d+)?|"
    r"\d+(?:st|nd|rd|th)\s+(?:annual|edition))\b",
    re.IGNORECASE,
)


@dataclass(slots=True, frozen=True)
class SeriesSuggestion:
    """One detector hit."""

    conference_id: str
    conference_name: str
    series_id: str
    canonical_name: str
    matched_via: str        # "canonical" / "alias"
    matched_value: str       # the alias string or the canonical name
    stripped_name: str       # debug — what we compared against
    confidence: float        # 0..1, pg_trgm similarity

    def to_dict(self) -> dict:
        return asdict(self)


def strip_year_and_edition(name: str) -> str:
    """Remove year + edition tokens; collapse whitespace.

    Examples:
      "NeurIPS 2026"                       → "NeurIPS"
      "AAAI 2027 Spring"                   → "AAAI"
      "KubeCon + CloudNativeCon NA 2026"   → "KubeCon + CloudNativeCon NA"
      "ICML 2025: Vol. 42"                 → "ICML:"  (still recognizable)
    """
    s = _YEAR_RE.sub("", name)
    s = _EDITION_RE.sub("", s)
    # Drop standalone hyphens / colons / commas left dangling.
    s = re.sub(r"[\s\-:,]+", " ", s)
    return s.strip()


async def suggest_series_for_unlinked(
    db: AsyncSession,
    *,
    threshold: float = SUGGEST_THRESHOLD,
    limit: int = 50,
) -> list[SeriesSuggestion]:
    """Run the detector and return ranked suggestions for human review.

    Bounded at ``limit`` (we don't want a UI that has to paginate the
    suggestion list — admins should burn through them in one sitting).
    Sorted highest-confidence first.
    """
    # Pull every unlinked, eligible conference.
    confs = (
        await db.execute(
            select(Conference)
            .where(Conference.series_id.is_(None))
            .where(~Conference.status.in_(list(_INELIGIBLE_STATUSES)))
        )
    ).scalars().all()
    if not confs:
        return []

    # Pull every active series with its aliases. Tiny N (low hundreds at
    # most) so we can iterate in Python rather than build a CROSS JOIN.
    series_rows = (
        await db.execute(
            select(ConferenceSeries).where(ConferenceSeries.is_active.is_(True))
        )
    ).scalars().all()
    if not series_rows:
        return []

    suggestions: list[SeriesSuggestion] = []

    for conf in confs:
        stripped = strip_year_and_edition(conf.name)
        if not stripped:
            continue

        # Get pg_trgm similarity() in one round-trip per conference.
        # similarity(text, text) returns a float in [0,1].
        rows = (
            await db.execute(
                sql_text(
                    """
                    SELECT id, canonical_name, aliases,
                           similarity(canonical_name, :stripped) AS canonical_sim
                    FROM app.conference_series
                    WHERE is_active = true
                    """
                ),
                {"stripped": stripped},
            )
        ).all()

        best: SeriesSuggestion | None = None
        for sid, canonical_name, aliases, canonical_sim in rows:
            # Score: canonical match first.
            sim = float(canonical_sim or 0.0)
            matched_via = "canonical"
            matched_value = canonical_name

            # Compare against each alias via Python-side trigram-ish
            # fallback (cheap; tiny N). For accuracy on alias matches we'd
            # call similarity() again in SQL — but Python's difflib is fine
            # at this scale, and avoids N*M round-trips.
            for alias in aliases or []:
                a_sim = _trigram_like(stripped, alias)
                if a_sim > sim:
                    sim = a_sim
                    matched_via = "alias"
                    matched_value = alias

            if sim < threshold:
                continue
            if best is None or sim > best.confidence:
                best = SeriesSuggestion(
                    conference_id=str(conf.id),
                    conference_name=conf.name,
                    series_id=str(sid),
                    canonical_name=canonical_name,
                    matched_via=matched_via,
                    matched_value=matched_value,
                    stripped_name=stripped,
                    confidence=round(sim, 4),
                )

        if best is not None:
            suggestions.append(best)

    suggestions.sort(key=lambda s: s.confidence, reverse=True)
    log.info(
        "series.detector.done",
        n_conferences=len(confs),
        n_series=len(series_rows),
        n_suggestions=len(suggestions),
        threshold=threshold,
    )
    return suggestions[:limit]


def _trigram_like(a: str, b: str) -> float:
    """Cheap Python-side trigram-style similarity for alias matching.

    Not byte-for-byte identical to pg_trgm's algorithm (pg_trgm uses
    SimilarityScore over trigram sets), but close enough at this scale.
    Both sides lowercased + non-alnum stripped.
    """
    norm_a = _normalize(a)
    norm_b = _normalize(b)
    if not norm_a or not norm_b:
        return 0.0
    grams_a = _trigrams(norm_a)
    grams_b = _trigrams(norm_b)
    if not grams_a or not grams_b:
        return 0.0
    inter = len(grams_a & grams_b)
    union = len(grams_a | grams_b)
    return inter / union if union else 0.0


def _normalize(s: str) -> str:
    return re.sub(r"[^a-z0-9 ]+", "", s.lower()).strip()


def _trigrams(s: str) -> set[str]:
    padded = f"  {s}  "
    return {padded[i : i + 3] for i in range(len(padded) - 2)}
