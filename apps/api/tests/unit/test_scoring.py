"""The matcher's arithmetic — primitives, signals, and ranking.

One file because they are one module now (services/matcher.py).
These were test_scoring, test_signals and test_ranking, split to mirror
three source modules that each defined overlapping helpers; two of them
had their own ``clamp01``.
"""

from __future__ import annotations

import ast
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from app.services.matcher import (
    apply_chunk_decay,
    assign_ranks,
    best,
    blend,
    clamp01,
    cosine_from_distance,
    rescale,
    score,
    tie_summary,
    topk_mean,
)
from app.settings import Settings, get_settings

# --------------------------------------------------------------------------
# from test_scoring.py
# --------------------------------------------------------------------------


class TestClamp01:
    def test_in_range(self) -> None:
        assert clamp01(0.5) == 0.5
        assert clamp01(0.0) == 0.0
        assert clamp01(1.0) == 1.0

    def test_above_range(self) -> None:
        assert clamp01(1.5) == 1.0
        assert clamp01(99.0) == 1.0

    def test_below_range(self) -> None:
        assert clamp01(-0.1) == 0.0
        assert clamp01(-99.0) == 0.0


class TestTopKMean:
    def test_empty(self) -> None:
        assert topk_mean([], k=5) == 0.0

    def test_fewer_than_k(self) -> None:
        # mean of [0.8, 0.6, 0.4] = 0.6
        assert topk_mean([0.8, 0.6, 0.4], k=10) == pytest.approx(0.6)

    def test_picks_top_k(self) -> None:
        # top-3 of [0.9, 0.1, 0.8, 0.2, 0.7] = [0.9, 0.8, 0.7] → mean 0.8
        assert topk_mean([0.9, 0.1, 0.8, 0.2, 0.7], k=3) == pytest.approx(0.8)

    def test_zero_when_all_zero(self) -> None:
        assert topk_mean([0.0, 0.0, 0.0], k=2) == 0.0


class TestCosineFromDistance:
    def test_zero_distance_is_one(self) -> None:
        assert cosine_from_distance(0.0) == 1.0

    def test_one_distance_is_zero(self) -> None:
        assert cosine_from_distance(1.0) == 0.0

    def test_clamps_negative_similarity_to_zero(self) -> None:
        # distance 1.5 → similarity -0.5 → clamped to 0
        assert cosine_from_distance(1.5) == 0.0


class _StubChunk:
    """Minimal stand-in for a DocumentChunk row used by apply_chunk_decay."""

    def __init__(
        self,
        last_used_at: datetime | None = None,
        created_at: datetime | None = None,
    ) -> None:
        self.last_used_at = last_used_at
        self.created_at = created_at


class TestApplyChunkDecay:
    def test_no_timestamps_returns_raw(self) -> None:
        # Missing timestamps → freshness defaults to 1.0 → multiplier
        # collapses to 1.0 → returns raw similarity unchanged.
        chunk = _StubChunk()
        assert apply_chunk_decay(0.8, chunk) == pytest.approx(0.8)

    def test_fresh_chunk_returns_near_raw(self) -> None:
        now = datetime.now(tz=UTC)
        chunk = _StubChunk(created_at=now, last_used_at=now)
        assert apply_chunk_decay(0.8, chunk) == pytest.approx(0.8, rel=0.01)

    def test_one_half_life_drops_score(self) -> None:
        # 60-day-old chunk → freshness ≈ 0.5 → 0.8 × (0.85 + 0.15*0.5) ≈ 0.74
        old = datetime.now(tz=UTC) - timedelta(days=60)
        chunk = _StubChunk(created_at=old, last_used_at=old)
        result = apply_chunk_decay(0.8, chunk)
        assert 0.72 < result < 0.76

    def test_very_old_chunk_floors_at_alpha(self) -> None:
        # Many half-lives old → freshness → 0 → multiplier → alpha (0.85)
        # → 0.8 × 0.85 = 0.68
        ancient = datetime.now(tz=UTC) - timedelta(days=3650)
        chunk = _StubChunk(created_at=ancient, last_used_at=ancient)
        result = apply_chunk_decay(0.8, chunk)
        assert result == pytest.approx(0.68, abs=0.01)

    def test_uses_last_used_at_when_more_recent(self) -> None:
        # Created long ago but recently used → still ~fresh.
        old_created = datetime.now(tz=UTC) - timedelta(days=365)
        recent_use = datetime.now(tz=UTC) - timedelta(hours=1)
        chunk = _StubChunk(created_at=old_created, last_used_at=recent_use)
        result = apply_chunk_decay(0.8, chunk)
        assert result == pytest.approx(0.8, rel=0.01)


