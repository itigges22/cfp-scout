"""Main entity tables — the things the team and the scraper care about.

All in the ``app`` schema. See ``docs/data-model.md`` for per-column rationale;
this file is the implementation.

Convention notes:
  * Enum values are stored as ``String`` with no Postgres-level enum type. We
    validate them in Pydantic (plan 05) so we keep schema migrations cheap
    when adding a new enum value.
  * ``ARRAY(String)`` is used for ``text[]`` columns rather than introducing a
    polymorphic store.
  * Server-side defaults are preferred over Python-side ones so direct SQL
    inserts (Alembic data migrations, future bulk imports) get the same defaults.
"""

from __future__ import annotations

import uuid
from datetime import date

from sqlalchemy import (
    Boolean,
    Date,
    ForeignKey,
    Index,
    Integer,
    SmallInteger,
    String,
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.models._mixins import TimestampedMixin, uuid_pk


# ===========================================================================
# Manual inputs — team-curated reference data.
# ===========================================================================


class MessagingDocument(TimestampedMixin, Base):
    """Product messaging + positioning. Drives matcher Stage A."""

    __tablename__ = "messaging_documents"
    __table_args__ = {"schema": "app"}

    id: Mapped[uuid.UUID] = uuid_pk()

    title: Mapped[str] = mapped_column(String(120), nullable=False)
    source_type: Mapped[str] = mapped_column(String(20), nullable=False)
    file_path: Mapped[str | None] = mapped_column(Text)

    elevator_pitch: Mapped[str] = mapped_column(Text, nullable=False)
    target_personas: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False)
    key_themes: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False)
    talking_points: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False)
    differentiators: Mapped[list[str]] = mapped_column(
        ARRAY(Text), nullable=False, server_default=text("'{}'::text[]")
    )
    competitive_position: Mapped[str] = mapped_column(
        Text, nullable=False, server_default=text("''")
    )

    raw_content: Mapped[str | None] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("true")
    )


class AudienceProfile(TimestampedMixin, Base):
    """Red Hat marketing personas."""

    __tablename__ = "audience_profiles"
    __table_args__ = {"schema": "app"}

    id: Mapped[uuid.UUID] = uuid_pk()

    name: Mapped[str] = mapped_column(String(80), nullable=False, unique=True)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    industry: Mapped[str] = mapped_column(String(80), nullable=False)
    role_seniority: Mapped[str] = mapped_column(String(20), nullable=False)

    primary_pain_points: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False)
    key_messages: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False)
    exclusion_criteria: Mapped[list[str]] = mapped_column(
        ARRAY(Text), nullable=False, server_default=text("'{}'::text[]")
    )

    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("true")
    )


class StrategicPillar(TimestampedMixin, Base):
    """Red Hat AI's four-pillar strategy. Seeded; rarely changes."""

    __tablename__ = "strategic_pillars"
    __table_args__ = {"schema": "app"}

    id: Mapped[uuid.UUID] = uuid_pk()

    name: Mapped[str] = mapped_column(String(80), nullable=False, unique=True)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    display_order: Mapped[int] = mapped_column(SmallInteger, nullable=False)


class Sme(TimestampedMixin, Base):
    """Subject-matter experts (DAAM + non-DAAM)."""

    __tablename__ = "smes"
    __table_args__ = {"schema": "app"}

    id: Mapped[uuid.UUID] = uuid_pk()

    full_name: Mapped[str] = mapped_column(String(100), nullable=False)
    email: Mapped[str | None] = mapped_column(String(200))
    team: Mapped[str] = mapped_column(String(60), nullable=False)

    expertise_areas: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False)

    # primary_topics + audience_focus are denormalized lists for fast
    # filtering; sme_topics + sme_audiences junctions are authoritative
    # for graph traversal (plan 16).
    primary_topics: Mapped[list[uuid.UUID]] = mapped_column(
        ARRAY(UUID(as_uuid=True)), nullable=False, server_default=text("ARRAY[]::uuid[]")
    )
    audience_focus: Mapped[list[uuid.UUID]] = mapped_column(
        ARRAY(UUID(as_uuid=True)), nullable=False, server_default=text("ARRAY[]::uuid[]")
    )

    location_country: Mapped[str] = mapped_column(String(2), nullable=False)
    location_city: Mapped[str | None] = mapped_column(String(100))

    bio: Mapped[str] = mapped_column(Text, nullable=False)
    languages: Mapped[list[str]] = mapped_column(
        ARRAY(String(2)), nullable=False, server_default=text("'{}'::varchar[]")
    )

    external_links: Mapped[dict] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )

    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("true")
    )


