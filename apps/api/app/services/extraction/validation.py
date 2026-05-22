"""Validation rules + confidence scoring (plan 15).

Rules apply AFTER Pydantic validation. They model business logic that
Pydantic can't easily express — e.g. "every CFP deadline must precede the
event start". Failed rules don't reject the row outright; they reduce the
final confidence so the row routes to ``needs_review`` or ``quarantined``.

This is intentional: scraped pages are messy. Rejecting "submission deadline
after start date" outright would drop legitimate-but-misparsed pages we'd
rather human-review.

Structural confidence — separate from the LLM's self-assessment — is the
fraction of core fields the model populated. Final confidence = the lower
of LLM and structural.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

import pycountry

from app.services.extraction.schema import ExtractedConference

# ---------------------------------------------------------------------------
# Confidence tuning knobs. Easy to grep + tweak after first 50 conferences.
# ---------------------------------------------------------------------------
PENALTY_DATE_ORDER = 0.20  # start_date >= end_date
PENALTY_DEADLINE_PAST_START = 0.15  # cfp_deadline >= start_date
PENALTY_DATE_OUT_OF_RANGE = 0.25  # start_date far past or far future
PENALTY_BAD_COUNTRY = 0.10  # location_country not ISO-3166
PENALTY_ACCEPTANCE_BAD = 0.10  # acceptance_rate_percent outside 0..100

# Range checks: ignore "old" conferences and unrealistic "far future".
PAST_HORIZON_DAYS = 90
FUTURE_HORIZON_DAYS = 365 * 3

# Routing thresholds. Plan 15 calls out 0.85 / 0.50 as starting points.
DISCOVERED_THRESHOLD = 0.85
NEEDS_REVIEW_THRESHOLD = 0.50


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------
@dataclass(slots=True, frozen=True)
class RuleResult:
    rule: str
    passed: bool
    penalty: float = 0.0
    detail: str | None = None


@dataclass(slots=True)
class ValidationOutcome:
    structural_confidence: float
    rule_results: list[RuleResult]
    rule_penalty: float
    final_confidence: float
    status: str  # "discovered" / "needs_review" / "quarantined"

    @property
    def quarantine_reasons(self) -> list[str]:
        """Subset of failed rules' identifiers — useful for plan 15 pass 2's
        ``quarantine_reasons`` table. For pass 1 we just stash the list in
        the ingest_jobs.stats payload."""
        return [r.rule for r in self.rule_results if not r.passed]


# ---------------------------------------------------------------------------
# Core scorer
# ---------------------------------------------------------------------------
def validate_and_score(
    extracted: ExtractedConference, *, today: date | None = None
) -> ValidationOutcome:
    """Compute structural + business-rule confidence and choose a status."""
    today = today or date.today()

    structural = _structural_confidence(extracted)
    rule_results = _apply_rules(extracted, today=today)
    rule_penalty = sum(r.penalty for r in rule_results if not r.passed)

    # Combine: take the lower of LLM and structural, then subtract rule penalties.
    llm = extracted.confidence
    base = min(llm, structural)
    final = max(0.0, base - rule_penalty)

    if final >= DISCOVERED_THRESHOLD:
        status = "discovered"
    elif final >= NEEDS_REVIEW_THRESHOLD:
        status = "needs_review"
    else:
        status = "quarantined"

    return ValidationOutcome(
        structural_confidence=structural,
        rule_results=rule_results,
        rule_penalty=rule_penalty,
        final_confidence=final,
        status=status,
    )


# ---------------------------------------------------------------------------
# Structural confidence (field-coverage)
# ---------------------------------------------------------------------------
# Weighted because not all fields are equally informative. ``name`` is
# already a required input (won't fail) so it gets a smaller weight.
_FIELD_WEIGHTS: dict[str, float] = {
    "name": 0.10,
    "start_date": 0.20,
    "end_date": 0.10,
    "location_city_or_virtual": 0.10,
    "location_country_or_virtual": 0.10,
    "topics": 0.10,
    "cfp_close_at_or_deadlines": 0.20,
    "website": 0.10,
}


def _structural_confidence(e: ExtractedConference) -> float:
    score = 0.0

    if e.name and e.name != "Unknown":
        score += _FIELD_WEIGHTS["name"]
    if e.start_date:
        score += _FIELD_WEIGHTS["start_date"]
    if e.end_date:
        score += _FIELD_WEIGHTS["end_date"]
    if e.location_city or e.is_virtual:
        score += _FIELD_WEIGHTS["location_city_or_virtual"]
    if e.location_country or e.is_virtual:
        score += _FIELD_WEIGHTS["location_country_or_virtual"]
    if e.topics:
        score += _FIELD_WEIGHTS["topics"]
    if e.cfp_close_at or e.cfp_deadlines:
        score += _FIELD_WEIGHTS["cfp_close_at_or_deadlines"]
    if e.website:
        score += _FIELD_WEIGHTS["website"]

    return round(score, 3)


# ---------------------------------------------------------------------------
# Rule set
# ---------------------------------------------------------------------------
def _apply_rules(e: ExtractedConference, *, today: date) -> list[RuleResult]:
    rs: list[RuleResult] = []

    # 1. date ordering
    if e.start_date and e.end_date:
        if e.start_date > e.end_date:
            rs.append(
                RuleResult(
                    rule="date_order",
                    passed=False,
                    penalty=PENALTY_DATE_ORDER,
                    detail=f"start_date {e.start_date} > end_date {e.end_date}",
                )
            )
        else:
            rs.append(RuleResult(rule="date_order", passed=True))

    # 2. every deadline must precede start_date
    if e.start_date and e.cfp_deadlines:
        late = [d for d in e.cfp_deadlines if d.deadline_date >= e.start_date]
        if late:
            rs.append(
                RuleResult(
                    rule="deadline_before_start",
                    passed=False,
                    penalty=PENALTY_DEADLINE_PAST_START,
                    detail=f"{len(late)} deadline(s) on or after start_date",
                )
            )
        else:
            rs.append(RuleResult(rule="deadline_before_start", passed=True))

    # 3. plausible date range
    if e.start_date:
        if e.start_date < today - timedelta(days=PAST_HORIZON_DAYS):
            rs.append(
                RuleResult(
                    rule="date_in_past",
                    passed=False,
                    penalty=PENALTY_DATE_OUT_OF_RANGE,
                    detail=f"start_date {e.start_date} more than {PAST_HORIZON_DAYS}d ago",
                )
            )
        elif e.start_date > today + timedelta(days=FUTURE_HORIZON_DAYS):
            rs.append(
                RuleResult(
                    rule="date_too_far_future",
                    passed=False,
                    penalty=PENALTY_DATE_OUT_OF_RANGE,
                    detail=f"start_date {e.start_date} > {FUTURE_HORIZON_DAYS}d out",
                )
            )
        else:
            rs.append(RuleResult(rule="date_range_plausible", passed=True))

    # 4. ISO-3166 country code
    if e.location_country:
        if not _is_iso_alpha2(e.location_country):
            rs.append(
                RuleResult(
                    rule="country_code_iso",
                    passed=False,
                    penalty=PENALTY_BAD_COUNTRY,
                    detail=f"unknown country code {e.location_country!r}",
                )
            )
        else:
            rs.append(RuleResult(rule="country_code_iso", passed=True))

    # 5. acceptance rate sanity (Pydantic already enforces 0..100; we still
    #    flag implausible-but-valid values like 0 or 100 in case the model
    #    hallucinates them).
    if e.acceptance_rate_percent is not None and (
        e.acceptance_rate_percent <= 0 or e.acceptance_rate_percent >= 100
    ):
        rs.append(
            RuleResult(
                rule="acceptance_rate_implausible",
                passed=False,
                penalty=PENALTY_ACCEPTANCE_BAD,
                detail=f"acceptance_rate_percent={e.acceptance_rate_percent}",
            )
        )
    elif e.acceptance_rate_percent is not None:
        rs.append(RuleResult(rule="acceptance_rate_implausible", passed=True))

    return rs


# Cached set for the country-code lookup.
_ISO_ALPHA2: frozenset[str] = frozenset(
    c.alpha_2 for c in pycountry.countries if hasattr(c, "alpha_2")
)


def _is_iso_alpha2(code: str) -> bool:
    return code.upper() in _ISO_ALPHA2
