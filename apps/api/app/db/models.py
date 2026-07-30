"""The database schema: every ORM model, and the Base they share.

WHAT THIS DOES
    Declarative Base plus the ``uuid_pk`` / ``TimestampedMixin`` helpers,
    then the tables themselves:

        entities    conferences, sources, raw_pages, smes, talks, topics,
                    audiences, pillars, messaging_docs, conference_series
        junctions   the many-to-many rows joining them
        matching    matches, sme_fit
        vectors     embedding chunks (pgvector)
        ops         ingest_jobs, llm_calls, app_setting_overrides,
                    notifications, ops_state
        audit       audit_log

HOW IT CONNECTS
    Imported by  nearly every service and route; alembic reads Base.metadata
    Helpers      app/db/session.py owns the engine and sessions

WORTH KNOWING
    Seven files for one schema, and six of them existed only so the
    seventh could import them — junctions reference entities, matching
    references entities, and ``base`` had no consumer outside the package
    at all. Answering "what columns does Conference have, and what points
    at it" meant opening four files.

    Schemas are separated at the DATABASE level, not the module level:
    ``app`` for business tables and ``audit`` for the append-only log. The
    ``app`` role has INSERT + SELECT on audit and nothing else, so a DELETE
    against audit_log is refused by Postgres. See
    infra/postgres/init/02-roles-and-schemas.sql.

    Conference FKs are declared ``ondelete='CASCADE'`` on purpose: one
    DELETE removes the conference and everything referencing it.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    CHAR,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    MetaData,
    Numeric,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy import text as sql_text  # aliased to avoid shadowing by DocumentChunk.text column
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.sql import func

# ==========================================================================
# db/base.py
# ==========================================================================


NAMING_CONVENTION = {
    "ix": "ix_%(table_name)s_%(column_0_N_name)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


metadata = MetaData(naming_convention=NAMING_CONVENTION)


class Base(DeclarativeBase):
    """Declarative base for every ORM model in the project.

    Per-model ``__table_args__`` should set ``{"schema": "<schema_name>"}`` so
    tables land in the correct schema (app / vectors / audit / jobs). See
    ADR-0002 for the schema layout.
    """

    metadata = metadata


def uuid_pk() -> Mapped[uuid.UUID]:
    """Standard UUID primary key, server-side default via ``gen_random_uuid()``.

    Helper exists because every table uses this exact pattern. Returning the
    Mapped column directly lets each model class declare:

        id: Mapped[uuid.UUID] = uuid_pk()
    """
    return mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )


class TimestampedMixin:
    """Adds ``created_at`` and ``updated_at`` to a model.

    Server-side defaults via ``now()`` so insertions don't require a
    Python-side timestamp. ``updated_at`` updates on UPDATE via
    ``onupdate=func.now()``.
    """

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


# ==========================================================================
# db/models.py
# ==========================================================================


ATTENDANCE_VERDICTS: tuple[str, ...] = ("would_attend", "unsure", "would_not_attend")


def _in_sql(column: str, values: tuple[str, ...], *, nullable: bool = False) -> str:
    """Render an IN-list CHECK from a Python tuple.

    Built rather than hand-written so the constraint cannot drift from the
    vocabulary it enforces. The comment on EVENT_KINDS claimed the CHECKs
    were driven by the tuple; they were a copied string literal, so adding a
    kind updated Pydantic instantly and the database not at all.
    """
    rendered = ", ".join(f"'{v}'" for v in values)
    clause = f"{column} IN ({rendered})"
    return f"{column} IS NULL OR {clause}" if nullable else clause


class MessagingDocument(TimestampedMixin, Base):
    """Product messaging + positioning. Feeds the matcher's `fit` signal."""

    __tablename__ = "messaging_documents"
    __table_args__ = (
        Index("ix_messaging_documents_pillar_id", "pillar_id"),
        {"schema": "app"},
    )

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
    __table_args__ = (
        Index("ix_audience_profiles_pillar_id", "pillar_id"),
        {"schema": "app"},
    )

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

    # audience_focus is a denormalized list for fast filtering;
    # sme_audiences is authoritative for join-table traversal.
    audience_focus: Mapped[list[uuid.UUID]] = mapped_column(
        ARRAY(UUID(as_uuid=True)), nullable=False, server_default=text("ARRAY[]::uuid[]")
    )

    location_country: Mapped[str] = mapped_column(String(2), nullable=False)
    location_city: Mapped[str | None] = mapped_column(String(100))

    bio: Mapped[str] = mapped_column(Text, nullable=False)
    #: The person's own free-text description of what they work on. Appended
    #: to the bio at embed time, so it feeds bio-similarity directly. This
    #: replaced the "pick your topics from the extracted vocabulary" form
    #: field — see migration 20260729_1000 for why.
    expertise: Mapped[str] = mapped_column(Text, nullable=False, server_default="")
    languages: Mapped[list[str]] = mapped_column(
        ARRAY(String(2)), nullable=False, server_default=text("'{}'::varchar[]")
    )

    external_links: Mapped[dict] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )

    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))



