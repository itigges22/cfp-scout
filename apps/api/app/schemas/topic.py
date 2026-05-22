"""Topic vocabulary input schemas.

`topics` is a controlled vocabulary. Topics come from two paths:

  1. **Admin entry** via the UI or XLSX workbook — `is_active=true`,
     `pending_review=false`.
  2. **Discovery** by the LLM extractor (plan 15) — inserted with
     `is_active=false`, `pending_review=true`. These do NOT influence
     matching until an admin approves them via /settings/topics.

This module covers the admin-entry path. The discovery path uses the same
schema's `name`/`aliases` constraints but the service layer sets the flags.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated
from uuid import UUID

from pydantic import Field, field_validator
from pydantic.functional_validators import AfterValidator

from app.schemas.common import READ_CONFIG, StrictBase, TopicName


def _slugify_lower(value: str) -> str:
    """Lower-case + replace runs of non-alphanumerics with single dashes.

    Intentionally lightweight (no extra dep). The `slug` is for stable URLs
    and case-insensitive comparison, not aesthetics. Plan 15's normalization
    uses pg_trgm + unaccent, which is fuzzier than slug equality.
    """
    import re

    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")


# Slug constraints kept distinct from auto-slugified names so we can validate
# both a user-supplied slug and the auto-generated one.
Slug = Annotated[
    str,
    Field(min_length=2, max_length=80),
    AfterValidator(_slugify_lower),
]


class TopicBase(StrictBase):
    name: TopicName
    slug: Slug | None = None  # auto-derived from name if absent
    aliases: Annotated[list[str], Field(max_length=10)] = []

    is_active: bool = True
    pending_review: bool = False

    @field_validator("aliases")
    @classmethod
    def _alias_length(cls, value: list[str]) -> list[str]:
        for item in value:
            stripped = item.strip()
            if not (2 <= len(stripped) <= 60):
                raise ValueError(f"alias '{item}': must be 2-60 chars (after stripping whitespace)")
        return [item.strip() for item in value]


class TopicCreate(TopicBase):
    pass


class TopicUpdate(TopicBase):
    pass


class TopicRead(TopicBase):
    model_config = READ_CONFIG

    id: UUID
    created_at: datetime
    updated_at: datetime