# --------------------------------------------------------------------------
# from test_signals.py
# --------------------------------------------------------------------------


@pytest.fixture()
def settings():
    return get_settings()


def test_shipped_weights_sum_to_one(settings) -> None:
    total = settings.match_w_fit + settings.match_w_speakers
    assert total == pytest.approx(1.0), (
        f"matcher weights sum to {total}; every displayed percentage is then "
        f"wrong by that factor"
    )


def test_weights_that_do_not_sum_to_one_are_rejected() -> None:
    with pytest.raises(ValueError, match=r"sum to 1.0"):
        Settings(match_w_fit=0.40, match_w_speakers=0.35)


def test_negative_weights_are_rejected() -> None:
    with pytest.raises(ValueError):
        Settings(match_w_fit=1.5, match_w_speakers=-0.5)


def test_both_signals_perfect_is_one(settings) -> None:
    assert blend(fit=1.0, speakers=1.0, settings=settings) == pytest.approx(1.0)


def test_both_signals_zero_is_zero(settings) -> None:
    assert blend(fit=0.0, speakers=0.0, settings=settings) == pytest.approx(0.0)


def test_fit_outweighs_speakers(settings) -> None:
    """A conference our audience cares about beats one we merely have a
    speaker for. That ordering is the design, so it gets a test."""
    assert blend(fit=1.0, speakers=0.0, settings=settings) > blend(
        fit=0.0, speakers=1.0, settings=settings
    )


def test_blend_is_clamped(settings) -> None:
    assert 0.0 <= blend(fit=5.0, speakers=5.0, settings=settings) <= 1.0
    assert 0.0 <= blend(fit=-5.0, speakers=-5.0, settings=settings) <= 1.0


def test_zero_total_weight_does_not_divide_by_zero() -> None:
    class _Zero:
        match_w_fit = match_w_speakers = 0.0

    assert blend(fit=0.5, speakers=0.5, settings=_Zero()) == pytest.approx(0.0)


def test_an_empty_pool_scores_zero_not_missing() -> None:
    """No SME roster means we genuinely cannot staff the event. That is a
    real 0, not an absent measurement whose weight should be redistributed."""
    assert best([]) == 0.0


def test_best_takes_the_max_not_the_mean() -> None:
    """One pillar matching strongly is what makes a conference relevant.
    Averaging in four unrelated pillars would make the score depend on how
    many pillars happen to exist."""
    assert best([0.2, 0.9, 0.1, 0.15]) == pytest.approx(0.9)


def test_rescale_stretches_the_usable_band() -> None:
    assert rescale(0.10, floor=0.10, ceiling=0.45) == pytest.approx(0.0)
    assert rescale(0.45, floor=0.10, ceiling=0.45) == pytest.approx(1.0)
    assert rescale(0.275, floor=0.10, ceiling=0.45) == pytest.approx(0.5)


def test_rescale_survives_an_inverted_range() -> None:
    """A bad setting must not divide by zero or produce a negative score."""
    assert 0.0 <= rescale(0.5, floor=0.9, ceiling=0.1) <= 1.0