class ConferenceSeries(TimestampedMixin, Base):
    """Year-over-year linkage. Seeded from db/seeds/conference_series.yaml."""

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


class Source(TimestampedMixin, Base):
    """Crawl targets configured by the user. services/scraper/ does the fetching."""

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
        # Declared so `alembic revision --autogenerate` sees it. Without
        # this, the next autogenerate proposes DROPPING the constraint the
        # participation migration created — the exact failure mode the note
        # above describes for event_kind, repeated one field later.
        CheckConstraint(
            _in_sql("attendance_verdict", ATTENDANCE_VERDICTS, nullable=True),
            name="attendance_verdict_allowed",
        ),
        Index("ix_conferences_assigned_pillar_id", "assigned_pillar_id"),
        {"schema": "app"},
    )

    id: Mapped[uuid.UUID] = uuid_pk()

    name: Mapped[str] = mapped_column(String(200), nullable=False)
    slug: Mapped[str] = mapped_column(String(200), nullable=False, unique=True)

    # What the event says it is about, EXTRACTED FROM ITS OWN PAGE.
    #
    # Distinct from enriched_description below, and the distinction is the
    # point: this is observed, that is generated. For a long time only the
    # generated one existed, so the matcher's strongest input and the LLM
    # judge's entire reasoning basis were built from a guess made off the
    # conference's name. The scraper had the real page the whole time —
    # extraction pulled dates and CFP links out of it and discarded the
    # prose.
    #
    # NULL when the page had no descriptive text (or the row predates
    # this column). conference_embed_text prefers this and falls back to
    # enriched_description, so enrichment keeps exactly one job: covering
    # rows that genuinely have no page to read.
    description: Mapped[str | None] = mapped_column(Text)

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
    # source; cfp_close_at is the earliest non-workshop
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
    # embedder. Populated on ingest (or on backfill) by app.services.conferences.
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


    # Migration A: what kind of event is this?
    event_kind: Mapped[str] = mapped_column(
        # TEXT, not String(20): that is what the DDL created. The mismatch made
        # every `--autogenerate` run emit a spurious ALTER, and a spurious
        # diff is how real ones get skimmed past.
        Text,
        nullable=False,
        server_default=text("'corporate'"),
    )
    # Migration A: human-assigned pillar (distinct from matcher-computed conference_pillars scores)
    assigned_pillar_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("app.strategic_pillars.id", ondelete="SET NULL"),
    )

    # --- which edition this is -------------------------------------------
    # Normally the year of start_date. Set on its own for events we only
    # know by name and year ("NeurIPS 2025", typed in from memory), where
    # inventing a start_date would put a date on screen that nobody
    # verified. series_id + edition_year identifies one edition.
    edition_year: Mapped[int | None] = mapped_column(SmallInteger)

    # --- what happened, once we have been ---------------------------------
    # All null until someone records attendance. A conference nobody went
    # to simply has no participation rows and no values here.
    #
    # spend_usd is what we ACTUALLY spent; estimated_cost_usd above is the
    # forecast made before deciding. Keeping both is the only way to learn
    # whether the forecast was any good.
    spend_usd: Mapped[int | None] = mapped_column(Integer)

    # How many leads the event produced. The last of the four things the
    # data model says an attended conference carries, and the only one
    # that had no representation anywhere — no column, no schema field, no
    # endpoint. Without it the feedback loop into matching carried a
    # three-value verdict and nothing else, so "was it worth it" could
    # never be answered with a number.
    #
    # Nullable and deferrable on purpose: the operator records it when
    # they have it, which is often weeks after the event.
    leads_generated: Mapped[int | None] = mapped_column(Integer)

    # Trip logistics: travel, lodging, booth/swag, sponsorship status.
    #
    # These were the brief's "logistics_placeholder" — the backend handed
    # the frontend a localStorage KEY and a list of field names, and the
    # values lived in one person's browser. They vanished on a cache
    # clear and were invisible to everyone else on the team, which for a
    # tool whose stated purpose is "full tracking of all of it" is the
    # wrong place for exactly the facts people most need to share.
    #
    # Free text on purpose. "Flights booked, Anna has the confirmation"
    # is the real shape of this information; a structured travel model
    # would be a guess at a workflow nobody described.
    logistics_travel: Mapped[str] = mapped_column(
        Text, nullable=False, server_default=text("''")
    )
    logistics_lodging: Mapped[str] = mapped_column(
        Text, nullable=False, server_default=text("''")
    )
    logistics_booth: Mapped[str] = mapped_column(
        Text, nullable=False, server_default=text("''")
    )
    logistics_sponsorship: Mapped[str] = mapped_column(
        Text, nullable=False, server_default=text("''")
    )
    # Roughly how many people were at the event. The primary measure of
    # reach for Developer Advocacy, where the point is awareness rather
    # than attributable revenue.
    audience_size_estimate: Mapped[int | None] = mapped_column(Integer)
    # The retrospective: knowing what we know now, would we go again?
    # Feeds the matcher's series_memory boost for the next edition.
    attendance_verdict: Mapped[str | None] = mapped_column(String(20))
    attendance_notes: Mapped[str] = mapped_column(
        Text, nullable=False, server_default=text("''")
    )


