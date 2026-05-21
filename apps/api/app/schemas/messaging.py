"""Messaging-document input schemas.

A messaging document captures the product's positioning text the matcher
scores conferences against. Two source kinds:

  ``structured``  — every field is required and typed; the recommended path.
  ``pdf``         — the metadata fields below are STILL required; the PDF
                    contributes raw text for embedding, but it never replaces
                    structured input.

See ``PLANS/phase-1/05-data-input-guardrails.md`` for the rules.
"""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from pydantic import Field, model_validator

from app.schemas.common import (
    ElevatorPitch,
    ListItem,
    MessagingSourceType,
    ShortNote,
    ShortTitle,
    StrictBase,
    TalkingPoint,
)


class MessagingDocumentBase(StrictBase):
    """Fields common to create + update."""

    title: ShortTitle
    source_type: MessagingSourceType

    elevator_pitch: ElevatorPitch
    target_personas: Annotated[list[ListItem], Field(min_length=1, max_length=8)]
    key_themes: Annotated[list[ListItem], Field(min_length=3, max_length=12)]
    talking_points: Annotated[list[TalkingPoint], Field(min_length=3, max_length=15)]

    differentiators: Annotated[list[ListItem], Field(max_length=8)] = []
    competitive_position: Annotated[ShortNote, Field(default="")] = ""

    is_active: bool = True

    @model_validator(mode="after")
    def _check_source_type_consistency(self) -> "MessagingDocumentBase":
        # `file_path` is set by the PDF upload flow (plan 12), not by this
        # schema. We just make sure the source_type matches what callers can
        # legitimately set here. PDF uploads go through a different endpoint.
        return self


class MessagingDocumentCreate(MessagingDocumentBase):
    """POST body. The api enforces source_type='structured' on this path —
    PDF source rows are created via the upload endpoint in plan 12."""

    @model_validator(mode="after")
    def _require_structured_on_create(self) -> "MessagingDocumentCreate":
        if self.source_type is not MessagingSourceType.STRUCTURED:
            raise ValueError(
                "Use POST /api/v1/uploads/pdf to create PDF-source messaging documents. "
                "This endpoint is for structured entries only."
            )
        return self


class MessagingDocumentUpdate(MessagingDocumentBase):
    """PUT body. Same shape; the api wires partial-update vs replace
    semantics in plan 09. The shape stays strict either way."""


class MessagingDocumentRead(MessagingDocumentBase):
    """Read response. Adds server-side fields."""

    id: UUID
    file_path: str | None = None
    created_at: str  # ISO-8601 timestamp
    updated_at: str
