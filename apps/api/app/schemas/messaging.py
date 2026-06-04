"""Messaging-document input schemas.

A messaging document captures the product's positioning text the matcher
scores conferences against. Two source kinds:

  ``structured``  — fields entered manually.
  ``pdf``         — fields extracted from an uploaded PDF via LLM, then
                    reviewed and saved by the operator.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated
from uuid import UUID as UUIDType

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.schemas.common import (
    READ_CONFIG,
    ElevatorPitch,
    ListItem,
    MessagingSourceType,
    ShortNote,
    ShortTitle,
    StrictBase,
    TalkingPoint,
)

DOC_KIND_VALUES = ("gtm_strategy", "content_roadmap", "other")


class MessagingDocumentBase(StrictBase):
    """Fields common to create + update."""

    title: ShortTitle
    source_type: MessagingSourceType
    doc_kind: Annotated[str, Field(default="other", max_length=30)] = "other"

    elevator_pitch: ElevatorPitch
    target_personas: Annotated[list[ListItem], Field(min_length=1, max_length=8)]
    key_themes: Annotated[list[ListItem], Field(min_length=3, max_length=12)]
    talking_points: Annotated[list[TalkingPoint], Field(min_length=3, max_length=15)]

    differentiators: Annotated[list[ListItem], Field(max_length=8)] = []
    competitive_position: Annotated[ShortNote, Field(default="")] = ""

    pillar_id: UUIDType | None = None
    is_active: bool = True

    @model_validator(mode="after")
    def _check_source_type_consistency(self) -> MessagingDocumentBase:
        return self


class MessagingDocumentCreate(MessagingDocumentBase):
    """POST body. Accepts both structured and pdf source types."""


class MessagingDocumentUpdate(MessagingDocumentBase):
    """PUT body. Same shape; the api wires partial-update vs replace
    semantics in plan 09. The shape stays strict either way."""


class MessagingDocumentRead(MessagingDocumentBase):
    """Read response. Adds server-managed fields + relaxes extras for ORM serialization."""

    model_config = READ_CONFIG

    id: UUIDType
    file_path: str | None = None
    created_at: datetime
    updated_at: datetime


class MessagingDocUploadPreview(BaseModel):
    """Relaxed preview returned by the PDF upload endpoint.

    No min_length constraints — the LLM may not extract every field perfectly.
    The operator reviews and edits before saving via the normal create endpoint.
    """

    model_config = ConfigDict(extra="ignore")

    doc_kind: str = "other"
    title: str = ""
    elevator_pitch: str = ""
    target_personas: list[str] = []
    key_themes: list[str] = []
    talking_points: list[str] = []
    differentiators: list[str] = []
    competitive_position: str = ""