class Participation(TimestampedMixin, Base):
    """Who did what at one conference — one row per person, per activity.

    This is the table that replaced ``past_conferences``. The old design put
    a single array of SME ids on the event, which could say "these five
    people went" but never "Alice gave the talk and Bob worked the booth" —
    so the thing the team most wanted to track was the one thing it could
    not express.

    A person may appear more than once for one event when they genuinely
    did more than one thing (spoke AND staffed the booth); the unique
    constraint is on the combination, not the person.
    """

    __tablename__ = "participation"
    __table_args__ = (
        CheckConstraint(
            "activity IN ('talk', 'booth', 'attend', 'sponsor')",
            name="activity_allowed",
        ),
        CheckConstraint(
            "outcome IS NULL OR outcome IN "
            "('submitted', 'accepted', 'rejected', 'delivered', 'withdrawn')",
            name="outcome_allowed",
        ),
        # One person does one activity once per event. sme_id is nullable,
        # and Postgres treats NULLs as distinct in a unique index, so this
        # constrains known people only — deliberate, since two different
        # unmatched guest speakers must both be recordable.
        UniqueConstraint(
            "conference_id", "sme_id", "activity", name="uq_participation_person_activity"
        ),
        Index("ix_participation_conference_id", "conference_id"),
        Index("ix_participation_departs_on", "departs_on"),
        Index("ix_participation_sme_id", "sme_id"),
        {"schema": "app"},
    )

    id: Mapped[uuid.UUID] = uuid_pk()

    conference_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("app.conferences.id", ondelete="CASCADE"),
        nullable=False,
    )

    # Null when the person is not on the SME roster — an exec, a guest, a
    # name typed in from a spreadsheet. The row still counts as attendance.
    sme_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("app.smes.id", ondelete="SET NULL"),
    )
    # Always written, even when sme_id is set, so removing an SME from the
    # roster does not erase the fact that they were there.
    person_label: Mapped[str] = mapped_column(String(200), nullable=False)

    activity: Mapped[str] = mapped_column(String(20), nullable=False)
    # Which talk was given, when we track it in the talks library.
    talk_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("app.talks.id", ondelete="SET NULL"),
    )

    # When this person travels. Distinct from the conference's own dates:
    # people arrive late, leave early, or cover one day of three.
    #
    # These are what make a participation row a PLAN rather than a record.
    # A row with dates and no ``attended_at`` means "we intend to send
    # them"; that is the state the data model calls "on calendar", and it
    # is where a conference sits for most of its life.
    arrives_on: Mapped[date | None] = mapped_column(Date)
    departs_on: Mapped[date | None] = mapped_column(Date)

    # Set when someone confirms the person actually went.
    #
    # Attendance is deliberately NOT a status column. It is answered by
    # ``attended_at IS NOT NULL OR departs_on < today`` — an explicit
    # confirmation, or the dates having passed. Both routes the operator
    # asked for, and neither needs a background job to write anything.
    # See the decay pass (removed) for what happens when a cron owns a
    # state a human also owns.
    attended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    notes: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("''"))


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


