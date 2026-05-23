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

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator


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


# Keyword → enum mapping for free-form LLM output. The LLM regularly
# returns variants like "Submission Start", "Abstract Registration",
# "Camera-Ready", etc. We try a longest-keyword-first match against
# lowercased input.
_KIND_KEYWORDS: tuple[tuple[str, CfpDeadlineKind], ...] = (
    ("early bird", CfpDeadlineKind.EARLY_BIRD),
    ("early-bird", CfpDeadlineKind.EARLY_BIRD),
    ("abstract", CfpDeadlineKind.ABSTRACT),
    ("submission", CfpDeadlineKind.SUBMISSION),
    ("paper", CfpDeadlineKind.SUBMISSION),
    ("rebuttal", CfpDeadlineKind.SUBMISSION),
    ("camera-ready", CfpDeadlineKind.SUBMISSION),
    ("camera ready", CfpDeadlineKind.SUBMISSION),
    ("poster", CfpDeadlineKind.POSTER),
    ("workshop", CfpDeadlineKind.WORKSHOP),
    ("tutorial", CfpDeadlineKind.TUTORIAL),
    ("demo", CfpDeadlineKind.DEMO),
    ("sponsorship", CfpDeadlineKind.SPONSORSHIP),
    ("sponsor", CfpDeadlineKind.SPONSORSHIP),
)


def _normalize_kind(raw: object) -> str:
    """Map a free-form string to a canonical CfpDeadlineKind value.

    Falls back to 'other' if no keyword matches. Bare enum values pass
    through unchanged so canonical input is cheap.
    """
    if not isinstance(raw, str):
        return raw  # type: ignore[return-value]
    s = raw.strip().lower()
    # Already canonical?
    for k in CfpDeadlineKind:
        if s == k.value:
            return s
    for kw, enum_val in _KIND_KEYWORDS:
        if kw in s:
            return enum_val.value
    return CfpDeadlineKind.OTHER.value


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
    """One entry inside ``conferences.cfp_deadlines``.

    Tolerant of common LLM variants on input — the LLM often returns
    ``type`` instead of ``kind`` and ``deadline`` instead of
    ``deadline_date``, and uses free-form strings ("Submission Start")
    rather than the canonical enum value. The ``before`` validator
    normalizes those before strict validation runs.
    """

    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)

    kind: CfpDeadlineKind
    deadline_date: date
    description: ShortFreeText | None = None
    # "talks" / "workshops" / "all" / None. Free-text per plan 04; no enum here.
    applies_to: ShortFreeText | None = None

    @model_validator(mode="before")
    @classmethod
    def _accept_llm_variants(cls, data: object) -> object:
        if not isinstance(data, dict):
            return data
        # Field-name aliases. The LLM returns whatever it feels like:
        # `kind` (canonical), `type`, `name`, `phase`, `label`, …
        if "kind" not in data:
            for alias in ("type", "name", "phase", "label", "category"):
                if alias in data:
                    data["kind"] = data[alias]
                    # We pop only if we won't also use the alias as
                    # description — leave 'name' since it's often
                    # the human-readable form ("Abstract submission
                    # deadline") that doubles as a description.
                    if alias != "name":
                        data.pop(alias, None)
                    break
        # `name` was likely the descriptive label — keep as description
        # if we have no description yet.
        if "description" not in data and "name" in data and data.get("name") != data.get("kind"):
            data["description"] = data.pop("name", None)
        elif "name" in data:
            # If we already used name → kind above, drop the redundant.
            data.pop("name", None)

        if "deadline_date" not in data:
            for alias in ("deadline", "date", "due", "due_date"):
                if alias in data:
                    data["deadline_date"] = data.pop(alias)
                    break

        # Last-resort: derive `kind` from `description` if the LLM didn't
        # give us a separate one ("Abstract submission deadline" →
        # 'abstract'). Better than failing the whole extraction over a
        # default-to-'other' value.
        if "kind" not in data and "description" in data:
            data["kind"] = _normalize_kind(data["description"])

        # Normalize kind keyword + ISO-datetime → date.
        if "kind" in data:
            data["kind"] = _normalize_kind(data["kind"])
        else:
            # Truly nothing usable — fall back to OTHER so the row still
            # validates. Better to keep the deadline_date with kind=other
            # than throw the whole conference away.
            data["kind"] = CfpDeadlineKind.OTHER.value
        if isinstance(data.get("deadline_date"), str):
            raw_d = data["deadline_date"]
            if "T" in raw_d:
                data["deadline_date"] = raw_d.split("T", 1)[0]
        return data


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

    # LLMs regularly add useful-but-not-modelled fields (abbreviation,
    # series, hashtag, etc). Don't reject the whole extraction for that —
    # ignore the extras and keep the validated fields.
    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)

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
