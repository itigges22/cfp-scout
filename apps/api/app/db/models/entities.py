"""Main entity tables — the things your team and the scraper care about.

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
from datetime import date, datetime

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
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

    doc_kind: Mapped[str] = mapped_column(
        String(30), nullable=False, server_default=text("'other'")
    )
    pillar_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("app.strategic_pillars.id", ondelete="SET NULL"),
        nullable=True,
    )
    raw_content: Mapped[str | None] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))


class AudienceProfile(TimestampedMixin, Base):
    """Marketing audience personas."""

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

    # Migration B: optional pillar assignment (pillar page shows filtered view)
    pillar_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("app.strategic_pillars.id", ondelete="SET NULL"),
    )

    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))


class StrategicPillar(TimestampedMixin, Base):
    """Your AI strategy's pillars. Seeded; rarely changes."""

    __tablename__ = "strategic_pillars"
    __table_args__ = {"schema": "app"}

    id: Mapped[uuid.UUID] = uuid_pk()

    name: Mapped[str] = mapped_column(String(80), nullable=False, unique=True)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    # Long-form (500-800 word) pillar description, extracted from the
    # operator's messaging documents via the LLM. Used by the matcher's
    # stage B in place of ``description`` when present — the short
    # default ``description`` doesn't have enough discriminative
    # vocabulary for cosine similarity to separate "this conference
    # genuinely fits pillar X" from "this conference is AI-adjacent."
    enriched_description: Mapped[str | None] = mapped_column(Text)
    display_order: Mapped[int] = mapped_column(SmallInteger, nullable=False)


class Sme(TimestampedMixin, Base):
    """Subject-matter experts (your team + outside your team)."""

    __tablename__ = "smes"
    __table_args__ = {"schema": "app"}

    id: Mapped[uuid.UUID] = uuid_pk()

    full_name: Mapped[str] = mapped_column(String(100), nullable=False)
    email: Mapped[str | None] = mapped_column(String(200))
    team: Mapped[str] = mapped_column(String(60), nullable=False)

    # expertise_areas removed (Migration J) — sme_topics junction is authoritative.

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

    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))


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

    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
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
    description: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("''"))
    typical_month: Mapped[int | None] = mapped_column(SmallInteger)
    typical_topics: Mapped[list[str]] = mapped_column(
        ARRAY(Text), nullable=False, server_default=text("'{}'::text[]")
    )
    homepage: Mapped[str | None] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))


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

    # Raw attendee NAMES from the source CSV/spreadsheet. Includes BOTH
    # names that resolved to an SME (mirrored into attended_sme_ids) AND
    # names that didn't — so nothing the CSV told us is lost when an
    # attendee isn't an active SME yet. Calendar-sync mapper writes both
    # columns; manual entry through the UI only writes attended_sme_ids
    # (the dialog won't let you save without ≥1 real SME).
    attended_by_names_raw: Mapped[list[str]] = mapped_column(
        ARRAY(Text), nullable=False, server_default=text("'{}'::text[]")
    )

    role: Mapped[str] = mapped_column(String(20), nullable=False)
    session_type: Mapped[str | None] = mapped_column(String(20))
    notes: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("''"))
    imported_from: Mapped[str | None] = mapped_column(String(120))
    # Operator's retrospective on whether attending this was a good
    # idea. Drives the matcher's series_memory boost: would_attend
    # → +0.10, unsure → +0.05, would_not_attend → −0.10. CHECK-
    # constrained to those three values at the DB level.
    verdict: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default=text("'unsure'")
    )

    event_kind: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default=text("'corporate'")
    )
    conference_url: Mapped[str | None] = mapped_column(String(500))
    location_city: Mapped[str | None] = mapped_column(String(100))
    location_country: Mapped[str | None] = mapped_column(String(2))


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

    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    # DateTime with timezone — the 15-min "due for crawl" check needs sub-day
    # precision, which a Date column would round away. Migrated 2026-05-22 in
    # the same migration that bumped raw_pages.fetched_at to DateTime.
    last_crawled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
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
    # DateTime with timezone — see the rationale on sources.last_crawled_at;
    # a date-granular fetch timestamp was too lossy for diagnostics.
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
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
        Index("ix_conferences_event_kind", "event_kind"),
        Index("ix_conferences_assigned_pillar_id", "assigned_pillar_id"),
        {"schema": "app"},
    )

    id: Mapped[uuid.UUID] = uuid_pk()

    name: Mapped[str] = mapped_column(String(200), nullable=False)
    slug: Mapped[str] = mapped_column(String(200), nullable=False, unique=True)

    start_date: Mapped[date | None] = mapped_column(Date)
    end_date: Mapped[date | None] = mapped_column(Date)

    location_city: Mapped[str | None] = mapped_column(String(120))
    location_country: Mapped[str | None] = mapped_column(String(2))

    # Best-effort geocoded coordinates for the dashboard map. NULL until
    # the geocoding pass has run (Nominatim, rate-limited). Stored as
    # plain floats — no PostGIS dependency; the dashboard only needs an
    # approximate dot at city-level resolution.
    latitude: Mapped[float | None] = mapped_column()
    longitude: Mapped[float | None] = mapped_column()

    is_virtual: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    venue: Mapped[str | None] = mapped_column(String(200))
    website: Mapped[str | None] = mapped_column(Text)
    # Where to submit / view the full CFP. Usually a sub-page of website
    # (e.g. https://kdd2026.org/call-for-papers/) — kept separate so the
    # brief + dashboard can link straight to "Apply here" without first
    # bouncing through the homepage. Manually-entered conferences leave
    # this blank.
    cfp_url: Mapped[str | None] = mapped_column(Text)

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

    # 2-3 sentence LLM-generated factual description, used by the matcher's
    # embedder. Populated on ingest (or on backfill) by app.services.enrichment.
    # When NULL the matcher falls back to the bare name+topics blob, which
    # is signal-starved — most conferences score 0% on messaging without
    # enrichment because their bare text has 14 words median.
    enriched_description: Mapped[str | None] = mapped_column(Text)

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

    freshness_score: Mapped[float] = mapped_column(nullable=False, server_default=text("1.0"))

    # Migration A: what kind of event is this?
    event_kind: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default=text("'corporate'")
    )
    # Migration A: human-assigned pillar (distinct from matcher-computed conference_pillars scores)
    assigned_pillar_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("app.strategic_pillars.id", ondelete="SET NULL"),
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


