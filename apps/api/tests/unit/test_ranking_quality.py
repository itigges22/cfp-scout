"""Does the scorer actually rank the labelled corpus correctly?

WHY THIS EXISTS
    tests/fixtures/corpus.py has existed for a while, carrying an
    ``expect`` label on every conference — strong / mid / weak / veto —
    and its docstring said "Called by tests/unit/test_ranking_quality.py".

    That file did not exist. Nothing consumed the corpus.

    The consequence was worse than an unused fixture: the "3/54
    inversions" figure quoted across the planning docs and several module
    docstrings could not be reproduced by anyone. Those numbers were real
    when taken, from ad-hoc scripts during the ranking rewrite, but the
    scripts were never committed. Every claim resting on them had quietly
    become unverifiable, and any future scoring change would have shipped
    on argument instead of evidence.

WHAT IT MEASURES
    An INVERSION is a pair of conferences the scorer puts in the wrong
    order relative to their labels — a `weak` ranked above a `strong`.
    Counting pairs rather than checking absolute scores is deliberate:
    the scorer's job is to order candidates, and the rescale band can
    move every number without changing a single decision.

WHAT THIS HARNESS DOES *NOT* REPLICATE — read before trusting a number
    It embeds each corpus text WHOLE and takes the best similarity across
    the pooled corpus. The shipped pipeline chunks documents and takes a
    top-K mean over chunk pairs, which gives a conference more chances to
    match some part of a long messaging document.

    So this measures a simplification of the scorer, not the scorer. It
    is still a real regression detector — same inputs, same
    ``signals.score``, same settings, deterministic — and it is the only
    committed measurement of ranking quality that exists. But an absolute
    number from here should not be quoted as "the matcher's inversion
    rate". Closing the gap means chunking the corpus the way
    embeddings/chunker.py does, and is worth doing.

REAL EMBEDDINGS, NO NETWORK
    Vectors come from tests/fixtures/corpus_vectors.json, computed once
    against the actual embedding model by
    tests/fixtures/build_corpus_vectors.py and committed.

    Synthetic vectors were considered and rejected. A cosine between two
    made-up vectors measures the vectors, not the scorer, and would have
    produced a number that looked like a measurement and was not. If the
    fixture is missing or was built with a different model, these tests
    SKIP with an instruction rather than silently measuring nothing.
"""

from __future__ import annotations

import json
import math
import pathlib
from itertools import combinations

import pytest
from app.services.matcher import score
from app.settings import Settings

from tests.fixtures import corpus
from tests.fixtures.build_corpus_vectors import conference_text, text_key

VECTORS_PATH = pathlib.Path(__file__).parent.parent / "fixtures" / "corpus_vectors.json"

#: MEASURED BASELINE, not a target: 16 inversions out of 86 comparable
#: pairs across 16 conferences (81% of orderings correct), as of
#: 2026-07-27 with Nomic-embed-text-v2-moe.
#:
#: This is NOT the "3/54" quoted in the planning docs. That figure came
#: from ad-hoc scripts measuring the full chunked pipeline over a
#: different pair set, and those scripts were never committed — see this
#: module's docstring. The two numbers are not comparable, and pretending
#: otherwise would be worse than admitting the old one is unverifiable.
#:
#: Lower it when the scorer improves. Raising it needs a written reason.
MAX_INVERSIONS = 16

#: Rank order the labels imply. `attended` sits with strong: an event we
#: went to and would go to again should not be pushed down the list.
_LABEL_RANK = {"strong": 3, "attended": 3, "mid": 2, "weak": 1, "veto": 0}


@pytest.fixture(scope="module")
def vectors() -> dict[str, list[float]]:
    if not VECTORS_PATH.exists():
        pytest.skip(
            f"{VECTORS_PATH.name} missing — regenerate with "
            "`uv run python -m tests.fixtures.build_corpus_vectors`"
        )
    blob = json.loads(VECTORS_PATH.read_text())
    recorded = blob.get("model")
    current = Settings().llm_embedding_model
    if recorded != current:
        pytest.skip(
            f"corpus vectors were built with {recorded!r} but the configured "
            f"model is {current!r}. Vectors from different models are not "
            "comparable; rebuild the fixture."
        )
    return blob["vectors"]


