"""Event kinds are the operator's vocabulary, not ours.

WHY THIS EXISTS
    ``event_kind`` was a Python tuple with a database CHECK behind it. A
    team whose events are not shaped like ours — no research track, or a
    category we never thought of — could not say so without a code change
    and a migration. Same mistake the discovery keyword list had: a
    decision about the operator's world, compiled in.

    The awkward part is that one kind carried BEHAVIOUR. 'grassroot'
    events were created already approved and hidden from the finder,
    because there is no decision to make about attending your own meetup.
    While the list was hardcoded, that meaning could ride along on the
    name. Once the name is editable, behaviour attached to it silently
    detaches — rename 'grassroot' and the auto-approve quietly stops
    happening, with nothing failing.

    So it became its own setting. These tests pin that separation.
"""

from __future__ import annotations

import pytest
from app.settings import Settings


def test_kinds_are_a_setting_not_a_constant() -> None:
    from app.settings import SPECS

    names = {s.name for s in SPECS}
    assert "event_kinds" in names, "not editable from the settings page"
    assert "event_kinds_skipping_review" in names


def test_the_shipped_default_is_what_we_had_before() -> None:
    """Making it configurable must not change anyone's vocabulary."""
    assert Settings().event_kinds == [
        "corporate",
        "grassroot",
        "developer_day",
        "research",
        "hackathon",
    ]


def test_skip_review_kinds_must_be_real_kinds() -> None:
    """A kind that skips review but cannot be selected is unreachable —
    the operator would set it, see nothing happen, and have no way to
    tell why."""
    with pytest.raises(ValueError, match="not in"):
        Settings(event_kinds=["corporate"], event_kinds_skipping_review=["grassroot"])


def test_an_operator_can_use_a_vocabulary_we_never_shipped() -> None:
    s = Settings(
        event_kinds=["unconference", "barcamp"],
        event_kinds_skipping_review=["barcamp"],
    )
    assert s.event_kinds == ["unconference", "barcamp"]


def test_the_extraction_prompt_is_built_from_the_setting(monkeypatch) -> None:
    """The extractor classifies scraped pages into these categories. If
    the prompt kept its own hardcoded list, pages would be sorted into
    categories the operator does not use and cannot fix."""
    from app.services import extraction

    class _Fake:
        event_kinds = ["unconference", "barcamp"]

    monkeypatch.setattr(extraction, "get_settings", lambda: _Fake(), raising=False)
    monkeypatch.setattr("app.settings.get_settings", lambda: _Fake())

    text = extraction.build_system_prompt()
    assert "unconference" in text
    assert "barcamp" in text
    assert "developer_day" not in text, "a kind nobody configured leaked in"


def test_an_empty_vocabulary_asks_for_nothing_rather_than_inventing_one(
    monkeypatch,
) -> None:
    from app.services import extraction

    class _Fake:
        event_kinds: list[str] = []

    monkeypatch.setattr("app.settings.get_settings", lambda: _Fake())
    text = extraction.build_system_prompt()
    assert "omit this field" in text.lower()


def test_the_injection_guard_survives_the_rebuild() -> None:
    """build_system_prompt does string replacement on a template. The
    untrusted-input rule must not be lost in the process — extraction
    reads scraped pages, which have been known to contain text aimed at
    whatever model reads them."""
    from app.services.extraction import build_system_prompt

    text = build_system_prompt()
    assert "<page_text>" in text
    assert "untrusted DATA" in text