def test_score_pools_both_corpora(settings) -> None:
    """A strong pillar hit lifts fit even when messaging is weak — the two
    are one pool, not two weighted stages."""
    weak = score(fit_similarities=[0.1], speaker_similarities=[0.1], settings=settings)
    strong = score(
        fit_similarities=[0.1, 0.9], speaker_similarities=[0.1], settings=settings
    )
    assert strong.fit > weak.fit
    assert strong.overall > weak.overall


def _weight_names_used_in(path: Path) -> set[str]:
    tree = ast.parse(path.read_text())
    return {
        n.attr
        for n in ast.walk(tree)
        if isinstance(n, ast.Attribute) and n.attr.startswith("match_w_")
    }


def _conference_modules() -> list[Path]:
    """Every module in the conference package (it was one file before P6)."""
    return sorted((Path(__file__).resolve().parents[2] / "app/api/v1/conferences").glob("*.py"))


def test_call_sites_do_not_reimplement_the_blend() -> None:
    """Reading ``settings.match_w_*`` outside signals.py is how a second
    formula starts. Every consumer must go through blend()."""
    # blend() itself lives in matcher.py now, so that file necessarily reads
    # the weights — inside blend and nowhere else. The old guard excluded
    # signals.py by filename; that file was merged away, so the rule has to
    # be stated at function granularity instead of file granularity.
    import ast

    matcher = Path(__file__).resolve().parents[2] / "app/services/matcher.py"
    weights = {"match_w_fit", "match_w_speakers"}
    readers = {
        fn.name
        for fn in ast.walk(ast.parse(matcher.read_text()))
        if isinstance(fn, ast.FunctionDef | ast.AsyncFunctionDef)
        and any(
            isinstance(a, ast.Attribute) and a.attr in weights for a in ast.walk(fn)
        )
    }
    assert readers == {"blend"}, (
        f"{sorted(readers)} read the blend weights; only blend() may, so there "
        f"is exactly one formula"
    )

    offenders = {
        str(p.name): sorted(_weight_names_used_in(p))
        for p in _conference_modules()
        if _weight_names_used_in(p)
    }
    assert not offenders, (
        f"{offenders} read the weights directly — call blend() instead so "
        f"there is only one formula"
    )


def test_blend_is_defined_exactly_once() -> None:
    root = Path(__file__).resolve().parents[2] / "app"
    definitions = [p for p in root.rglob("*.py") if "def blend(" in p.read_text()]
    assert len(definitions) == 1, f"blend defined in {definitions}"


def test_the_usable_band_matches_what_max_pooling_produces(settings) -> None:
    """floor/ceiling must bracket the cosines the signals actually see.

    These were 0.10/0.45, tuned for a top-K mean (which lands 0.29-0.56).
    Against a max-pooled cosine (0.33-0.75) everything above 0.45 clamped,
    and eight of thirteen corpus conferences scored exactly 1.000 — the
    ranking collapsed while every unit test still passed. Only scoring the
    real corpus surfaced it.
    """
    floor = settings.matcher_baseline_cosine
    ceiling = settings.matcher_ceiling_cosine
    assert floor < ceiling
    assert 0.25 <= floor <= 0.40, (
        f"floor {floor} is outside the measured range for a max-pooled "
        f"cosine; below ~0.30 the weak end stops separating"
    )
    assert ceiling >= 0.70, (
        f"ceiling {ceiling} is below the strongest real cosines (~0.75), so "
        f"good matches clamp to 1.0 and tie with each other"
    )


def test_realistic_cosines_do_not_all_saturate(settings) -> None:
    """Five plausible conferences must produce five distinguishable scores."""
    observed = [0.35, 0.45, 0.55, 0.65, 0.75]
    scores = [
        score(
            fit_similarities=[c], speaker_similarities=[c], settings=settings
        ).overall
        for c in observed
    ]
    assert len(set(round(s, 3) for s in scores)) == len(observed), (
        f"distinct inputs collapsed to {scores} — the band is too narrow"
    )
    assert scores == sorted(scores)