def _cos(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    return 0.0 if na == 0 or nb == 0 else dot / (na * nb)


def _vec(vectors: dict, text: str) -> list[float]:
    key = text_key(text)
    if key not in vectors:
        pytest.fail(
            f"no cached vector for a corpus text (key {key}). The corpus "
            "changed since the fixture was built — rerun "
            "`uv run python -m tests.fixtures.build_corpus_vectors`"
        )
    return vectors[key]


def _scored(vectors: dict) -> list[tuple[str, str, float]]:
    """``[(name, expect, overall)]`` for every corpus conference.

    Uses the shipped ``signals.score`` and the shipped default settings,
    so what is measured is what runs in production — not a reimplementation
    that could drift from it.
    """
    settings = Settings(
        database_url="postgresql+asyncpg://x/y",
        postgres_user="x",
        postgres_password="x",
        postgres_db="x",
        scraper_user_agent="test",
    )

    fit_corpus = [_vec(vectors, f"{p['name']}: {p['description']}") for p in corpus.PILLARS]
    fit_corpus += [_vec(vectors, m["elevator_pitch"]) for m in corpus.MESSAGING]
    speaker_corpus = [_vec(vectors, s["bio"]) for s in corpus.SMES]
    speaker_corpus += [
        _vec(vectors, f"{t['title']}. {t['abstract']}") for t in corpus.TALKS
    ]

    out = []
    for c in corpus.CONFERENCES:
        cv = _vec(vectors, conference_text(c))
        signals = score(
            fit_similarities=[_cos(cv, f) for f in fit_corpus],
            speaker_similarities=[_cos(cv, s) for s in speaker_corpus],
            settings=settings,
        )
        out.append((c["name"], c["expect"], signals.overall))
    return out


def _inversions(scored: list[tuple[str, str, float]]) -> list[tuple[str, str]]:
    """Pairs the scorer orders against their labels."""
    bad = []
    for (n1, e1, s1), (n2, e2, s2) in combinations(scored, 2):
        r1, r2 = _LABEL_RANK[e1], _LABEL_RANK[e2]
        if r1 == r2:
            continue  # same label: any order is fine
        if (r1 > r2 and s1 < s2) or (r2 > r1 and s2 < s1):
            bad.append((n1, n2))
    return bad


def test_the_corpus_is_actually_consumed_now() -> None:
    """The bug this file fixes. If the fixture stops being used again,
    this is the first thing that should fail."""
    assert corpus.CONFERENCES, "corpus is empty"
    assert VECTORS_PATH.exists(), "no committed vectors — the harness cannot run offline"


def test_ranking_does_not_regress(vectors) -> None:
    scored = _scored(vectors)
    bad = _inversions(scored)
    detail = "\n".join(f"    {a}  ranked below/above  {b}" for a, b in bad[:12])
    assert len(bad) <= MAX_INVERSIONS, (
        f"{len(bad)} label inversions (baseline {MAX_INVERSIONS}):\n{detail}\n"
        "A scoring change made the ordering worse. Either fix it or raise "
        "MAX_INVERSIONS with a written reason."
    )


def test_scores_are_spread_not_saturated(vectors) -> None:
    """A scorer that returns 1.0 for everything has zero inversions and is
    useless. This caught a real regression once: floor/ceiling tuned for
    top-K mean saturated 8 of 13 conferences at 1.000, and only scoring
    the corpus with the SHIPPED code revealed it."""
    scored = _scored(vectors)
    values = [s for _, _, s in scored]
    assert max(values) - min(values) > 0.15, (
        f"scores span only {max(values) - min(values):.3f} — the scorer is "
        f"barely separating anything. min={min(values):.3f} max={max(values):.3f}"
    )
    at_ceiling = sum(1 for v in values if v >= 0.999)
    assert at_ceiling <= len(values) // 3, (
        f"{at_ceiling}/{len(values)} conferences pinned at 1.000 — the "
        "rescale band is too narrow to discriminate"
    )


def test_the_strongest_beats_the_weakest(vectors) -> None:
    """The single claim the whole scorer has to earn."""
    scored = _scored(vectors)
    strong = [s for _, e, s in scored if e in ("strong", "attended")]
    weak = [s for _, e, s in scored if e in ("weak", "veto")]
    assert strong and weak, "corpus needs both strong and weak examples"
    assert max(strong) > max(weak), (
        f"best strong ({max(strong):.3f}) does not beat best weak "
        f"({max(weak):.3f})"
    )
