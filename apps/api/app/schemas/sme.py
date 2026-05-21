"""SME (subject-matter expert) input schemas.

SME profile quality drives matcher quality. The bio min-length of 200 chars
is deliberate — empty or terse bios produce poor embeddings, so the
guardrail nudges the team to invest in actual content.

`primary_topics` and `audience_focus` reference existing rows in
`topics` and `audience_profiles`. Schema-level we only check the
UUID format; existence is verified by the service layer in plan 09.
"""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from pydantic import EmailStr, Field, field_validator

from app.schemas.common import (
    CountryCode,
    LanguageCode,
    ListItem,
    ShortName,
    SmeBio,
    StrictBase,
    validate_country_code,
    validate_language_code,
)


# ---------------------------------------------------------------------------
# external_links — constrained to a closed set of keys.
# Anything else is rejected (we don't want twitter / mastodon / random URLs
# accumulating in a freeform dict).
# ---------------------------------------------------------------------------
class SmeExternalLinks(StrictBase):
    """Allowed link keys for an SME profile. Add new keys here with intent."""

    linkedin: str | None = None
    github: str | None = None
    website: str | None = None


class SmeBase(StrictBase):
    full_name: ShortName
    email: EmailStr | None = None

    # team: free-form for now (team + sibling team names). A future
    # iteration could enum-ify this once we know the closed set.
    team: Annotated[str, Field(min_length=2, max_length=60)]

    expertise_areas: Annotated[list[ListItem], Field(min_length=2, max_length=10)]

    # Schema only validates the UUID format; FK existence checked by the
    # service layer that has DB access.
    primary_topics: Annotated[list[UUID], Field(min_length=2, max_length=15)]
    audience_focus: Annotated[list[UUID], Field(min_length=1, max_length=8)]

    location_country: CountryCode
    location_city: Annotated[str | None, Field(default=None, max_length=100)] = None

    bio: SmeBio

    languages: list[LanguageCode] = []

    external_links: SmeExternalLinks = SmeExternalLinks()

    is_active: bool = True

    # ----- runtime validation ----------------------------------------------
    @field_validator("location_country")
    @classmethod
    def _validate_country(cls, value: str) -> str:
        return validate_country_code(value)

    @field_validator("languages")
    @classmethod
    def _validate_languages(cls, value: list[str]) -> list[str]:
        return [validate_language_code(code) for code in value]


class SmeCreate(SmeBase):
    pass


class SmeUpdate(SmeBase):
    pass


class SmeRead(SmeBase):
    id: UUID
    created_at: str
    updated_at: str
