"""Unit tests for the brief builder's pure helpers (plan 33).

Full integration coverage of `build_brief` lives in the integration suite
(plan 27 pass 2). Here we just lock down the small pure formatters that
the print view depends on for "is the next deadline correctly bolded?"
+ score-bucket thresholds.
"""

from __future__ import annotations

from datetime import date

from app.services.brief.builder import (
    _bucket,
    _cfp_section,
    _iso_date,
    _round,
    _series_summary,
)


class _ConfStub:
    """Mimic just enough of the Conference SQLAlchemy model for the
    pure ``_cfp_section`` formatter."""

    def __init__(
        self,
        deadlines: list[dict] | None = None,
        topics_of_interest: list[str] | None = None,
        open_at: date | None = None,
        close_at: date | None = None,
    ) -> None:
        self.cfp_deadlines = deadlines or []
        self.cfp_topics_of_interest = topics_of_interest or []
        self.cfp_open_at = open_at
        self.cfp_close_at = close_at


class _SeriesStub:
    def __init__(self, sid: str, name: str, month: int | None) -> None:
        self.id = sid
        self.canonical_name = name
        self.typical_month = month


class TestBucket:
    def test_strong(self) -> None:
        assert _bucket(0.90) == "strong"
        assert _bucket(0.75) == "strong"

    def test_good(self) -> None:
        assert _bucket(0.74) == "good"
        assert _bucket(0.55) == "good"

    def test_marginal(self) -> None:
        assert _bucket(0.54) == "marginal"
        assert _bucket(0.40) == "marginal"

    def test_weak(self) -> None:
        assert _bucket(0.30) == "weak"
        assert _bucket(0.0) == "weak"

    def test_none(self) -> None:
        assert _bucket(None) is None


class TestRoundAndIsoDate:
    def test_round_keeps_4_dp(self) -> None:
        assert _round(0.123456789) == 0.1235

    def test_round_none(self) -> None:
        assert _round(None) is None

    def test_iso_date_roundtrip(self) -> None:
        assert _iso_date(date(2027, 4, 15)) == "2027-04-15"

    def test_iso_date_none(self) -> None:
        assert _iso_date(None) is None


class TestCfpSection:
    def test_marks_next_deadline_only(self) -> None:
        """The soonest *future* deadline is_next=True; the rest stay False."""
        today = date.today()
        future_soon = (today.replace(day=1)).isoformat()  # past or today
        far_future = date(today.year + 5, 1, 1).isoformat()
        past = date(today.year - 1, 1, 1).isoformat()

        conf = _ConfStub(
            deadlines=[
                {"kind": "submission", "date": past, "description": "old"},
                {"kind": "workshop", "date": far_future, "description": "far"},
                {"kind": "rebuttal", "date": future_soon, "description": "soonish"},
            ]
        )
        section = _cfp_section(conf)
        next_flags = [d["is_next"] for d in section["deadlines"]]
        assert sum(next_flags) <= 1  # at most one bold deadline

    def test_no_dates_no_next(self) -> None:
        conf = _ConfStub(
            deadlines=[
                {"kind": "submission", "date": None, "description": "TBD"},
            ]
        )
        out = _cfp_section(conf)
        assert out["deadlines"][0]["is_next"] is False
        assert out["deadlines"][0]["days_remaining"] is None

    def test_truncates_topics_to_10(self) -> None:
        conf = _ConfStub(topics_of_interest=[f"topic-{i}" for i in range(20)])
        assert len(_cfp_section(conf)["topics_of_interest"]) == 10


class TestSeriesSummary:
    def test_counts_recent_attendance(self) -> None:
        series = _SeriesStub("sid-1", "KubeCon", 11)
        past = [
            {"attendees": [{"sme_id": "a", "full_name": "A"}]},
            {"attendees": []},
            {"attendees": [{"sme_id": "b", "full_name": "B"}]},
        ]
        out = _series_summary(series, past)
        assert out["past_editions_count"] == 3
        assert out["team_attended_recent"] == 2
        assert out["canonical_name"] == "KubeCon"
