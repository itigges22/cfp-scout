"""app_setting_overrides holds settings. Only settings.

WHY THIS EXISTS
    ``upsert()`` accepted any name. The diagnostics page used it to park
    a "when did someone last clear the LLM error list" timestamp —
    operational state, not a setting, not a field on ``Settings``, and
    something that would never appear on the settings page.

    That table feeds ``get_settings()``. Every row in it should
    correspond to something an operator can see and change. Two ways it
    goes wrong otherwise:

      * stray values accumulate, and the table stops describing settings
      * a TYPO'd real key ("mach_m_gate") sits there looking configured
        while changing nothing, with no error anywhere

    Values that are not settings now go in ``app.ops_state``.
"""

from __future__ import annotations

import pytest
from app.services.settings_store import _reject_unknown
from app.settings import SPECS


def test_a_registered_setting_is_accepted() -> None:
    _reject_unknown("llm_api_key")
    _reject_unknown("discovery_keywords")


def test_the_diagnostics_watermark_is_refused() -> None:
    """The exact value that was living in the settings table."""
    with pytest.raises(ValueError, match="not a registered setting"):
        _reject_unknown("diagnostics_llm_errors_cleared_at")


def test_a_typo_of_a_real_setting_is_refused() -> None:
    """The quieter failure: close enough to look right, wrong enough to
    do nothing."""
    with pytest.raises(ValueError, match="not a registered setting"):
        _reject_unknown("mach_m_gate")


def test_the_error_says_what_to_do_instead() -> None:
    with pytest.raises(ValueError) as exc:
        _reject_unknown("something_invented")
    msg = str(exc.value)
    assert "SettingSpec" in msg, "should say how to register it properly"


def test_every_spec_name_is_a_real_settings_field() -> None:
    """The other direction: a SettingSpec for a field that does not exist
    would render an editable control that writes to nothing."""
    from app.settings import Settings

    fields = set(Settings.model_fields)
    missing = [s.name for s in SPECS if s.name not in fields]
    assert not missing, (
        f"settings_spec registers names that are not Settings fields: "
        f"{sorted(missing)}. The settings page would show a control that "
        f"writes a value nothing reads."
    )