# ===========================================================================
# Talks library (v2 Phase 1)
# ===========================================================================


class Talk(TimestampedMixin, Base):
    """A prepared talk abstract. Migration D."""

    __tablename__ = "talks"
    __table_args__ = (
        Index("ix_talks_pillar_id", "pillar_id"),
        Index("ix_talks_primary_sme_id", "primary_sme_id"),
        Index("ix_talks_review_status", "review_status"),
        Index("ix_talks_is_active", "is_active"),
        {"schema": "app"},
    )

    id: Mapped[uuid.UUID] = uuid_pk()

    title: Mapped[str] = mapped_column(Text, nullable=False)
    abstract: Mapped[str | None] = mapped_column(Text)
    full_content: Mapped[str | None] = mapped_column(Text)

    source_type: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'manual'"))
    file_path: Mapped[str | None] = mapped_column(Text)

    pillar_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("app.strategic_pillars.id", ondelete="SET NULL"),
    )
    primary_sme_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("app.smes.id", ondelete="SET NULL"),
    )
    co_speaker_ids: Mapped[list[uuid.UUID]] = mapped_column(
        ARRAY(UUID(as_uuid=True)), nullable=False, server_default=text("ARRAY[]::uuid[]")
    )

    talk_format: Mapped[str | None] = mapped_column(Text)
    suggested_duration_minutes: Mapped[int | None] = mapped_column(Integer)

    review_status: Mapped[str] = mapped_column(
        Text, nullable=False, server_default=text("'draft'")
    )
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))


class TalkTag(Base):
    """User-defined labels for organizing talks. Migration E."""

    __tablename__ = "talk_tags"
    __table_args__ = {"schema": "app"}

    id: Mapped[uuid.UUID] = uuid_pk()

    name: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    color: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("NOW()")
    )


class TalkSubmission(Base):
    """Record of a talk being submitted to a conference. Migration G."""

    __tablename__ = "talk_submissions"
    __table_args__ = (
        Index("ix_talk_submissions_talk_id", "talk_id"),
        Index("ix_talk_submissions_conference_id", "conference_id"),
        Index("ix_talk_submissions_sme_id", "submitted_by_sme_id"),
        {"schema": "app"},
    )

    id: Mapped[uuid.UUID] = uuid_pk()

    talk_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("app.talks.id", ondelete="CASCADE"),
        nullable=False,
    )
    conference_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("app.conferences.id", ondelete="CASCADE"),
        nullable=False,
    )
    submitted_by_sme_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("app.smes.id", ondelete="SET NULL"),
    )

    submitted_at: Mapped[date | None] = mapped_column(Date)
    outcome: Mapped[str | None] = mapped_column(Text)
    notes: Mapped[str | None] = mapped_column(Text)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("NOW()")
    )


# ===========================================================================
# Pillar content tables (v2 Phase 1)
# ===========================================================================


class PillarContentRoadmap(TimestampedMixin, Base):
    """Quarterly goals per pillar. Migration H."""

    __tablename__ = "pillar_content_roadmap"
    __table_args__ = (
        Index("ix_pillar_content_roadmap_pillar_id", "pillar_id"),
        {"schema": "app"},
    )

    id: Mapped[uuid.UUID] = uuid_pk()

    pillar_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("app.strategic_pillars.id", ondelete="CASCADE"),
        nullable=False,
    )
    quarter: Mapped[str] = mapped_column(Text, nullable=False)
    goals: Mapped[list[str]] = mapped_column(
        ARRAY(Text), nullable=False, server_default=text("'{}'::text[]")
    )
    owner_label: Mapped[str | None] = mapped_column(Text)
    notes: Mapped[str | None] = mapped_column(Text)


class PillarGtmStrategy(TimestampedMixin, Base):
    """Versioned GTM strategy per pillar. Migration I."""

    __tablename__ = "pillar_gtm_strategy"
    __table_args__ = (
        Index("ix_pillar_gtm_strategy_pillar_id", "pillar_id"),
        {"schema": "app"},
    )

    id: Mapped[uuid.UUID] = uuid_pk()

    pillar_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("app.strategic_pillars.id", ondelete="CASCADE"),
        nullable=False,
    )
    objective: Mapped[str | None] = mapped_column(Text)
    key_messages: Mapped[list[str]] = mapped_column(
        ARRAY(Text), nullable=False, server_default=text("'{}'::text[]")
    )
    target_audience_ids: Mapped[list[uuid.UUID]] = mapped_column(
        ARRAY(UUID(as_uuid=True)), nullable=False, server_default=text("ARRAY[]::uuid[]")
    )
    notes: Mapped[str | None] = mapped_column(Text)
    version: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("1"))