class Topic(TimestampedMixin, Base):
    """Controlled topic vocabulary.

    Topics with pending_review=true are LLM-discovered (plan 15) and do not
    influence matching until an admin approves them.
    """

    __tablename__ = "topics"
    __table_args__ = {"schema": "app"}

    id: Mapped[uuid.UUID] = uuid_pk()

    name: Mapped[str] = mapped_column(String(60), nullable=False, unique=True)
    slug: Mapped[str] = mapped_column(String(80), nullable=False, unique=True)
    aliases: Mapped[list[str]] = mapped_column(
        ARRAY(Text), nullable=False, server_default=text("'{}'::text[]")
    )

    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("true")
    )
    pending_review: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )


class ConferenceSeries(TimestampedMixin, Base):
    """Year-over-year linkage (plan 23). Seeded from db/seeds/conference_series.yaml."""

    __tablename__ = "conference_series"
    __table_args__ = {"schema": "app"}

    id: Mapped[uuid.UUID] = uuid_pk()

    canonical_name: Mapped[str] = mapped_column(String(150), nullable=False, unique=True)
    aliases: Mapped[list[str]] = mapped_column(
        ARRAY(Text), nullable=False, server_default=text("'{}'::text[]")
    )
    description: Mapped[str] = mapped_column(
        Text, nullable=False, server_default=text("''")
    )
    typical_month: Mapped[int | None] = mapped_column(SmallInteger)
    typical_topics: Mapped[list[str]] = mapped_column(
        ARRAY(Text), nullable=False, server_default=text("'{}'::text[]")
    )
    homepage: Mapped[str | None] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("true")
    )


class PastConference(TimestampedMixin, Base):
    """History of who attended what."""

    __tablename__ = "past_conferences"
    __table_args__ = {"schema": "app"}

    id: Mapped[uuid.UUID] = uuid_pk()

    name: Mapped[str] = mapped_column(String(150), nullable=False)
    year: Mapped[int] = mapped_column(SmallInteger, nullable=False)

    series_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("app.conference_series.id", ondelete="SET NULL"),
    )

    attended_sme_ids: Mapped[list[uuid.UUID]] = mapped_column(
        ARRAY(UUID(as_uuid=True)), nullable=False
    )

    role: Mapped[str] = mapped_column(String(20), nullable=False)
    session_type: Mapped[str | None] = mapped_column(String(20))
    notes: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("''"))
    imported_from: Mapped[str | None] = mapped_column(String(120))


# ===========================================================================
# Scraper / discovery
# ===========================================================================


class Source(TimestampedMixin, Base):
    """Crawl targets configured by the user. Plan 14 owns the scraping logic."""

    __tablename__ = "sources"
    __table_args__ = {"schema": "app"}

    id: Mapped[uuid.UUID] = uuid_pk()

    name: Mapped[str] = mapped_column(String(120), nullable=False)
    url: Mapped[str] = mapped_column(Text, nullable=False)
    kind: Mapped[str] = mapped_column(String(20), nullable=False)

    enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("true")
    )
    last_crawled_at: Mapped["date | None"] = mapped_column(Date)
    crawl_cadence: Mapped[str] = mapped_column(
        # Stored as interval; SQLAlchemy returns timedelta.
        # Use Text here to keep the ORM type simple at the app layer for now;
        # a future plan can swap to INTERVAL with timedelta mapping.
        Text,
        nullable=False,
        server_default=text("'1 day'"),
    )
    robots_allowed: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("true")
    )
    politeness_delay_seconds: Mapped[int] = mapped_column(
        SmallInteger, nullable=False, server_default=text("3")
    )
    notes: Mapped[str | None] = mapped_column(Text)


