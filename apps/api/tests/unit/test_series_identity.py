"""Series identity has to answer two different questions correctly.

Getting these wrong applies one conference's history to another — the
failure the fuzzy name matchers it replaces were prone to, silently.
"""

from __future__ import annotations

import pytest
from app.services.conferences import (
    event_key,
    relationship,
    same_event,
    same_series,
    series_key,
)

KUBECON_EU_25 = "KubeCon + CloudNativeCon Europe 2025"
KUBECON_EU_26 = "KubeCon + CloudNativeCon Europe 2026"
KUBECON_NA_26 = "KubeCon + CloudNativeCon North America 2026"


# ---------------------------------------------------------------------------
# The case that motivated the module
# ---------------------------------------------------------------------------
def test_same_event_across_years() -> None:
    """Different years of one event are the same event — that is what makes
    'we attended this last year' mean anything."""
    assert same_event(KUBECON_EU_25, KUBECON_EU_26)
    assert relationship(KUBECON_EU_25, KUBECON_EU_26) == "same_event"


def test_same_series_but_different_event_across_regions() -> None:
    """EU and NA are one franchise and two events. History from one should
    not be applied to the other as if they were interchangeable."""
    assert same_series(KUBECON_EU_26, KUBECON_NA_26)
    assert not same_event(KUBECON_EU_26, KUBECON_NA_26)
    assert relationship(KUBECON_EU_26, KUBECON_NA_26) == "same_series"


def test_unrelated_conferences_are_unrelated() -> None:
    assert relationship(KUBECON_EU_26, "PyTorch Conference 2026") == "unrelated"
    assert relationship("NeurIPS 2026", "WordPress Community Summit 2026") == "unrelated"


# ---------------------------------------------------------------------------
# Identity must ignore what does not identify
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    ("a", "b"),
    [
        ("NeurIPS 2025", "NeurIPS 2026"),
        ("PyTorch Conference 2026", "PyTorch Conference 2027"),
        ("12th Annual AI Engineer World's Fair 2027", "AI Engineer World's Fair 2026"),
        ("ICML 2025: Vol. 42", "ICML 2026"),
        ("vLLM Summit 2026", "vLLM Summit"),
    ],
)
def test_years_ordinals_and_edition_nouns_do_not_change_identity(a: str, b: str) -> None:
    assert same_event(a, b), f"{a!r} and {b!r} should be the same event"


def test_word_order_does_not_change_identity() -> None:
    assert same_event(
        "KubeCon + CloudNativeCon Europe 2026",
        "CloudNativeCon + KubeCon Europe 2026",
    )


def test_punctuation_does_not_fuse_tokens() -> None:
    """``KubeCon+CloudNativeCon`` must not collapse into one token, or it
    stops matching the spaced form."""
    assert same_event("KubeCon+CloudNativeCon Europe 2026", KUBECON_EU_26)


@pytest.mark.parametrize("region", ["EU", "Europe", "EMEA", "APAC", "China"])
def test_region_is_stripped_from_the_series_key(region: str) -> None:
    """All regional variants of one franchise share a series key."""
    assert same_series(
        f"KubeCon + CloudNativeCon {region} 2026", KUBECON_NA_26
    )
    assert not same_event(
        f"KubeCon + CloudNativeCon {region} 2026", KUBECON_NA_26
    )


def test_abbreviated_names_do_NOT_auto_link() -> None:
    """A deliberate false negative.

    "KubeCon Europe" lacks the CloudNativeCon token, so it does not link to
    "KubeCon + CloudNativeCon North America". Matching is exact on the token
    set. A wrong link applies one conference's history to another, which is
    worse than no link — so this errs toward missing, and aliases are where
    the exceptions belong.
    """
    assert relationship("KubeCon Europe 2026", KUBECON_NA_26) == "unrelated"


# ---------------------------------------------------------------------------
# Properties
# ---------------------------------------------------------------------------
def test_same_event_implies_same_series() -> None:
    """An event is always within its own franchise. If this ever fails the
    two keys have drifted apart."""
    names = [KUBECON_EU_25, KUBECON_EU_26, KUBECON_NA_26, "NeurIPS 2026",
             "PyTorch Conference 2026", "vLLM Summit 2026"]
    for a in names:
        for b in names:
            if same_event(a, b):
                assert same_series(a, b), f"{a!r} vs {b!r}"


