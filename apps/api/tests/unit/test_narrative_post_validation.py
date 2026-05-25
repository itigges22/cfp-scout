"""Tests for the SME-fit-narrative quote-guard (plan 19)."""

from __future__ import annotations

from app.services.matcher.sme_narrative import (
    UNAVAILABLE,
    _inputs_blob,
    _post_validate,
)


class _Conf:
    name = "NeurIPS 2027"
    topics = ["llm", "rag"]
    cfp_topics_of_interest = ["agents"]
    venue = "Vancouver Convention Centre"


class _Sme:
    full_name = "Alice Chen"
    team = "Marketing"
    expertise_areas = ["retrieval-augmented generation", "vector databases"]


def _blob() -> str:
    return _inputs_blob(conference=_Conf(), sme=_Sme(), bio="Alice has spoken on RAG.")


class TestPostValidate:
    def test_empty_narrative_fails(self) -> None:
        assert _post_validate("", _blob()) is False

    def test_unavailable_sentinel_fails(self) -> None:
        assert _post_validate(UNAVAILABLE, _blob()) is False

    def test_no_quotes_passes(self) -> None:
        text = "Alice is a great fit for this conference. She covers the right topics."
        assert _post_validate(text, _blob()) is True

    def test_quote_present_in_inputs_passes(self) -> None:
        text = 'Alice covers "RAG" topics in depth.'
        assert _post_validate(text, _blob()) is True

    def test_fabricated_quote_fails(self) -> None:
        text = 'Alice gave a talk on "interpretive dance for transformers" last year.'
        assert _post_validate(text, _blob()) is False

    def test_apostrophes_in_bio_dont_falsely_match(self) -> None:
        # Apostrophes are intentionally NOT detected as quotes (too noisy).
        text = "Alice's work covers retrieval augmented generation broadly."
        assert _post_validate(text, _blob()) is True

    def test_case_insensitive_matching(self) -> None:
        text = 'Alice contributes to "VECTOR DATABASES" research.'
        assert _post_validate(text, _blob()) is True

    def test_overlong_narrative_fails(self) -> None:
        text = "A" * 2000  # way over MAX_NARRATIVE_CHARS * 1.5
        assert _post_validate(text, _blob()) is False
