"""The judge vetoes on audience, and it reasons rather than looking things up.

No model call here — these pin the properties that make the verdict
trustworthy, which are all checkable offline. The behaviour itself is
checked by running the prompt over tests/fixtures/corpus.py.
"""

from __future__ import annotations

import pytest
from app.services.matcher import (
    _parse_response,
    _render_system_prompt,
)
from app.settings import get_settings

from tests.fixtures import corpus as C

# Venues the old prompt hardcoded verdicts for. Naming any of them again
# would reintroduce the failure: a categorical rule that silently overrides
# the reasoning it claims to guide.
_HARDCODED_VENUES = [
    "NeurIPS", "ICLR", "ICML", "AAAI", "EMNLP", "ACL", "CVPR", "COLT",
    "KubeCon", "re:Invent", "GTC", "Ignite", "DockerCon", "Ray Summit",
    "ODSC", "KDD", "RecSys", "SIGIR", "PyTorch", "Kubeflow",
]


def test_the_prompt_names_no_specific_venues() -> None:
    """The judge must reason about the room, not recall a list.

    The previous prompt said "ACADEMIC ML venues (NeurIPS, ICLR, ICML) score
    25-45 by default" and "INDUSTRY flagships default to 80+". That is a
    hardcoded opinion wearing a language model as a costume, it cannot be
    right for every operator, and it was wrong here — NeurIPS is a genuine
    fit for a team with research to present.

    It also cannot generalise: most discovered conferences are ones no list
    contains.
    """
    found = [v for v in _HARDCODED_VENUES if v.lower() in get_settings().prompt_judge.lower()]
    assert not found, (
        f"the prompt names {found} — replace the rule with a question about "
        f"who is in the room"
    )


def test_the_prompt_asks_about_the_audience() -> None:
    lowered = get_settings().prompt_judge.lower()
    assert "room" in lowered
    assert "audience" in lowered


def test_the_prompt_tells_the_model_not_to_veto_when_unsure() -> None:
    """Thin scraped text is a data problem. Vetoing on it would quietly
    delete conferences for having a bad website."""
    assert "unsure" in get_settings().prompt_judge.lower()


def test_the_operator_profile_is_injected() -> None:
    rendered = _render_system_prompt("WE SELL BOATS TO PIRATES")
    assert "WE SELL BOATS TO PIRATES" in rendered
    assert "{operator_profile}" not in rendered


# ---------------------------------------------------------------------------
# Parsing — the failure mode that matters is a wrongly-inferred veto
# ---------------------------------------------------------------------------
def test_ok_verdict() -> None:
    r = _parse_response('{"verdict": "ok", "reason": ""}')
    assert r is not None and not r.vetoed


def test_veto_carries_its_reason() -> None:
    r = _parse_response('{"verdict": "veto", "reason": "Marketers, not engineers."}')
    assert r is not None
    assert r.vetoed
    assert r.reason == "Marketers, not engineers."


def test_a_veto_without_a_reason_still_gets_one() -> None:
    """A veto shows up in a human's review queue. An empty reason there is
    unactionable, so it is filled rather than left blank."""
    r = _parse_response('{"verdict": "veto"}')
    assert r is not None and r.vetoed
    assert r.reason


def test_an_unparseable_reply_is_not_a_veto() -> None:
    """None means the caller leaves the conference alone. Dropping one
    because a model rambled is worse than showing one that should have
    been dropped."""
    assert _parse_response("I think this conference is probably fine!") is None
    assert _parse_response("") is None


def test_an_unescaped_quote_in_the_reason_still_yields_the_verdict() -> None:
    """Strict JSON parsing would discard the whole call over punctuation."""
    r = _parse_response('{"verdict": "veto", "reason": "They call it "AI" but it is CRM."}')
    assert r is not None and r.vetoed


@pytest.mark.parametrize("text", ['{"verdict":"VETO","reason":"x"}', '{"verdict" : "veto" , "reason":"x"}'])
def test_case_and_spacing_do_not_change_the_verdict(text: str) -> None:
    r = _parse_response(text)
    assert r is not None and r.vetoed


# ---------------------------------------------------------------------------
# The fixture has to be self-consistent or it tests nothing
# ---------------------------------------------------------------------------
def test_the_corpus_profile_covers_the_corpus_pillars() -> None:
    """The judge sees only the profile when deciding who the audience is.

    If the corpus carries research SMEs and a Data Science pillar but the
    profile never mentions research, then vetoing NeurIPS is the CORRECT
    answer and the expectation label is the thing that is wrong. Keeping
    them in step is what makes a judge failure mean the judge failed.
    """
    profile = C.OPERATOR_PROFILE.lower()
    assert "research" in profile, (
        "the corpus has AI Research SMEs and a Data Science & AutoML pillar; "
        "a profile that omits research makes the NeurIPS expectation unfair"
    )
    assert "platform engineer" in profile
    research_smes = [s for s in C.SMES if "research" in s["team"].lower()]
    assert research_smes, "profile promises research staff the corpus lacks"
