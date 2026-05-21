"""Shared enums, type aliases, and validators used by every input schema.

Importing this module is the conventional way to discover the rules in one
place. Schemas in sibling modules re-use what's here rather than redefining.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator

# ---------------------------------------------------------------------------
# Base config every input schema inherits.
# ---------------------------------------------------------------------------
# extra='forbid' rejects unknown keys — no silent drops, no accidental
# typos like {"linked_in": "..."} succeeding as "ignored extra data."
# str_strip_whitespace normalises leading/trailing whitespace on every
# string field so we never store '  RAG  ' as a topic.
# str_min_length=1 prevents '' from passing as a value where a non-empty
# string is expected (Pydantic doesn't infer this from `str`).
BASE_CONFIG = ConfigDict(
    extra="forbid",
    str_strip_whitespace=True,
    use_enum_values=False,  # keep StrEnum members typed, not stringified yet
)


class StrictBase(BaseModel):
    """All Scout input schemas inherit from this. Centralises model_config."""

    model_config = BASE_CONFIG


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------
class RoleSeniority(StrEnum):
    EXECUTIVE = "executive"
    DIRECTOR = "director"
    MANAGER = "manager"
    IC = "ic"
    MIXED = "mixed"


class MessagingSourceType(StrEnum):
    STRUCTURED = "structured"
    PDF = "pdf"


class PastConferenceRole(StrEnum):
    ATTENDEE = "attendee"
    SPEAKER = "speaker"
    SPONSOR = "sponsor"
    ORGANIZER = "organizer"


class PastConferenceSessionType(StrEnum):
    KEYNOTE = "keynote"
    TALK = "talk"
    PANEL = "panel"
    WORKSHOP = "workshop"
    POSTER = "poster"


# ---------------------------------------------------------------------------
# Type aliases (Annotated string constraints).
#
# These keep the per-field declarations on the data classes short and obvious.
# Names follow the pattern <Use>Text with explicit min/max to encode policy.
# ---------------------------------------------------------------------------
ShortTitle = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=3, max_length=120)
]
ShortName = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=3, max_length=100)
]
AudienceName = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=3, max_length=80)
]
Description = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=50, max_length=500)
]
TopicName = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=2, max_length=60)
]
ConferenceName = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=3, max_length=150)
]
ShortNote = Annotated[
    str, StringConstraints(strip_whitespace=True, max_length=500)
]
ListItem = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=2, max_length=200)
]
ElevatorPitch = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=50, max_length=600)
]
TalkingPoint = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=5, max_length=200)
]
SmeBio = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=200, max_length=2000)
]
CountryCode = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=2, max_length=2, to_upper=True)
]
LanguageCode = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=2, max_length=2, to_lower=True)
]


# ---------------------------------------------------------------------------
# Validators
# ---------------------------------------------------------------------------
def _iso_3166_alpha2_codes() -> frozenset[str]:
    """Build the canonical set of ISO-3166-1 alpha-2 country codes via pycountry.

    Defined as a function so the import cost is paid once at module load.
    pycountry ships the lists; we never maintain country data ourselves.
    """
    import pycountry  # local import to keep startup graph tidy

    return frozenset(country.alpha_2 for country in pycountry.countries)


def _iso_639_1_codes() -> frozenset[str]:
    """ISO-639-1 (2-letter) language codes."""
    import pycountry

    return frozenset(
        lang.alpha_2 for lang in pycountry.languages if hasattr(lang, "alpha_2")
    )


# Cached lookups; expensive to build, never change at runtime.
_COUNTRY_CODES = _iso_3166_alpha2_codes()
_LANGUAGE_CODES = _iso_639_1_codes()


def validate_country_code(value: str) -> str:
    """Validator: must be a real ISO-3166-1 alpha-2 code."""
    upper = value.upper()
    if upper not in _COUNTRY_CODES:
        raise ValueError(
            f"'{value}' is not a valid ISO-3166-1 alpha-2 country code. "
            f"Use codes like 'US', 'DE', 'JP'."
        )
    return upper


def validate_language_code(value: str) -> str:
    """Validator: must be a real ISO-639-1 (2-letter) language code."""
    lower = value.lower()
    if lower not in _LANGUAGE_CODES:
        raise ValueError(
            f"'{value}' is not a valid ISO-639-1 language code. "
            f"Use codes like 'en', 'de', 'ja'."
        )
    return lower


# ---------------------------------------------------------------------------
# Reusable mixin for list-of-text fields.
#
# Pydantic v2 doesn't directly support per-element StringConstraints on a
# list in the type annotation; field_validator handles it cleanly.
# ---------------------------------------------------------------------------
class TrimItemsMixin:
    """Provides a generic '_trim_items' validator that strips whitespace
    on every list element and refuses empty strings.

    Subclasses opt-in by declaring lists of `ListItem` and inheriting from
    this mixin AFTER their schema's base.
    """

    @field_validator("*", mode="before")
    @classmethod
    def _trim_items(cls, value: object) -> object:
        if isinstance(value, list):
            # Strip + drop empty strings; preserve order
            return [item.strip() if isinstance(item, str) else item for item in value]
        return value
