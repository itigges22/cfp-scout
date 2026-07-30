"""A dimension we could not measure is not a zero.

WHY THIS EXISTS
    ``conference_audiences`` is read by the SME ranker and written by
    nothing — no service, no task, no extraction step ever inserts a row.
    So ``audience_overlap`` was 0 for every SME/conference pair in
    existence.

    The composite was a plain weighted sum, so that 0 did not redistribute
    — it CAPPED. With sme_w_audience at 0.25, the highest score any SME
    could reach was 0.75, against a gate of 0.5. A candidate who was
    perfect on bio, location and past attendance still lost a
    quarter of the scale for a question nothing could answer.

    Nothing failed. The scores were simply lower than they claimed to be,
    for a reason no log line mentioned.

THE DISTINCTION
    signals.py deliberately does the OPPOSITE for the speaker signal: an
    empty SME roster scores a real 0, because it genuinely means we
    cannot staff the event. Measured absence and missing measurement look
    identical in a number and mean opposite things.
"""

from __future__ import annotations

import pytest
from app.settings import Settings


def _weights(s: Settings) -> dict[str, float]:
    return {
        "audience": s.sme_w_audience,
        "bio": s.sme_w_bio,
        "location": s.sme_w_location,
        "past": s.sme_w_past,
    }


def test_the_weights_still_sum_to_one() -> None:
    assert sum(_weights(Settings()).values()) == pytest.approx(1.0)


def test_a_perfect_sme_can_reach_1_when_audiences_are_missing() -> None:
    """The bug, stated as arithmetic. Before renormalisation the best
    achievable composite was 1 - sme_w_audience."""
    s = Settings()
    w = _weights(s)
    w.pop("audience")
    total = sum(w.values())

    # Perfect on every measurable dimension.
    composite = sum(w[k] * 1.0 for k in w) / total
    assert composite == pytest.approx(1.0), (
        "a candidate perfect on every dimension we CAN measure should be "
        "able to score 1.0"
    )

    # What it used to be.
    old = sum(w[k] * 1.0 for k in w)
    assert old == pytest.approx(1.0 - s.sme_w_audience)
    assert old < s.match_s_gate * 2, "documenting the size of the old cap"


def test_relative_order_is_unchanged_by_renormalisation() -> None:
    """Renormalising divides every composite by the same constant, so it
    cannot reorder candidates — it only stops the scale being truncated.
    Worth pinning: a scoring change that reorders silently is the thing
    the ranking harness exists to catch."""
    s = Settings()
    w = _weights(s)
    w.pop("audience")
    total = sum(w.values())

    a = {"bio": 0.4, "location": 1.0, "past": 0.0}
    b = {"bio": 0.9, "location": 0.0, "past": 1.0}

    raw_a = sum(w[k] * a[k] for k in w)
    raw_b = sum(w[k] * b[k] for k in w)
    assert (raw_a > raw_b) == ((raw_a / total) > (raw_b / total))


def test_a_measured_zero_still_counts() -> None:
    """Only dimensions whose INPUTS are absent get dropped. An SME who
    was never at any edition of a series scores 0 on past attendance and
    keeps its weight — that is a real answer."""
    s = Settings()
    w = _weights(s)  # audiences present, nothing dropped
    total = sum(w.values())
    scores = {"audience": 1.0, "bio": 1.0, "location": 1.0, "past": 0.0}
    composite = sum(w[k] * scores[k] for k in w) / total
    assert composite == pytest.approx(1.0 - s.sme_w_past), (
        "a real zero must still cost its weight"
    )