class TalkSubmission(Base):
    """Record of a talk being submitted to a conference. Migration G."""

    __tablename__ = "talk_submissions"
    __table_args__ = (
        # Declared here as well as in the migration: without it
        # `--autogenerate` proposes DROPping it, and it is the only thing
        # preventing one talk being recorded twice against one conference
        # (which would silently corrupt the reuse-risk calculation).
        # Spelled out in full on purpose. base.py's "uq" convention is
        # uq_%(table_name)s_%(column_0_N_name)s — it keys off COLUMN names,
        # not %(constraint_name)s — so an explicit name is used verbatim and
        # the convention would otherwise produce
        # uq_talk_submissions_talk_id_conference_id, which is not what the
        # migration created.
        UniqueConstraint(
            "talk_id", "conference_id", name="uq_talk_submissions_talk_conference"
        ),
        # Mirrors the CHECK created in 20260603_0900. Declared here because
        # `alembic revision --autogenerate` compares the model against the
        # database and proposes DROPPING anything the model does not know
        # about — so an undeclared constraint is one unrelated autogenerate
        # away from being silently removed. Same failure the notes on
        # event_kind and participation.activity describe.
        #
        # NOTE the vocabularies differ on purpose-for-now: this allows
        # submitted/accepted/rejected/withdrawn, while participation.outcome
        # also allows 'delivered'. Two records of one fact; D13 resolves it.
        CheckConstraint(
            "outcome IN ('submitted', 'accepted', 'rejected', 'withdrawn') "
            "OR outcome IS NULL",
            name="talk_submissions_outcome_check",
        ),
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


# ==========================================================================
# db/models.py
# ==========================================================================



class ConferenceAudience(Base):
    __tablename__ = "conference_audiences"
    __table_args__ = {"schema": "app"}

    conference_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("app.conferences.id", ondelete="CASCADE"),
        primary_key=True,
    )
    audience_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("app.audience_profiles.id", ondelete="CASCADE"),
        primary_key=True,
    )
    weight: Mapped[float] = mapped_column(default=1.0, server_default=text("1.0"), nullable=False)


class ConferencePillar(Base):
    """Matcher-computed alignment between a conference and a strategic pillar."""

    __tablename__ = "conference_pillars"
    __table_args__ = {"schema": "app"}

    conference_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("app.conferences.id", ondelete="CASCADE"),
        primary_key=True,
    )
    pillar_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("app.strategic_pillars.id", ondelete="CASCADE"),
        primary_key=True,
    )
    score: Mapped[float] = mapped_column(default=0.0, server_default=text("0.0"), nullable=False)


class ConferenceSme(Base):
    """Matcher-computed recommendation. Written by the matcher pipeline."""

    __tablename__ = "conference_smes"
    __table_args__ = {"schema": "app"}

    conference_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("app.conferences.id", ondelete="CASCADE"),
        primary_key=True,
    )
    sme_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("app.smes.id", ondelete="CASCADE"),
        primary_key=True,
    )
    score: Mapped[float] = mapped_column(default=0.0, server_default=text("0.0"), nullable=False)



class SmeAudience(Base):
    __tablename__ = "sme_audiences"
    __table_args__ = {"schema": "app"}

    sme_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("app.smes.id", ondelete="CASCADE"),
        primary_key=True,
    )
    audience_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("app.audience_profiles.id", ondelete="CASCADE"),
        primary_key=True,
    )
    weight: Mapped[float] = mapped_column(default=1.0, server_default=text("1.0"), nullable=False)


