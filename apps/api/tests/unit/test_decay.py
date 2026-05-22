"""Pure-math tests for plan 25 decay helpers."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.services.lifecycle.decay import (
    DECAY_ALPHA,
    apply_decay_multiplier,
    compute_freshness,
)


class TestComputeFreshness:
    def test_none_reference_is_one(self) -> None:
        assert compute_freshness(reference_time=None, half_life_days=60) == 1.0

    def test_future_reference_is_one(self) -> None:
        future = datetime.now(tz=timezone.utc) + timedelta(days=7)
        assert compute_freshness(reference_time=future, half_life_days=60) == 1.0

    def test_zero_age_is_one(self) -> None:
        now = datetime.now(tz=timezone.utc)
        assert compute_freshness(reference_time=now, half_life_days=60, now=now) == 1.0

    def test_one_half_life_is_half(self) -> None:
        now = datetime.now(tz=timezone.utc)
        old = now - timedelta(days=60)
        result = compute_freshness(reference_time=old, half_life_days=60, now=now)
        assert result == pytest.approx(0.5, abs=0.001)

    def test_two_half_lives_is_quarter(self) -> None:
        now = datetime.now(tz=timezone.utc)
        old = now - timedelta(days=120)
        result = compute_freshness(reference_time=old, half_life_days=60, now=now)
        assert result == pytest.approx(0.25, abs=0.001)

    def test_naive_datetime_treated_as_utc(self) -> None:
        # A reference_time without tzinfo should be coerced, not crash.
        now = datetime.now(tz=timezone.utc)
        old_naive = (now - timedelta(days=60)).replace(tzinfo=None)
        result = compute_freshness(
            reference_time=old_naive, half_life_days=60, now=now
        )
        assert result == pytest.approx(0.5, abs=0.001)


class TestApplyDecayMultiplier:
    def test_freshness_one_returns_raw(self) -> None:
        assert apply_decay_multiplier(0.8, 1.0) == pytest.approx(0.8)

    def test_freshness_zero_returns_alpha_times_raw(self) -> None:
        # raw * (alpha + (1-alpha)*0) = raw * alpha
        assert apply_decay_multiplier(0.8, 0.0) == pytest.approx(0.8 * DECAY_ALPHA)

    def test_clamps_above_one(self) -> None:
        # raw=1.0, freshness=1.0 → max possible = 1.0, never above
        assert apply_decay_multiplier(1.0, 1.0) == 1.0

    def test_negative_freshness_treated_as_zero(self) -> None:
        # Multiplier should never go below alpha.
        result = apply_decay_multiplier(0.8, -0.5)
        assert result == pytest.approx(0.8 * DECAY_ALPHA)

    def test_alpha_override(self) -> None:
        # alpha=0.5, freshness=1.0 → multiplier = 0.5 + 0.5*1 = 1.0
        # alpha=0.5, freshness=0.0 → multiplier = 0.5
        assert apply_decay_multiplier(0.8, 1.0, alpha=0.5) == pytest.approx(0.8)
        assert apply_decay_multiplier(0.8, 0.0, alpha=0.5) == pytest.approx(0.4)
