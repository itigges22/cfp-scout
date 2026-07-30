"""Tier-selection unit tests for the size-aware PDF parser.

The actual Docling pipeline runs are exercised by integration tests
(plan 27 pass 2). Here we just lock down the size-to-tier policy + the
fallback ordering so a regression can't silently send a 30 MB PDF
through the small-PDF pipeline.
"""

from __future__ import annotations

from app.services.pdf import (
    LARGE_THRESHOLD_BYTES,
    SMALL_THRESHOLD_BYTES,
    pick_tier,
)


class TestPickTier:
    def test_under_small_threshold_is_small(self) -> None:
        assert pick_tier(0) == "small"
        assert pick_tier(SMALL_THRESHOLD_BYTES - 1) == "small"

    def test_at_small_threshold_is_medium(self) -> None:
        # Strictly less-than for small; the boundary lands in medium.
        assert pick_tier(SMALL_THRESHOLD_BYTES) == "medium"

    def test_between_thresholds_is_medium(self) -> None:
        midpoint = (SMALL_THRESHOLD_BYTES + LARGE_THRESHOLD_BYTES) // 2
        assert pick_tier(midpoint) == "medium"
        assert pick_tier(LARGE_THRESHOLD_BYTES - 1) == "medium"

    def test_at_or_above_large_threshold_is_large(self) -> None:
        assert pick_tier(LARGE_THRESHOLD_BYTES) == "large"
        assert pick_tier(100 * 1024 * 1024) == "large"

    def test_thresholds_are_ordered(self) -> None:
        """Sanity guard against an accidental swap."""
        assert SMALL_THRESHOLD_BYTES < LARGE_THRESHOLD_BYTES