class SmePillar(Base):
    """Junction: SME ↔ pillar (many-to-many). Migration C."""

    __tablename__ = "sme_pillars"
    __table_args__ = (
        Index("ix_sme_pillars_pillar_id", "pillar_id"),
        {"schema": "app"},
    )

    sme_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("app.smes.id", ondelete="CASCADE"),
        primary_key=True,
    )
    pillar_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("app.strategic_pillars.id", ondelete="CASCADE"),
        primary_key=True,
    )
    # server_default, not default: the column has had a DB-level default
    # since the baseline migration, and declaring only a Python-side
    # default left the model permanently out of step with the schema —
    # enough to make `alembic check` fail on an untouched database.
    is_primary: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )



# ==========================================================================
# db/models.py
# ==========================================================================


class Match(TimestampedMixin, Base):
    """Matcher output. One row per conference per algorithm_version."""

    __tablename__ = "matches"
    __table_args__ = (
        CheckConstraint(
            "judge_verdict IS NULL OR judge_verdict IN ('ok', 'veto')",
            name="judge_verdict_allowed",
        ),
        {"schema": "app"},
    )

    id: Mapped[uuid.UUID] = uuid_pk()

    conference_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("app.conferences.id", ondelete="CASCADE"),
        nullable=False,
    )

    # The two ranking signals. Persisted so the conference list can
    # recompute the overall score live without re-running the matcher.
    # These replaced messaging_score / pillar_score / sme_score: the first
    # two correlated at r=0.86 and were one question asked twice.
    fit_score: Mapped[float] = mapped_column(nullable=False)
    speaker_score: Mapped[float] = mapped_column(nullable=False)
    # The judge's verdict: 'ok', 'veto', or NULL when it has not run.
    # NOT a score — it is deliberately outside overall_score, because a veto
    # averaged into a weighted mean produces a number nobody can explain.
    judge_verdict: Mapped[str | None] = mapped_column(String(10))
    # One sentence, shown to a human in the review queue. Empty unless vetoed.
    judge_reason: Mapped[str] = mapped_column(
        Text, nullable=False, server_default=text("''")
    )
    # Fingerprint of everything that went into the prompt. Lets a re-run skip
    # the model call when nothing relevant changed — most of the LLM cost on
    # a full rescore.
    judge_input_hash: Mapped[str | None] = mapped_column(CHAR(64))

    overall_score: Mapped[float] = mapped_column(nullable=False)

    recommended_sme_ids: Mapped[list[uuid.UUID]] = mapped_column(
        ARRAY(UUID(as_uuid=True)), nullable=False, server_default=text("ARRAY[]::uuid[]")
    )
    rationale_text: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("''"))

    algorithm_version: Mapped[str] = mapped_column(String(40), nullable=False)
    computed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class Decision(TimestampedMixin, Base):
    """Human approve/reject/needs-review actions."""

    __tablename__ = "decisions"
    __table_args__ = {"schema": "app"}

    id: Mapped[uuid.UUID] = uuid_pk()

    conference_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("app.conferences.id", ondelete="CASCADE"),
        nullable=False,
    )
    decided_by_label: Mapped[str] = mapped_column(
        String(120), nullable=False, server_default=text("''")
    )
    decision: Mapped[str] = mapped_column(String(20), nullable=False)
    reason: Mapped[str | None] = mapped_column(Text)
    decided_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )


# ==========================================================================
# db/models.py
# ==========================================================================


