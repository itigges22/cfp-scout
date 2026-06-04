"""Schemas for the talks library (v2)."""

from __future__ import annotations

from datetime import date, datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.common import READ_CONFIG, StrictBase

_VALID_FORMATS = frozenset(
    ["keynote", "talk", "panel", "workshop", "tutorial", "other"]
)
_VALID_SOURCE_TYPES = frozenset(["uploaded", "manual"])
_VALID_REVIEW_STATUSES = frozenset(["draft", "pending_review", "approved"])
_VALID_OUTCOMES = frozenset(["submitted", "accepted", "rejected", "withdrawn"])


# ---------------------------------------------------------------------------
# Talk
# ---------------------------------------------------------------------------


class TalkCreate(StrictBase):
    title: str = Field(min_length=1, max_length=500)
    abstract: str | None = None
    full_content: str | None = None
    source_type: str = "manual"
    file_path: str | None = None
    pillar_id: UUID | None = None
    primary_sme_id: UUID | None = None
    co_speaker_ids: list[UUID] = Field(default_factory=list)
    talk_format: str | None = None
    suggested_duration_minutes: int | None = Field(default=None, ge=1, le=600)
    review_status: str = "draft"
    is_active: bool = True


class TalkUpdate(StrictBase):
    title: str | None = Field(default=None, min_length=1, max_length=500)
    abstract: str | None = None
    full_content: str | None = None
    pillar_id: UUID | None = None
    primary_sme_id: UUID | None = None
    co_speaker_ids: list[UUID] | None = None
    talk_format: str | None = None
    suggested_duration_minutes: int | None = Field(default=None, ge=1, le=600)
    review_status: str | None = None
    is_active: bool | None = None


class TalkTagRead(BaseModel):
    model_config = READ_CONFIG

    id: UUID
    name: str
    color: str | None = None
    created_at: datetime


class TalkTopicRead(BaseModel):
    id: UUID
    name: str
    weight: float = 1.0


class TalkSubmissionRead(BaseModel):
    model_config = READ_CONFIG

    id: UUID
    talk_id: UUID
    conference_id: UUID
    submitted_by_sme_id: UUID | None = None
    submitted_at: date | None = None
    outcome: str | None = None
    notes: str | None = None
    created_at: datetime


class TalkRead(BaseModel):
    model_config = READ_CONFIG

    id: UUID
    title: str
    abstract: str | None = None
    full_content: str | None = None
    source_type: str
    file_path: str | None = None
    pillar_id: UUID | None = None
    primary_sme_id: UUID | None = None
    co_speaker_ids: list[UUID] = []
    talk_format: str | None = None
    suggested_duration_minutes: int | None = None
    review_status: str
    is_active: bool
    created_at: datetime
    updated_at: datetime

    tags: list[TalkTagRead] = []
    topics: list[TalkTopicRead] = []
    submissions: list[TalkSubmissionRead] = []

    # Derived from len(submissions). Populated by the service layer.
    times_applied: int = 0
    is_flagged: bool = False


# ---------------------------------------------------------------------------
# Talk submission
# ---------------------------------------------------------------------------


class TalkSubmissionCreate(StrictBase):
    conference_id: UUID
    submitted_by_sme_id: UUID | None = None
    submitted_at: date | None = None
    outcome: str | None = None
    notes: str | None = None


class TalkSubmissionUpdate(StrictBase):
    outcome: str | None = None
    notes: str | None = None
    submitted_at: date | None = None


# ---------------------------------------------------------------------------
# Reuse check
# ---------------------------------------------------------------------------


class SeriesReuseItem(BaseModel):
    series_id: UUID
    series_name: str
    submission_count: int


class ReuseCheckResult(BaseModel):
    talk_id: UUID
    submission_count_12m: int
    series_reuse: list[SeriesReuseItem] = []
    risk_level: str  # 'low' | 'medium' | 'high'
    warning: str | None = None


# ---------------------------------------------------------------------------
# Talk tag
# ---------------------------------------------------------------------------


class TalkTagCreate(StrictBase):
    name: str = Field(min_length=1, max_length=100)
    color: str | None = None


class TalkTagUpdate(StrictBase):
    name: str | None = Field(default=None, min_length=1, max_length=100)
    color: str | None = None
