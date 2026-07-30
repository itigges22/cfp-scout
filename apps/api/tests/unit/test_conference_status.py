"""Adding a status must not silently change what anyone can see.

`vetoed` shipped with the LLM judge. Only the producer and one whitelist
consumer were updated; every other filter was a hand-written blacklist, so
the new status was invisible to all of them. Nothing failed loudly — the
sets just quietly meant something different from what they claimed.

These tests make the vocabulary the single source and check that nothing has
drifted back to a literal.

Note the fix for that original bug went one step too far: `vetoed` was added
to HIDDEN_FROM_FINDER, which made the judge's opinion delete conferences
from view. That is now reversed — see
test_a_vetoed_conference_stays_visible_to_the_operator. Hiding is for
decisions a person made, not opinions a model had. The lesson that survives
is about the mechanism, not the membership: derive from the vocabulary, and
a change like this shows up as a failing test instead of a silent shift.
"""

from __future__ import annotations

import ast
import pathlib

import pytest
from app.services import conferences as cs

APP = pathlib.Path(__file__).resolve().parents[2] / "app"


def test_the_derived_sets_are_subsets_of_the_vocabulary() -> None:
    assert cs.HIDDEN_FROM_FINDER <= cs.ALL
    assert cs.SCOREABLE <= cs.ALL
    assert cs.DIGEST_ELIGIBLE <= cs.ALL


def test_hidden_and_digest_eligible_cannot_overlap() -> None:
    """A conference nobody should see must not earn a CFP reminder."""
    assert not (cs.HIDDEN_FROM_FINDER & cs.DIGEST_ELIGIBLE)


def test_a_vetoed_conference_stays_visible_to_the_operator() -> None:
    """The whole point of the veto: flagged, not deleted — and "flagged"
    has to mean the operator can actually see it.

    This test previously asserted the opposite, that a veto hid its
    conference. That was wrong, and it became actively harmful once
    discovery started ingesting broadly (W1): the judge runs ungated on
    every conference, so a hiding veto would quietly remove most of what
    discovery found, leaving a short list with no way to tell what was
    missing. That is the same silent-loss failure as the feed's keyword
    filter, which cost 375 of 801 future events.

    The team's goal is to say yes or no to a conference. They cannot say
    yes to one they were never shown.
    """
    assert not cs.is_hidden(cs.VETOED)
    # Still scoreable — an operator may disagree, and re-scoring has to
    # be able to reach it.
    assert cs.is_scoreable(cs.VETOED)
    # Visible is not the same as worth a deadline reminder.
    assert cs.VETOED not in cs.DIGEST_ELIGIBLE


def test_only_junk_and_human_rejections_are_hidden() -> None:
    """Hiding is reserved for decisions already taken by a person, or
    data too broken to show. A machine opinion never qualifies."""
    assert frozenset({cs.QUARANTINED, cs.REJECTED}) == cs.HIDDEN_FROM_FINDER


def test_quarantined_is_the_only_thing_the_matcher_skips() -> None:
    assert {cs.QUARANTINED} == cs.ALL - cs.SCOREABLE


@pytest.mark.parametrize(
    "status", ["approved", "rejected", "vetoed", "quarantined", "discovered"]
)
def test_every_status_the_pipeline_can_produce_is_in_the_vocabulary(
    status: str,
) -> None:
    assert status in cs.ALL


def test_choose_status_only_returns_known_statuses() -> None:
    """Read the producer directly — a new return value must be classified."""
    src = (APP / "services" / "matcher.py").read_text()
    tree = ast.parse(src)
    fn = next(
        n
        for n in ast.walk(tree)
        if isinstance(n, ast.FunctionDef) and n.name == "choose_status"
    )
    returned = {
        n.value.value
        for n in ast.walk(fn)
        if isinstance(n, ast.Return)
        and isinstance(n.value, ast.Constant)
        and isinstance(n.value.value, str)
    }
    assert returned, "could not read choose_status's return values"
    unknown = returned - cs.ALL
    assert not unknown, f"choose_status returns unclassified statuses: {unknown}"


def test_no_module_filters_status_with_a_hand_written_blacklist() -> None:
    """The drift mechanism, banned.

    `not_in(["quarantined", "rejected"])` is how `vetoed` stayed visible for
    a whole release. Filters must derive from conference_status.
    """
    offenders = []
    for p in APP.rglob("*.py"):
        if p.name == "conference_status.py":
            continue
        text = p.read_text()
        if 'not_in(["quarantined"' in text or "not_in(['quarantined'" in text:
            offenders.append(str(p.relative_to(APP)))
    assert not offenders, (
        f"hand-written status blacklist in {offenders} — derive it from "
        f"conference_status.HIDDEN_FROM_FINDER instead"
    )
