"""Import attendee names match the roster forgivingly but never guess."""

from __future__ import annotations

from types import SimpleNamespace

from app.services.conferences import match_sme_by_name


def _roster(*names: str):
    return [SimpleNamespace(full_name=n) for n in names]


def test_exact_match_case_insensitive() -> None:
    r = _roster("Cedric Cylburn", "Isaac Tigges")
    assert match_sme_by_name("cedric cylburn", r).full_name == "Cedric Cylburn"


def test_unique_first_name_matches() -> None:
    r = _roster("Cedric Cylburn", "Isaac Tigges")
    assert match_sme_by_name("Cedric", r).full_name == "Cedric Cylburn"


def test_ambiguous_first_name_links_nobody() -> None:
    r = _roster("Cedric Cylburn", "Cedric Alexander")
    assert match_sme_by_name("Cedric", r) is None


def test_first_plus_last_initial() -> None:
    r = _roster("Cedric Cylburn", "Cedric Alexander")
    assert match_sme_by_name("Cedric C", r).full_name == "Cedric Cylburn"


def test_token_prefixes() -> None:
    r = _roster("Cedric Cylburn", "Isaac Tigges")
    assert match_sme_by_name("ced cyl", r).full_name == "Cedric Cylburn"


def test_unknown_name_links_nobody() -> None:
    r = _roster("Cedric Cylburn")
    assert match_sme_by_name("Totally Unknown", r) is None
    assert match_sme_by_name("", r) is None
