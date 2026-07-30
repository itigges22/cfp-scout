"""Bounds must hold on BOTH paths into a setting.

A value can arrive two ways: an environment variable at boot, or a PATCH to
/admin/settings at runtime. `settings_spec` enforced its min/max only on the
second. Thirteen settings had bounds there and bare types in `settings.py`,
so `SCOUT_MATCH_M_GATE=5.0` passed validation at boot and sent every
conference to `low_messaging_fit` — while the same value typed into the
settings UI was rejected.
"""

from __future__ import annotations

import pytest
from app.settings import SPECS, Settings


def _has_bounds(name: str) -> bool:
    field = Settings.model_fields.get(name)
    if field is None:
        return False
    meta = " ".join(repr(m) for m in (field.metadata or []))
    return "Ge(" in meta or "Le(" in meta or "Interval(" in meta


def test_every_spec_bound_is_also_enforced_on_the_env_path() -> None:
    unenforced = [
        s.name
        for s in SPECS
        if (s.min_value is not None or s.max_value is not None)
        and not _has_bounds(s.name)
    ]
    assert not unenforced, (
        f"these have bounds in settings_spec but bare types in settings.py, "
        f"so an env var bypasses them: {unenforced}"
    )


@pytest.mark.parametrize(
    ("field", "bad"),
    [
        ("match_m_gate", 5.0),
        ("match_s_gate", -1.0),
        ("sme_w_bio", 2.0),
        ("llm_monthly_budget_usd", -5.0),
    ],
)
def test_an_out_of_range_value_is_rejected(field: str, bad: float) -> None:
    with pytest.raises(Exception):
        Settings(**{field: bad})


def test_in_range_values_are_still_accepted() -> None:
    """Adding bounds must not reject legitimate configuration.

    Deliberately avoids the sme_w_* family here — those carry a
    separate sum-to-1.0 validator, so setting one in isolation fails for a
    different and correct reason.
    """
    s = Settings(
        match_m_gate=0.5,
        match_s_gate=0.25,
        llm_monthly_budget_usd=None,
    )
    assert s.match_m_gate == 0.5


def test_the_weight_families_still_have_to_sum_to_one() -> None:
    """Bounds are per-field; the sum rule is separate and still enforced."""
    with pytest.raises(Exception, match=r"sum to 1\.0"):
        Settings(sme_w_bio=0.9, sme_w_audience=0.9)
