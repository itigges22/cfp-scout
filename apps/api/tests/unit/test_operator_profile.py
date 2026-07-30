"""The operator profile is the judge's whole idea of who we are.

It is the only text telling the judge which audiences we serve, so a gap in
it becomes a wrong veto: an audience you serve but never wrote down is an
audience the judge will reject conferences for having. That makes it worth
guarding — and worth being editable without a deploy.
"""

from __future__ import annotations

import pytest
from app.settings import SPECS, Settings, coerce_setting


def _spec():
    return next((s for s in SPECS if s.name == "operator_profile"), None)


def test_it_is_editable_from_the_settings_ui() -> None:
    """Not being in SPECS means env-var-only, which means a deploy to change
    who the judge thinks we are."""
    spec = _spec()
    assert spec is not None, "operator_profile is missing from SPECS"
    assert spec.group == "matcher"


def test_it_is_a_textarea_not_a_one_line_input() -> None:
    """It is multi-paragraph prose. Editing it in a single-line input means
    not being able to see the text that decides what gets vetoed."""
    assert _spec().kind == "text"


def test_the_default_describes_rather_than_excludes() -> None:
    """The previous default ended "(NOT PhD students or academic faculty)".

    The judge obeyed it exactly and vetoed NeurIPS for having a research
    audience — for a team with AutoML research to present there. Exclusions
    fire on venues nobody had in mind; a description generalises.
    """
    default = Settings.model_fields["operator_profile"].default
    assert "NOT " not in default, f"exclusion clause in the default: {default}"
    assert "not a " not in default.lower()


def test_the_default_names_the_audiences_it_serves() -> None:
    default = Settings.model_fields["operator_profile"].default.lower()
    for audience in ("platform engineer", "developer", "decision-maker", "researcher"):
        assert audience in default, f"default never mentions {audience}"


def test_text_coerces_like_a_string_and_keeps_its_newlines() -> None:
    spec = _spec()
    multi = "line one\nline two\n\nline four"
    assert coerce_setting(spec, multi) == multi


def test_a_blank_profile_is_rejected() -> None:
    """An empty profile leaves the judge with no idea who the audience is,
    which is worse than a stale one — it would veto on vibes."""
    with pytest.raises(ValueError):
        Settings(operator_profile="   ")


def test_changing_it_invalidates_cached_verdicts() -> None:
    """Verdicts are cached on a hash of everything in the prompt.

    If the profile were left out of that hash, editing it in the UI would
    appear to do nothing — every conference would serve a verdict formed
    under the old description.
    """
    from app.db.models import Conference, StrategicPillar
    from app.services.matcher import compute_judge_input_hash

    conf = Conference(name="Some Event 2099", slug="some-event-2099")
    conf.topics = []
    conf.enriched_description = "A conference about things."
    pillar = StrategicPillar(name="P", description="d", display_order=1)
    pillar.enriched_description = None

    a = compute_judge_input_hash(
        conference=conf, pillars=[pillar], operator_profile="we sell boats"
    )
    b = compute_judge_input_hash(
        conference=conf, pillars=[pillar], operator_profile="we sell trains"
    )
    assert a != b, "editing the profile would not re-run the judge"
