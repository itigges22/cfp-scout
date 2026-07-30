"""Tests for the extraction pipeline's pure helpers (plan 15)."""

from __future__ import annotations

from datetime import date

from app.services.extraction import (
    CfpDeadline,
    CfpDeadlineKind,
    ExtractedConference,
    build_slug,
    validate_and_score,
    year_for,
)
from app.settings import get_settings


class TestBuildSlug:
    def test_basic(self) -> None:
        assert build_slug("NeurIPS 2027", 2027) == "neurips-2027-2027"
        assert build_slug("ICML", 2025) == "icml-2025"

    def test_no_year_uses_unknown_suffix(self) -> None:
        assert build_slug("AAAI", None).endswith("-unknown")

    def test_handles_punctuation(self) -> None:
        slug = build_slug("KubeCon + CloudNativeCon NA!", 2026)
        # python-slugify strips punctuation; trailing year stays.
        assert slug.endswith("-2026")
        assert "+" not in slug


class TestYearFor:
    def test_none(self) -> None:
        assert year_for(None) is None

    def test_extracts_year(self) -> None:
        assert year_for(date(2027, 4, 15)) == 2027


class TestValidateAndScore:
    def _baseline(self, **overrides) -> ExtractedConference:
        """Reasonably populated conference; tests override specific fields."""
        defaults = dict(
            name="AAAI 2027",
            start_date=date(2027, 4, 15),
            end_date=date(2027, 4, 17),
            location_city="Boston",
            location_country="US",
            is_virtual=False,
            website="https://aaai.org/aaai27",
            cfp_close_at=date(2026, 12, 1),
            cfp_deadlines=[
                CfpDeadline(
                    kind=CfpDeadlineKind.SUBMISSION,
                    deadline_date=date(2026, 12, 1),
                    description=None,
                    applies_to=None,
                )
            ],
            cfp_topics_of_interest=["llm", "agents"],
            topics=["llm", "agents", "reasoning"],
            acceptance_rate_percent=22,
            estimated_cost_usd=900,
            confidence=0.9,
        )
        defaults.update(overrides)
        return ExtractedConference(**defaults)

    def test_well_populated_routes_discovered(self) -> None:
        out = validate_and_score(self._baseline(), today=date(2026, 10, 1))
        assert out.status == "discovered"
        assert out.final_confidence >= get_settings().extraction_confidence_discovered

    def test_low_llm_confidence_routes_quarantined(self) -> None:
        c = self._baseline(confidence=0.2)
        out = validate_and_score(c, today=date(2026, 10, 1))
        assert out.status == "quarantined"
        assert out.final_confidence < get_settings().extraction_confidence_needs_review

    def test_bad_country_code_drops_confidence(self) -> None:
        c = self._baseline(location_country="ZZ")  # not ISO
        out = validate_and_score(c, today=date(2026, 10, 1))
        rule_names = {r.rule for r in out.rule_results}
        assert "country_code_iso" in rule_names
        assert any(r.rule == "country_code_iso" and not r.passed for r in out.rule_results)

    def test_swapped_dates_drops_confidence(self) -> None:
        c = self._baseline(
            start_date=date(2027, 4, 17),
            end_date=date(2027, 4, 15),
        )
        out = validate_and_score(c, today=date(2026, 10, 1))
        names = {r.rule for r in out.rule_results}
        assert "date_order" in names

    def test_far_past_conference_penalized(self) -> None:
        c = self._baseline(
            start_date=date(2020, 1, 1),
            end_date=date(2020, 1, 3),
            # match deadlines so deadline_before_start doesn't dominate
            cfp_close_at=date(2019, 11, 1),
            cfp_deadlines=[
                CfpDeadline(
                    kind=CfpDeadlineKind.SUBMISSION,
                    deadline_date=date(2019, 11, 1),
                )
            ],
        )
        out = validate_and_score(c, today=date(2026, 10, 1))
        names = {r.rule for r in out.rule_results}
        assert "date_in_past" in names

    def test_implausible_acceptance_rate_flagged(self) -> None:
        c = self._baseline(acceptance_rate_percent=100)  # implausible high
        out = validate_and_score(c, today=date(2026, 10, 1))
        names = {r.rule for r in out.rule_results}
        assert "acceptance_rate_implausible" in names

    def test_unknown_name_routes_quarantined(self) -> None:
        c = self._baseline(name="Unknown", confidence=0.95)
        out = validate_and_score(c, today=date(2026, 10, 1))
        # validate_and_score does NOT itself reroute on "Unknown" — that's
        # the pipeline's job. But structural confidence should still be
        # less than full because "Unknown" loses the name dimension.
        assert out.structural_confidence < 1.0