def test_relations_are_symmetric() -> None:
    names = [KUBECON_EU_25, KUBECON_EU_26, KUBECON_NA_26, "MLOps World 2026"]
    for a in names:
        for b in names:
            assert same_event(a, b) == same_event(b, a)
            assert same_series(a, b) == same_series(b, a)


def test_empty_and_junk_names_are_never_equal() -> None:
    """An empty key must not make everything match everything."""
    assert not same_event("", "")
    assert not same_series("", "")
    assert not same_event("2026", "2025")          # year only -> empty key
    assert not same_event("Annual Conference", "Annual Summit")


def test_keys_are_stable_and_readable() -> None:
    """The keys are inspectable on purpose — a human has to be able to see
    why two things matched."""
    assert event_key(KUBECON_EU_26) == event_key(KUBECON_EU_25)
    assert series_key(KUBECON_EU_26) == series_key(KUBECON_NA_26)
    assert event_key(KUBECON_EU_26) != event_key(KUBECON_NA_26)


# ---------------------------------------------------------------------------
# Against the labelled corpus
# ---------------------------------------------------------------------------
def test_corpus_series_relationships() -> None:
    """Every pair in the corpus must land in the right bucket."""
    from tests.fixtures import corpus as C

    names = [c["name"] for c in C.CONFERENCES]
    kubecons = [n for n in names if "KubeCon" in n]
    assert len(kubecons) == 3, "corpus should carry the three KubeCon rows"

    # all three share a series
    for a in kubecons:
        for b in kubecons:
            assert same_series(a, b)

    # exactly one pair is the same event: the two Europe editions
    same_event_pairs = {
        frozenset((a, b))
        for a in kubecons
        for b in kubecons
        if a != b and same_event(a, b)
    }
    assert len(same_event_pairs) == 1
    assert all("Europe" in n for n in next(iter(same_event_pairs)))


def test_no_unrelated_corpus_pair_is_linked() -> None:
    """Nothing outside the KubeCon family should link to anything else."""
    from tests.fixtures import corpus as C

    names = [c["name"] for c in C.CONFERENCES]
    for i, a in enumerate(names):
        for b in names[i + 1:]:
            if "KubeCon" in a and "KubeCon" in b:
                continue
            assert relationship(a, b) == "unrelated", f"{a!r} linked to {b!r}"


# ---------------------------------------------------------------------------
# The over-collapse bug: short names where the event-type noun IS the identity
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    ("a", "b"),
    [
        ("AI Summit 2026", "AI Expo 2026"),
        ("Data Conference 2026", "Data Days 2026"),
        ("Cloud Expo", "Cloud Summit"),
        ("Security Forum 2026", "Security Congress 2026"),
    ],
)
def test_two_word_names_do_not_collapse_to_one_token(a: str, b: str) -> None:
    """Stripping the event-type noun used to be unconditional.

    "AI Summit" and "AI Expo" both reduced to "ai", compared as the SAME
    event, and one conference's attendance history and verdict transplanted
    onto the other — the exact false-positive linking this module exists to
    prevent, produced by the module itself.

    The noun stays when dropping it would leave fewer than two tokens.
    """
    assert not same_event(a, b), f"{a!r} and {b!r} collapsed to the same event"
    assert not same_series(a, b)


def test_the_event_noun_is_still_dropped_when_the_name_survives_it() -> None:
    """The fix must not stop the noun being ignored where it is noise.

    Different years of "PyTorch Conference" are still one event.
    """
    assert same_event("PyTorch Conference 2026", "PyTorch Conference 2027")
    assert same_event("vLLM Summit 2026", "vLLM Summit")


def test_instance_markers_are_still_always_dropped() -> None:
    """Volume and ordinal markers are never identity, even on a short name.

    This is why the fix splits the two noun classes instead of just
    requiring a minimum token count: "ICML Vol. 42" must still reduce to
    "icml", or it stops matching plain "ICML".
    """
    assert same_event("ICML 2025: Vol. 42", "ICML 2026")
    assert same_event("12th Annual DevCon", "DevCon")


def test_no_key_is_ever_a_single_generic_word() -> None:
    """A one-token key like "ai" or "data" matches half the corpus."""
    for name in ("AI Summit 2026", "Data Conference", "Cloud Expo", "ML Workshop"):
        key = event_key(name)
        assert len(key.split()) >= 2, f"{name!r} produced the bare key {key!r}"
