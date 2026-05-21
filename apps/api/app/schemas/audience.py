"""Audience-profile input schemas.

Audience profiles are your marketing personas. The matcher uses
audience overlap (Jaccard between conference_audiences and sme_audiences)
as one of the SME-matching dimensions.

The ``industry`` field is intentionally a freeform string rather than a
Postgres enum — it gets validated against the team's industry vocabulary
(maintained via the XLSX workbook from plan 31). Doing it that way means
adding a new industry is a workbook edit, not a code change + migration.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated
from uuid import UUID

from pydantic import Field

from app.schemas.common import (
    READ_CONFIG,
    AudienceName,
    Description,
    ListItem,
    RoleSeniority,
    StrictBase,
)


class AudienceProfileBase(StrictBase):
    name: AudienceName
    description: Description

    # Industry is text now; runtime validation against the
    # `industries` lookup table (workbook-managed) lives in the service
    # layer, not the schema, so we don't have to migrate every time a new
    # industry is added.
    industry: Annotated[str, Field(min_length=2, max_length=80)]

    role_seniority: RoleSeniority

    primary_pain_points: Annotated[list[ListItem], Field(min_length=2, max_length=8)]
    key_messages: Annotated[list[ListItem], Field(min_length=2, max_length=8)]
    exclusion_criteria: Annotated[list[ListItem], Field(max_length=5)] = []

    is_active: bool = True


class AudienceProfileCreate(AudienceProfileBase):
    pass


class AudienceProfileUpdate(AudienceProfileBase):
    pass


class AudienceProfileRead(AudienceProfileBase):
    model_config = READ_CONFIG

    id: UUID
    created_at: datetime
    updated_at: datetime