class RawPage(TimestampedMixin, Base):
    """Every fetched page. HTML lives on the volume; this is just metadata."""

    __tablename__ = "raw_pages"
    __table_args__ = (
        Index("ix_raw_pages_url_fetched_at", "url", "fetched_at"),
        {"schema": "app"},
    )

    id: Mapped[uuid.UUID] = uuid_pk()

    source_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("app.sources.id", ondelete="CASCADE"),
        nullable=False,
    )
    url: Mapped[str] = mapped_column(Text, nullable=False)
    fetched_at: Mapped[date] = mapped_column(Date, nullable=False)
    http_status: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    content_type: Mapped[str] = mapped_column(String(120), nullable=False)
    raw_body_path: Mapped[str] = mapped_column(Text, nullable=False)
    # sha256 of body. Unique drives dedup.
    hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    etag: Mapped[str | None] = mapped_column(Text)
    last_modified: Mapped[str | None] = mapped_column(Text)
    parse_status: Mapped[str | None] = mapped_column(String(30))


class Conference(TimestampedMixin, Base):
    """The canonical, deduplicated conference list. Hot table."""

    __tablename__ = "conferences"
    __table_args__ = (
        Index("ix_conferences_start_date", "start_date"),
        # Partial index covering the dashboard's "active statuses" query.
        Index(
            "ix_conferences_status_active",
            "status",
            "start_date",
            postgresql_where=text(
                "status IN ('discovered', 'needs_review', 'needs_review_pillar', "
                "'needs_sme_review', 'approved')"
            ),
        ),
        # GIN on the denormalized topics array for fast tag filtering.
        Index("ix_conferences_topics_gin", "topics", postgresql_using="gin"),
        {"schema": "app"},
    )

    id: Mapped[uuid.UUID] = uuid_pk()

    name: Mapped[str] = mapped_column(String(200), nullable=False)
    slug: Mapped[str] = mapped_column(String(200), nullable=False, unique=True)

    start_date: Mapped[date | None] = mapped_column(Date)
    end_date: Mapped[date | None] = mapped_column(Date)

    location_city: Mapped[str | None] = mapped_column(String(120))
    location_country: Mapped[str | None] = mapped_column(String(2))

    is_virtual: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    venue: Mapped[str | None] = mapped_column(String(200))
    website: Mapped[str | None] = mapped_column(Text)

    # Denormalized "primary" CFP close. cfp_deadlines is the authoritative
    # source (plan 14 / 24); cfp_close_at is the earliest non-workshop
    # deadline for quick filters.
    cfp_open_at: Mapped[date | None] = mapped_column(Date)
    cfp_close_at: Mapped[date | None] = mapped_column(Date)
    cfp_deadlines: Mapped[list[dict]] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb")
    )
    cfp_topics_of_interest: Mapped[list[str]] = mapped_column(
        ARRAY(Text), nullable=False, server_default=text("'{}'::text[]")
    )
    acceptance_rate_percent: Mapped[int | None] = mapped_column(SmallInteger)

    estimated_cost_usd: Mapped[int | None] = mapped_column(Integer)
    topics: Mapped[list[str]] = mapped_column(
        ARRAY(Text), nullable=False, server_default=text("'{}'::text[]")
    )

    confidence_score: Mapped[float | None] = mapped_column()
    status: Mapped[str] = mapped_column(
        String(40), nullable=False, server_default=text("'discovered'")
    )

    series_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("app.conference_series.id", ondelete="SET NULL"),
    )

    freshness_score: Mapped[float] = mapped_column(
        nullable=False, server_default=text("1.0")
    )


class ConferenceSource(Base):
    """Junction: which raw_pages contributed to which conference row.

    Composite PK; no TimestampedMixin (the conference + raw_page already
    carry timestamps).
    """

    __tablename__ = "conference_sources"
    __table_args__ = {"schema": "app"}

    conference_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("app.conferences.id", ondelete="CASCADE"),
        primary_key=True,
    )
    raw_page_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("app.raw_pages.id", ondelete="CASCADE"),
        primary_key=True,
    )
