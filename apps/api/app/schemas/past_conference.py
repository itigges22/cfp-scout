"""Past-conference input schemas.

Past conferences record who attended what, in what capacity. Powers the
past-attendance bonus in the SME matcher (via conference series — plan 23).

Both single-row entry (plan 09) and CSV import (also plan 09) and XLSX
workbook import (plan 31) validate against this schema.
"""

from __future__ import annotations

from datetime import date
from typing import Annotated
from uuid import UUID

from pydantic import Field, field_validator

from app.schemas.common import (
    ConferenceName,
    PastConferenceRole,
    PastConferenceSessionType,
    ShortNote,
    StrictBase,
)


# Year sanity. Pre-1990 is almost certainly a typo; > current_year + 1 is
# also a typo (future events go in `conferences`, not `past_conferences`).
_MIN_YEAR = 1990


def _max_year() -> int:
    return date.today().year


class PastConferenceBase(StrictBase):
    name: ConferenceName
    year: Annotated[int, Field(ge=_MIN_YEAR)]

    series_id: UUID | None = None  # FK to conference_series (plan 23)

    attended_sme_ids: Annotated[list[UUID], Field(min_length=1)]

    role: PastConferenceRole
    session_type: PastConferenceSessionType | None = None

    notes: ShortNote | None = ""
    imported_from: Annotated[str | None, Field(default=None, max_length=120)] = None

    @field_validator("year")
    @classmethod
    def _year_not_in_future(cls, value: int) -> int:
        if value > _max_year():
            raise ValueError(
                f"year={value} is in the future. Use the `conferences` table for upcoming events."
            )
        return value


class PastConferenceCreate(PastConferenceBase):
    pass


class PastConferenceUpdate(PastConferenceBase):
    pass


class PastConferenceRead(PastConferenceBase):
    id: UUID
    created_at: str
    updated_at: str


# ---------------------------------------------------------------------------
# CSV row shape — used by the bulk-import endpoint in plan 09 + plan 31.
#
# attended_by_names is the SMA-display-name representation used in the CSV;
# the service layer (plan 09) resolves it to attended_sme_ids by
# case-insensitive match against `smes.full_name`. Unknown names error out.
# ---------------------------------------------------------------------------
class PastConferenceCSVRow(StrictBase):
    name: ConferenceName
    year: Annotated[int, Field(ge=_MIN_YEAR)]
    attended_by_names: Annotated[str, Field(min_length=1, max_length=600)]
    role: PastConferenceRole
    session_type: PastConferenceSessionType | None = None
    notes: ShortNote | None = ""

    @field_validator("year")
    @classmethod
    def _year_not_in_future(cls, value: int) -> int:
        if value > _max_year():
            raise ValueError(
                f"year={value} is in the future. Use the `conferences` table for upcoming events."
            )
        return value