class EmbeddingModel(TimestampedMixin, Base):
    """Registry of embedding models. Lets us roll over to a new model
    without losing the old vectors — chunks carry the model_id they were
    embedded under."""

    __tablename__ = "embedding_models"
    __table_args__ = {"schema": "vectors"}

    id: Mapped[uuid.UUID] = uuid_pk()

    name: Mapped[str] = mapped_column(String(120), nullable=False, unique=True)
    provider: Mapped[str] = mapped_column(String(60), nullable=False)
    dimension: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=sql_text("false")
    )
    # Set by the rollover migration when a model is retired, never by
    # application code — which is why a grep for it finds only migrations.
    # It is operational metadata for a human doing a model swap.
    deprecated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class DocumentChunk(TimestampedMixin, Base):
    """Chunked + embedded text produced by Docling's HybridChunker.

    ``owner_type`` + ``owner_id`` is a polymorphic ref (no FK constraint at
    the DB level since the owner table varies). The application layer keeps
    these in sync.
    """

    __tablename__ = "document_chunks"
    __table_args__ = (
        Index("ix_document_chunks_owner", "owner_type", "owner_id"),
        # HNSW index on `embedding` is created by the initial migration via
        # raw SQL (Alembic doesn't expose pgvector index params).
        {"schema": "vectors"},
    )

    id: Mapped[uuid.UUID] = uuid_pk()

    owner_type: Mapped[str] = mapped_column(String(30), nullable=False)
    owner_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)

    chunk_index: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    token_count: Mapped[int] = mapped_column(SmallInteger, nullable=False)

    embedding_model_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("vectors.embedding_models.id", ondelete="RESTRICT"),
        nullable=False,
    )
    embedding: Mapped[list[float]] = mapped_column(Vector(768), nullable=False)

    # Docling structural info: {section_heading, page_number, content_type}.
    # `{}` for non-document inputs (manual messaging entries, SME bios).
    #
    # Written by both embedding paths; nothing reads it yet. Kept anyway,
    # unlike the other write-only things this codebase has shed: it is a
    # column on rows that get written regardless, so the marginal cost is
    # a JSONB field, and it is exactly what a citation needs to say "page 7,
    # under 'Deployment'". The extraction is already done — throwing it
    # away means re-deriving it the day the agent wants page numbers.
    chunk_metadata: Mapped[dict] = mapped_column(
        JSONB, nullable=False, server_default=sql_text("'{}'::jsonb")
    )

    # Bumped on retrieval; drives the decay pass.
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


# ==========================================================================
# db/models.py
# ==========================================================================


class IngestJob(TimestampedMixin, Base):
    """Each scrape, extraction, match, decay run lands a row here."""

    __tablename__ = "ingest_jobs"
    __table_args__ = {"schema": "app"}

    id: Mapped[uuid.UUID] = uuid_pk()

    kind: Mapped[str] = mapped_column(String(60), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    stats: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    error_text: Mapped[str | None] = mapped_column(Text)


class LLMCall(Base):
    """Every LLM call. NO TimestampedMixin — we use ``created_at`` only
    (no UPDATE semantics for an append-only log)."""

    __tablename__ = "llm_calls"
    __table_args__ = (
        Index("ix_llm_calls_created_at", "created_at"),
        Index("ix_llm_calls_purpose", "purpose"),
        {"schema": "app"},
    )

    id: Mapped[uuid.UUID] = uuid_pk()

    model: Mapped[str] = mapped_column(String(120), nullable=False)
    purpose: Mapped[str] = mapped_column(String(40), nullable=False)
    prompt_tokens: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    completion_tokens: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0")
    )
    cost_usd: Mapped[Decimal] = mapped_column(
        Numeric(10, 6), nullable=False, server_default=text("0")
    )
    latency_ms: Mapped[int | None] = mapped_column(Integer)
    request_id: Mapped[str | None] = mapped_column(String(60))
    error: Mapped[str | None] = mapped_column(Text)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )


class ChatSession(TimestampedMixin, Base):
    """Agent chat session. One conversation per row."""

    __tablename__ = "chat_sessions"
    __table_args__ = {"schema": "app"}

    id: Mapped[uuid.UUID] = uuid_pk()

    title: Mapped[str | None] = mapped_column(String(200))
    archived: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))


class ChatMessage(Base):
    """One turn (user or assistant) in a chat_session."""

    __tablename__ = "chat_messages"
    __table_args__ = (
        Index("ix_chat_messages_session", "session_id", "created_at"),
        {"schema": "app"},
    )

    id: Mapped[uuid.UUID] = uuid_pk()

    session_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("app.chat_sessions.id", ondelete="CASCADE"),
        nullable=False,
    )
    role: Mapped[str] = mapped_column(String(20), nullable=False)  # user / assistant / system
    content: Mapped[str] = mapped_column(Text, nullable=False)

    # Citations + intent classification + token usage
    metadata_json: Mapped[dict] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )


