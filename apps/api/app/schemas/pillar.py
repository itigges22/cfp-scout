"""Schemas for pillar system (v2)."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.common import READ_CONFIG, StrictBase


# ---------------------------------------------------------------------------
# Pillar read (existing StrategicPillar + aggregate counts)
# ---------------------------------------------------------------------------


class PillarRead(BaseModel):
    model_config = READ_CONFIG

    id: UUID
    name: str
    description: str
    enriched_description: str | None = None
    display_order: int
    created_at: datetime
    updated_at: datetime

    # Aggregate counts populated by service layer
    sme_count: int = 0
    talk_count: int = 0
    audience_count: int = 0
    conference_count: int = 0


class PillarCreate(StrictBase):
    name: str = Field(min_length=2, max_length=80)
    description: str = Field(min_length=2)
    display_order: int | None = None


class PillarUpdate(StrictBase):
    name: str = Field(min_length=2, max_length=80)
    description: str = Field(min_length=2)


# ---------------------------------------------------------------------------
# Pillar → SME link
# ---------------------------------------------------------------------------


class SmePillarLink(StrictBase):
    is_primary: bool = False


class SmePillarRead(BaseModel):
    model_config = READ_CONFIG

    sme_id: UUID
    pillar_id: UUID
    is_primary: bool


# ---------------------------------------------------------------------------
# Content Roadmap
# ---------------------------------------------------------------------------


class RoadmapEntryCreate(StrictBase):
    quarter: str = Field(min_length=1, max_length=20)
    goals: list[str] = Field(default_factory=list)
    owner_label: str | None = Field(default=None, max_length=100)
    notes: str | None = None


class RoadmapEntryUpdate(StrictBase):
    quarter: str | None = Field(default=None, min_length=1, max_length=20)
    goals: list[str] | None = None
    owner_label: str | None = None
    notes: str | None = None


class RoadmapEntryRead(BaseModel):
    model_config = READ_CONFIG

    id: UUID
    pillar_id: UUID
    quarter: str
    goals: list[str] = []
    owner_label: str | None = None
    notes: str | None = None
    created_at: datetime
    updated_at: datetime


# ---------------------------------------------------------------------------
# GTM Strategy
# ---------------------------------------------------------------------------


class GtmStrategyCreate(StrictBase):
    objective: str | None = None
    key_messages: list[str] = Field(default_factory=list)
    target_audience_ids: list[UUID] = Field(default_factory=list)
    notes: str | None = None


class GtmStrategyRead(BaseModel):
    model_config = READ_CONFIG

    id: UUID
    pillar_id: UUID
    objective: str | None = None
    key_messages: list[str] = []
    target_audience_ids: list[UUID] = []
    notes: str | None = None
    version: int
    created_at: datetime
    updated_at: datetime
