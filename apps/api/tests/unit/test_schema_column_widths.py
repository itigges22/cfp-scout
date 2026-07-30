"""A schema length must never exceed its database column.

When it does, over-long input passes Pydantic and dies at the INSERT — the
user gets a 500 from asyncpg instead of a 422 naming the field. The point of
these aliases is to turn that into a good error message, which only works
while the numbers agree.

Note what this does NOT assert: that every alias equals its column. Stricter
than the column is a legitimate policy choice (ConferenceName is 150 against
a VARCHAR(200), because a longer name is nearly always a bad scrape). Looser
is always a bug.
"""

from __future__ import annotations

import app.db.models  # noqa: F401  (registers the tables on Base.metadata)
import pytest
from app import schemas as common
from app.db.models import Base

#: alias name -> (table, column) it is used for.
MIRRORS = [
    ("ShortTitle", "messaging_documents", "title"),
    ("ShortTitle", "sources", "name"),
    ("ShortName", "smes", "full_name"),
    ("AudienceName", "audience_profiles", "name"),
    ("AudienceName", "strategic_pillars", "name"),
    ("ConferenceName", "conferences", "name"),
]


def _alias_max(name: str) -> int:
    alias = getattr(common, name)
    for meta in getattr(alias, "__metadata__", ()):
        if getattr(meta, "max_length", None):
            return int(meta.max_length)
    raise AssertionError(f"{name} declares no max_length")


def _column_width(table: str, column: str) -> int | None:
    t = Base.metadata.tables.get(f"app.{table}")
    assert t is not None, f"no table app.{table}"
    col = t.columns.get(column)
    assert col is not None, f"no column {table}.{column}"
    return getattr(col.type, "length", None)


@pytest.mark.parametrize(("alias", "table", "column"), MIRRORS)
def test_the_schema_limit_fits_inside_the_column(
    alias: str, table: str, column: str
) -> None:
    width = _column_width(table, column)
    if width is None:
        pytest.skip(f"{table}.{column} is unbounded TEXT")
    assert _alias_max(alias) <= width, (
        f"{alias} allows {_alias_max(alias)} characters but "
        f"{table}.{column} holds {width} — over-long input would reach the "
        f"database and fail with a 500 instead of a 422"
    )


def test_the_sme_bio_floor_is_still_a_floor() -> None:
    """Not a style rule: short bios embed badly and score badly.

    If this ever gets "tidied" away, SME matching quietly degrades for
    everyone who typed one line.
    """
    alias = common.SmeBio
    mins = [
        m.min_length
        for m in getattr(alias, "__metadata__", ())
        if getattr(m, "min_length", None)
    ]
    assert mins and mins[0] >= 200, "SmeBio lost its minimum length"
