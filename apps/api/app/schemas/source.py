"""Pydantic schemas for crawl sources (plan 14).

A ``Source`` is a configured crawl target — an RSS feed, a sitemap, a static
page with conference listings, etc. The team enters these manually or imports
them from the XLSX workbook (plan 31).

For pass 1 we support two kinds:
  * ``rss`` — RSS/Atom feed parsed via feedparser
  * ``page`` — static HTML page; the scraper extracts links and queues each
              one for parsing (plan 15 does the per-link extraction)

Future kinds (pass 2): ``sitemap``, ``ics``, ``wikicfp``, ``api``.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Annotated
from uuid import UUID

from pydantic import Field, HttpUrl, StringConstraints, field_validator

from app.schemas.common import READ_CONFIG, ReadBase, ShortName, ShortNote, StrictBase


class SourceKind(StrEnum):
    """Crawl-strategy enum. Pass 1 ships rss + page; pass 2 adds the rest."""

    RSS = "rss"
    PAGE = "page"
    # Reserved for plan 14 pass 2:
    SITEMAP = "sitemap"
    ICS = "ics"
    WIKICFP = "wikicfp"
    API = "api"


# Cadence text (Postgres INTERVAL syntax). The DB stores it as text and uses
# `cast('1 day' as interval)` inside the runner's "due for crawl" query. We
# validate the format here rather than letting bogus values reach the DB.
_VALID_CADENCE_PATTERN = (
    # very small allowlist — single positive integer + unit
    # examples: "15 minutes", "1 hour", "1 day", "7 days"
    r"^\d{1,4} (minute|minutes|hour|hours|day|days|week|weeks)$"
)
CrawlCadence = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        min_length=3,
        max_length=30,
        pattern=_VALID_CADENCE_PATTERN,
    ),
]


class SourceCreate(StrictBase):
    """POST /sources payload."""

    name: ShortName
    url: HttpUrl
    kind: SourceKind
    crawl_cadence: CrawlCadence = "1 day"
    politeness_delay_seconds: int = Field(default=3, ge=1, le=60)
    enabled: bool = True
    notes: ShortNote | None = None

    @field_validator("kind", mode="after")
    @classmethod
    def _reject_unsupported_kinds_for_pass_1(cls, kind: SourceKind) -> SourceKind:
        """Pass 1 only supports rss + page. Others land in pass 2."""
        if kind in {SourceKind.SITEMAP, SourceKind.ICS, SourceKind.WIKICFP, SourceKind.API}:
            raise ValueError(
                f"Source kind {kind.value!r} is reserved for plan 14 pass 2. "
                "For now use 'rss' or 'page'."
            )
        return kind


class SourceUpdate(StrictBase):
    """PATCH /sources/{id}. All fields optional."""

    name: ShortName | None = None
    url: HttpUrl | None = None
    crawl_cadence: CrawlCadence | None = None
    politeness_delay_seconds: int | None = Field(default=None, ge=1, le=60)
    enabled: bool | None = None
    notes: ShortNote | None = None


class SourceRead(ReadBase):
    """GET /sources response row."""

    model_config = READ_CONFIG

    id: UUID
    name: str
    url: str
    kind: str
    enabled: bool
    crawl_cadence: str
    politeness_delay_seconds: int
    robots_allowed: bool
    last_crawled_at: datetime | None = None
    notes: str | None = None
    created_at: datetime
    updated_at: datetime
