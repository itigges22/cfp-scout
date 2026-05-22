"""Tests for the series name-stripping helper (plan 23)."""

from __future__ import annotations

import pytest

from app.services.series.detector import strip_year_and_edition


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("NeurIPS 2026", "NeurIPS"),
        ("AAAI 2027 Spring", "AAAI"),
        ("ICML 2025: Vol. 42", "ICML"),
        ("KubeCon + CloudNativeCon NA 2026", "KubeCon + CloudNativeCon NA"),
        ("CVPR 1999", "CVPR"),
        ("12th Annual AI Engineer World's Fair 2027", "AI Engineer World's Fair"),
        # No year + no edition tokens → unchanged sans collapsing.
        ("Strange Loop", "Strange Loop"),
    ],
)
def test_strip(raw: str, expected: str) -> None:
    assert strip_year_and_edition(raw) == expected