class Notification(Base):
    """In-app notifications (bell badge). The CFP digest job writes here."""

    __tablename__ = "notifications"
    __table_args__ = (
        Index("ix_notifications_unread", "seen", "created_at"),
        {"schema": "app"},
    )

    id: Mapped[uuid.UUID] = uuid_pk()

    kind: Mapped[str] = mapped_column(String(40), nullable=False)
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    seen: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )


class AppSettingOverride(Base):
    """Singleton-style key/value overrides for app/settings.py values.

    Populated via ``PATCH /api/v1/admin/settings`` so admins can tune
    matcher weights, decay flags, LLM keys/models/budget, etc. without
    editing ``.env``. This table is the runtime source of truth: env vars
    are boot defaults only. Loaded into the Pydantic Settings instance at
    startup, then re-read every ``settings_refresh_seconds`` by every
    process (api replicas + standalone scheduler, see
    ``app.services.settings_store``), so a PATCH — including an
    LLM_API_KEY rotation — propagates everywhere without a restart.
    """

    __tablename__ = "app_setting_overrides"
    __table_args__ = {"schema": "app"}

    name: Mapped[str] = mapped_column(String(80), primary_key=True)
    value: Mapped[str] = mapped_column(Text, nullable=False)  # JSON-encoded scalar/list
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    actor_label: Mapped[str] = mapped_column(
        String(120), nullable=False, server_default=text("'system'")
    )


class OpsState(Base):
    """Operational state the app remembers — NOT settings.

    A tiny key-value table for things the deployment needs to recall
    across restarts but which nobody configures: watermarks, "last time
    someone dismissed X", and similar.

    It exists because ``app_setting_overrides`` was becoming the default
    home for these. The diagnostics page parked its
    "errors cleared at" timestamp there, which meant a table named for
    operator-editable settings held a value that is not a setting, is not
    a field on ``Settings``, and would never appear on the settings page.

    The distinction is worth a table: ``app_setting_overrides`` feeds
    ``get_settings()`` and every row in it should correspond to something
    an operator can see and change. Anything else belongs here.
    """

    __tablename__ = "ops_state"
    __table_args__ = {"schema": "app"}

    key: Mapped[str] = mapped_column(String(80), primary_key=True)
    value: Mapped[str] = mapped_column(Text, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )


# ==========================================================================
# db/models.py
# ==========================================================================


class AuditLog(Base):
    """Append-only audit trail. NO TimestampedMixin: we use ``at`` as the
    canonical timestamp; ``created_at``/``updated_at`` don't apply to an
    append-only log."""

    __tablename__ = "audit_log"
    __table_args__ = (
        Index("ix_audit_log_at", "at"),
        {"schema": "audit"},
    )

    id: Mapped[uuid.UUID] = uuid_pk()

    actor_label: Mapped[str] = mapped_column(
        String(120), nullable=False, server_default=text("'system'")
    )
    action: Mapped[str] = mapped_column(String(60), nullable=False)
    target_type: Mapped[str] = mapped_column(String(60), nullable=False)
    target_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)

    before: Mapped[dict | None] = mapped_column(JSONB)
    after: Mapped[dict | None] = mapped_column(JSONB)

    at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )


__all__ = [
    "NAMING_CONVENTION",
    "AppSettingOverride",
    "AudienceProfile",
    "AuditLog",
    "Base",
    "ChatMessage",
    "ChatSession",
    "Conference",
    "ConferenceAudience",
    "ConferencePillar",
    "ConferenceSeries",
    "ConferenceSme",
    "ConferenceSource",
    "Decision",
    "DocumentChunk",
    "EmbeddingModel",
    "IngestJob",
    "LLMCall",
    "Match",
    "MessagingDocument",
    "Notification",
    "OpsState",
    "Participation",
    "RawPage",
    "Sme",
    "SmeAudience",
    "SmePillar",
    "Source",
    "StrategicPillar",
    "Talk",
    "TalkSubmission",
    "TimestampedMixin",
    "uuid_pk",
]