# --------------------------------------------------------------------------
# from test_ranking.py
# --------------------------------------------------------------------------


def test_distinct_scores_rank_in_order() -> None:
    r = assign_ranks([("a", 0.9), ("b", 0.5), ("c", 0.1)])
    assert [(x.item, x.rank) for x in r] == [("a", 1), ("b", 2), ("c", 3)]
    assert not any(x.tied for x in r)


def test_ties_share_a_rank_and_the_next_one_skips() -> None:
    """Competition ranking: 1, 2, 2, 4. The count of conferences above a
    rank stays equal to rank - 1, which is what makes "#4 of 40" true."""
    r = assign_ranks([("a", 0.9), ("b", 0.5), ("c", 0.5), ("d", 0.2)])
    assert [x.rank for x in r] == [1, 2, 2, 4]


def test_near_equal_scores_tie() -> None:
    """0.7213 and 0.7189 both display as 72%. Ranking them #3 and #4
    invents precision the scores do not have."""
    r = assign_ranks([("a", 0.7213), ("b", 0.7189)])
    assert [x.rank for x in r] == [1, 1]
    assert all(x.tied for x in r)


def test_scores_further_apart_than_the_tolerance_do_not_tie() -> None:
    r = assign_ranks([("a", 0.80), ("b", 0.80 - get_settings().matcher_tie_tolerance * 2)])
    assert [x.rank for x in r] == [1, 2]


def test_a_shallow_slope_does_not_chain_into_one_group() -> None:
    """Each item is compared to its GROUP LEADER, not its neighbour.

    Chaining on neighbours would collapse a long gentle gradient into a
    single tie even though the ends are far apart — every conference tied
    with every other, which is obviously wrong.
    """
    step = get_settings().matcher_tie_tolerance * 0.8
    scored = [(f"c{i}", 1.0 - i * step) for i in range(10)]
    r = assign_ranks(scored)
    assert r[0].rank != r[-1].rank, "a 10-step slope collapsed into one rank"


def test_everything_tied_is_reported_not_hidden() -> None:
    """A cohort we cannot separate is a finding about the evidence (D10)."""
    r = assign_ranks([("a", 0.5), ("b", 0.5), ("c", 0.5)])
    assert [x.rank for x in r] == [1, 1, 1]
    assert tie_summary(r) == {"total": 3, "tied": 3, "distinct_ranks": 1}


def test_ranks_are_positions_in_the_whole_cohort_not_the_slice() -> None:
    """The property that makes filtering safe (D11).

    Rank is assigned once over everything; a filter is a predicate applied
    afterwards. The best conference in Germany keeps its global number
    instead of being relabelled #1.
    """
    cohort = [("de1", 0.80), ("us1", 0.95), ("de2", 0.40), ("us2", 0.90)]
    ranked = assign_ranks(cohort)
    german = [x for x in ranked if x.item.startswith("de")]
    assert [x.rank for x in german] == [3, 4]


def test_empty_input() -> None:
    assert assign_ranks([]) == []
    assert tie_summary([]) == {"total": 0, "tied": 0, "distinct_ranks": 0}


def test_order_within_a_tie_group_is_stable() -> None:
    """Same input, same output — a list must not shuffle between renders."""
    scored = [("a", 0.5), ("b", 0.5), ("c", 0.5)]
    assert [x.item for x in assign_ranks(scored)] == [
        x.item for x in assign_ranks(scored)
    ]


def test_rank_minus_one_equals_the_number_of_conferences_above() -> None:
    """The invariant that lets the UI say "#7 of 48" honestly."""
    scored = [("a", 0.9), ("b", 0.7), ("c", 0.7), ("d", 0.7), ("e", 0.3)]
    ranked = assign_ranks(scored)
    for r in ranked:
        strictly_above = sum(
            1 for o in ranked if o.score - r.score > get_settings().matcher_tie_tolerance
        )
        assert strictly_above == r.rank - 1, f"{r.item} at rank {r.rank}"
