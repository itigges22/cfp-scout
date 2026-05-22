"""Pure-function tests for the matcher scoring helpers (plan 17 + 25)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.services.matcher._scoring import (
    apply_chunk_decay,
    clamp01,
    cosine_from_distance,
    topk_max,
    topk_mean,
)


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


class TestTopKMax:
    def test_empty(self) -> None:
        assert topk_max([]) == 0.0

    def test_picks_max(self) -> None:
        assert topk_max([0.1, 0.7, 0.3, 0.9, 0.5]) == 0.9


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
        now = datetime.now(tz=timezone.utc)
        chunk = _StubChunk(created_at=now, last_used_at=now)
        assert apply_chunk_decay(0.8, chunk) == pytest.approx(0.8, rel=0.01)

    def test_one_half_life_drops_score(self) -> None:
        # 60-day-old chunk → freshness ≈ 0.5 → 0.8 × (0.85 + 0.15*0.5) ≈ 0.74
        old = datetime.now(tz=timezone.utc) - timedelta(days=60)
        chunk = _StubChunk(created_at=old, last_used_at=old)
        result = apply_chunk_decay(0.8, chunk)
        assert 0.72 < result < 0.76

    def test_very_old_chunk_floors_at_alpha(self) -> None:
        # Many half-lives old → freshness → 0 → multiplier → alpha (0.85)
        # → 0.8 × 0.85 = 0.68
        ancient = datetime.now(tz=timezone.utc) - timedelta(days=3650)
        chunk = _StubChunk(created_at=ancient, last_used_at=ancient)
        result = apply_chunk_decay(0.8, chunk)
        assert result == pytest.approx(0.68, abs=0.01)

    def test_uses_last_used_at_when_more_recent(self) -> None:
        # Created long ago but recently used → still ~fresh.
        old_created = datetime.now(tz=timezone.utc) - timedelta(days=365)
        recent_use = datetime.now(tz=timezone.utc) - timedelta(hours=1)
        chunk = _StubChunk(created_at=old_created, last_used_at=recent_use)
        result = apply_chunk_decay(0.8, chunk)
        assert result == pytest.approx(0.8, rel=0.01)
