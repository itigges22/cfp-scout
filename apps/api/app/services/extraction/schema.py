"""Pydantic schema for the LLM's extracted conference output (plan 15).

This is the contract between the LLM and the database. The prompt sends the
model a JSON schema string derived from these classes; the model returns a
JSON object that we parse + validate before any DB write.

**This is the only place in Scout where LLM output crosses into typed data**.
User-entered data has its own (stricter) guardrails in :mod:`app.schemas`.
Scraped pages are messy, so we accept partial / unknown values here and
score the result with a confidence number rather than rejecting outright.
"""

from __future__ import annotations

from datetime import date
from enum import StrEnum
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints


# ---------------------------------------------------------------------------
# Enums + type aliases
# ---------------------------------------------------------------------------
class CfpDeadlineKind(StrEnum):
    """Recognized kinds of CFP deadline."""

    SUBMISSION = "submission"
    ABSTRACT = "abstract"
    POSTER = "poster"
    WORKSHOP = "workshop"
    TUTORIAL = "tutorial"
    DEMO = "demo"
    SPONSORSHIP = "sponsorship"
    EARLY_BIRD = "early_bird"
    OTHER = "other"


# Names get extra trim + cap that matches the conferences.name column (200).
ExtractedName = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=3, max_length=200)
]
ShortFreeText = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)
]
Topic = Annotated[str, StringConstraints(strip_whitespace=True, min_length=2, max_length=100)]


# ---------------------------------------------------------------------------
# Nested types
# ---------------------------------------------------------------------------
class CfpDeadline(BaseModel):
    """One entry inside ``conferences.cfp_deadlines``."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    kind: CfpDeadlineKind
    deadline_date: date
    description: ShortFreeText | None = None
    # "talks" / "workshops" / "all" / None. Free-text per plan 04; no enum here.
    applies_to: ShortFreeText | None = None


# ---------------------------------------------------------------------------
# Top-level extraction envelope
# ---------------------------------------------------------------------------
class ExtractedConference(BaseModel):
    """Strict shape returned by the LLM for a single page.

    Every field is optional except ``name`` — pages that can't even produce
    a name are quarantined upstream (confidence floor). ``confidence`` is
    the LLM's own self-assessment 0..1; the pipeline multiplies it by a
    structural confidence computed from field-coverage.
    """

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    name: ExtractedName

    start_date: date | None = None
    end_date: date | None = None

    location_city: (
        Annotated[str, StringConstraints(strip_whitespace=True, max_length=120)] | None
    ) = None
    # ISO-3166-1 alpha-2 (upper). Validator enforces.
    location_country: (
        Annotated[str, StringConstraints(strip_whitespace=True, min_length=2, max_length=2)] | None
    ) = None
    is_virtual: bool = False
    venue: Annotated[str, StringConstraints(strip_whitespace=True, max_length=200)] | None = None
    website: Annotated[str, StringConstraints(strip_whitespace=True, max_length=500)] | None = None

    cfp_open_at: date | None = None
    cfp_close_at: date | None = None
    cfp_deadlines: list[CfpDeadline] = Field(default_factory=list, max_length=20)
    cfp_topics_of_interest: list[Topic] = Field(default_factory=list, max_length=50)

    topics: list[Topic] = Field(default_factory=list, max_length=30)

    acceptance_rate_percent: int | None = Field(default=None, ge=0, le=100)
    estimated_cost_usd: int | None = Field(default=None, ge=0, le=100_000)

    # LLM's self-assessed confidence 0..1.
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)
