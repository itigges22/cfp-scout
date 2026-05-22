"""initial baseline

Encodes every table from PLANS/phase-1/04-database-schema.md and
docs/data-model.md. This is the *only* hand-crafted migration — all
subsequent ones should be generated via ``make migrate-create``.

Revision ID: 20260521_1200_baseline
Revises:
Create Date: 2026-05-21 12:00:00
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "20260521_1200_baseline"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


# ---------------------------------------------------------------------------
# Helpers used many times
# ---------------------------------------------------------------------------
UUID_PK_ARGS = dict(
    server_default=sa.text("gen_random_uuid()"),
    primary_key=True,
)


def _id_col() -> sa.Column:
    return sa.Column("id", postgresql.UUID(as_uuid=True), **UUID_PK_ARGS)


def _timestamps() -> list[sa.Column]:
    return [
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    ]


def upgrade() -> None:
    # ---------------------------------------------------------------------
    # app schema — manual inputs
    # ---------------------------------------------------------------------
    op.create_table(
        "messaging_documents",
        _id_col(),
        sa.Column("title", sa.String(120), nullable=False),
        sa.Column("source_type", sa.String(20), nullable=False),
        sa.Column("file_path", sa.Text),
        sa.Column("elevator_pitch", sa.Text, nullable=False),
        sa.Column("target_personas", postgresql.ARRAY(sa.Text), nullable=False),
        sa.Column("key_themes", postgresql.ARRAY(sa.Text), nullable=False),
        sa.Column("talking_points", postgresql.ARRAY(sa.Text), nullable=False),
        sa.Column(
            "differentiators",
            postgresql.ARRAY(sa.Text),
            nullable=False,
            server_default=sa.text("'{}'::text[]"),
        ),
        sa.Column(
            "competitive_position",
            sa.Text,
            nullable=False,
            server_default=sa.text("''"),
        ),
        sa.Column("raw_content", sa.Text),
        sa.Column(
            "is_active",
            sa.Boolean,
            nullable=False,
            server_default=sa.text("true"),
        ),
        *_timestamps(),
        schema="app",
    )

    op.create_table(
        "audience_profiles",
        _id_col(),
        sa.Column("name", sa.String(80), nullable=False),
        sa.Column("description", sa.Text, nullable=False),
        sa.Column("industry", sa.String(80), nullable=False),
        sa.Column("role_seniority", sa.String(20), nullable=False),
        sa.Column("primary_pain_points", postgresql.ARRAY(sa.Text), nullable=False),
        sa.Column("key_messages", postgresql.ARRAY(sa.Text), nullable=False),
        sa.Column(
            "exclusion_criteria",
            postgresql.ARRAY(sa.Text),
            nullable=False,
            server_default=sa.text("'{}'::text[]"),
        ),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default=sa.text("true")),
        *_timestamps(),
        sa.UniqueConstraint("name", name="uq_audience_profiles_name"),
        schema="app",
    )

    op.create_table(
        "strategic_pillars",
        _id_col(),
        sa.Column("name", sa.String(80), nullable=False),
        sa.Column("description", sa.Text, nullable=False),
        sa.Column("display_order", sa.SmallInteger, nullable=False),
        *_timestamps(),
        sa.UniqueConstraint("name", name="uq_strategic_pillars_name"),
        schema="app",
    )

    op.create_table(
        "smes",
        _id_col(),
        sa.Column("full_name", sa.String(100), nullable=False),
        sa.Column("email", sa.String(200)),
        sa.Column("team", sa.String(60), nullable=False),
        sa.Column("expertise_areas", postgresql.ARRAY(sa.Text), nullable=False),
        sa.Column(
            "primary_topics",
            postgresql.ARRAY(postgresql.UUID(as_uuid=True)),
            nullable=False,
            server_default=sa.text("ARRAY[]::uuid[]"),
        ),
        sa.Column(
            "audience_focus",
            postgresql.ARRAY(postgresql.UUID(as_uuid=True)),
            nullable=False,
            server_default=sa.text("ARRAY[]::uuid[]"),
        ),
        sa.Column("location_country", sa.String(2), nullable=False),
        sa.Column("location_city", sa.String(100)),
        sa.Column("bio", sa.Text, nullable=False),
        sa.Column(
            "languages",
            postgresql.ARRAY(sa.String(2)),
            nullable=False,
            server_default=sa.text("'{}'::varchar[]"),
        ),
        sa.Column(
            "external_links",
            postgresql.JSONB,
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default=sa.text("true")),
        *_timestamps(),
        schema="app",
    )

    op.create_table(
        "topics",
        _id_col(),
        sa.Column("name", sa.String(60), nullable=False),
        sa.Column("slug", sa.String(80), nullable=False),
        sa.Column(
            "aliases",
            postgresql.ARRAY(sa.Text),
            nullable=False,
            server_default=sa.text("'{}'::text[]"),
        ),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default=sa.text("true")),
        sa.Column("pending_review", sa.Boolean, nullable=False, server_default=sa.text("false")),
        *_timestamps(),
        sa.UniqueConstraint("name", name="uq_topics_name"),
        sa.UniqueConstraint("slug", name="uq_topics_slug"),
        schema="app",
    )

    op.create_table(
        "conference_series",
        _id_col(),
        sa.Column("canonical_name", sa.String(150), nullable=False),
        sa.Column(
            "aliases",
            postgresql.ARRAY(sa.Text),
            nullable=False,
            server_default=sa.text("'{}'::text[]"),
        ),
        sa.Column("description", sa.Text, nullable=False, server_default=sa.text("''")),
        sa.Column("typical_month", sa.SmallInteger),
        sa.Column(
            "typical_topics",
            postgresql.ARRAY(sa.Text),
            nullable=False,
            server_default=sa.text("'{}'::text[]"),
        ),
        sa.Column("homepage", sa.Text),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default=sa.text("true")),
        *_timestamps(),
        sa.UniqueConstraint("canonical_name", name="uq_conference_series_canonical_name"),
        schema="app",
    )

    op.create_table(
        "past_conferences",
        _id_col(),
        sa.Column("name", sa.String(150), nullable=False),
        sa.Column("year", sa.SmallInteger, nullable=False),
        sa.Column(
            "series_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("app.conference_series.id", ondelete="SET NULL"),
        ),
        sa.Column(
            "attended_sme_ids",
            postgresql.ARRAY(postgresql.UUID(as_uuid=True)),
            nullable=False,
        ),
        sa.Column("role", sa.String(20), nullable=False),
        sa.Column("session_type", sa.String(20)),
        sa.Column("notes", sa.Text, nullable=False, server_default=sa.text("''")),
        sa.Column("imported_from", sa.String(120)),
        *_timestamps(),
        schema="app",
    )

    # ---------------------------------------------------------------------
    # app schema — scraper / discovery
    # ---------------------------------------------------------------------
    op.create_table(
        "sources",
        _id_col(),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("url", sa.Text, nullable=False),
        sa.Column("kind", sa.String(20), nullable=False),
        sa.Column("enabled", sa.Boolean, nullable=False, server_default=sa.text("true")),
        sa.Column("last_crawled_at", sa.Date),
        sa.Column("crawl_cadence", sa.Text, nullable=False, server_default=sa.text("'1 day'")),
        sa.Column("robots_allowed", sa.Boolean, nullable=False, server_default=sa.text("true")),
        sa.Column(
            "politeness_delay_seconds",
            sa.SmallInteger,
            nullable=False,
            server_default=sa.text("3"),
        ),
        sa.Column("notes", sa.Text),
        *_timestamps(),
        schema="app",
    )

    op.create_table(
        "raw_pages",
        _id_col(),
        sa.Column(
            "source_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("app.sources.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("url", sa.Text, nullable=False),
        sa.Column("fetched_at", sa.Date, nullable=False),
        sa.Column("http_status", sa.SmallInteger, nullable=False),
        sa.Column("content_type", sa.String(120), nullable=False),
        sa.Column("raw_body_path", sa.Text, nullable=False),
        sa.Column("hash", sa.String(64), nullable=False),
        sa.Column("etag", sa.Text),
        sa.Column("last_modified", sa.Text),
        sa.Column("parse_status", sa.String(30)),
        *_timestamps(),
        sa.UniqueConstraint("hash", name="uq_raw_pages_hash"),
        schema="app",
    )
    op.create_index(
        "ix_raw_pages_url_fetched_at",
        "raw_pages",
        ["url", "fetched_at"],
        schema="app",
    )

    op.create_table(
        "conferences",
        _id_col(),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("slug", sa.String(200), nullable=False),
        sa.Column("start_date", sa.Date),
        sa.Column("end_date", sa.Date),
        sa.Column("location_city", sa.String(120)),
        sa.Column("location_country", sa.String(2)),
        sa.Column("is_virtual", sa.Boolean, nullable=False, server_default=sa.text("false")),
        sa.Column("venue", sa.String(200)),
        sa.Column("website", sa.Text),
        sa.Column("cfp_open_at", sa.Date),
        sa.Column("cfp_close_at", sa.Date),
        sa.Column(
            "cfp_deadlines",
            postgresql.JSONB,
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column(
            "cfp_topics_of_interest",
            postgresql.ARRAY(sa.Text),
            nullable=False,
            server_default=sa.text("'{}'::text[]"),
        ),
        sa.Column("acceptance_rate_percent", sa.SmallInteger),
        sa.Column("estimated_cost_usd", sa.Integer),
        sa.Column(
            "topics",
            postgresql.ARRAY(sa.Text),
            nullable=False,
            server_default=sa.text("'{}'::text[]"),
        ),
        sa.Column("confidence_score", sa.Float),
        sa.Column(
            "status",
            sa.String(40),
            nullable=False,
            server_default=sa.text("'discovered'"),
        ),
        sa.Column(
            "series_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("app.conference_series.id", ondelete="SET NULL"),
        ),
        sa.Column("freshness_score", sa.Float, nullable=False, server_default=sa.text("1.0")),
        *_timestamps(),
        sa.UniqueConstraint("slug", name="uq_conferences_slug"),
        schema="app",
    )
    op.create_index("ix_conferences_start_date", "conferences", ["start_date"], schema="app")
    op.create_index(
        "ix_conferences_status_active",
        "conferences",
        ["status", "start_date"],
        postgresql_where=sa.text(
            "status IN ('discovered', 'needs_review', 'needs_review_pillar', "
            "'needs_sme_review', 'approved')"
        ),
        schema="app",
    )
    op.create_index(
        "ix_conferences_topics_gin",
        "conferences",
        ["topics"],
        postgresql_using="gin",
        schema="app",
    )

    op.create_table(
        "conference_sources",
        sa.Column(
            "conference_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("app.conferences.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "raw_page_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("app.raw_pages.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        schema="app",
    )

    # ---------------------------------------------------------------------
    # app schema — junction tables (the graph edges)
    # ---------------------------------------------------------------------
    op.create_table(
        "conference_topics",
        sa.Column(
            "conference_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("app.conferences.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "topic_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("app.topics.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("weight", sa.Float, nullable=False, server_default=sa.text("1.0")),
        schema="app",
    )

    op.create_table(
        "conference_audiences",
        sa.Column(
            "conference_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("app.conferences.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "audience_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("app.audience_profiles.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("weight", sa.Float, nullable=False, server_default=sa.text("1.0")),
        schema="app",
    )

    op.create_table(
        "conference_pillars",
        sa.Column(
            "conference_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("app.conferences.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "pillar_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("app.strategic_pillars.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("score", sa.Float, nullable=False, server_default=sa.text("0.0")),
        schema="app",
    )

    op.create_table(
        "conference_smes",
        sa.Column(
            "conference_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("app.conferences.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "sme_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("app.smes.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("score", sa.Float, nullable=False, server_default=sa.text("0.0")),
        schema="app",
    )

    op.create_table(
        "sme_topics",
        sa.Column(
            "sme_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("app.smes.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "topic_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("app.topics.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("weight", sa.Float, nullable=False, server_default=sa.text("1.0")),
        schema="app",
    )

    op.create_table(
        "sme_audiences",
        sa.Column(
            "sme_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("app.smes.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "audience_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("app.audience_profiles.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("weight", sa.Float, nullable=False, server_default=sa.text("1.0")),
        schema="app",
    )

    op.create_table(
        "messaging_pillars",
        sa.Column(
            "messaging_document_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("app.messaging_documents.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "pillar_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("app.strategic_pillars.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("weight", sa.Float, nullable=False, server_default=sa.text("1.0")),
        schema="app",
    )

    # ---------------------------------------------------------------------
    # vectors schema — embeddings
    # ---------------------------------------------------------------------
    op.create_table(
        "embedding_models",
        _id_col(),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("provider", sa.String(60), nullable=False),
        sa.Column("dimension", sa.SmallInteger, nullable=False),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default=sa.text("false")),
        sa.Column("deprecated_at", sa.DateTime(timezone=True)),
        *_timestamps(),
        sa.UniqueConstraint("name", name="uq_embedding_models_name"),
        schema="vectors",
    )

    # Create document_chunks WITHOUT the embedding column first; pgvector
    # types don't reliably round-trip through alembic's type registration
    # across versions, so we add `embedding vector(768)` via raw SQL below.
    op.create_table(
        "document_chunks",
        _id_col(),
        sa.Column("owner_type", sa.String(30), nullable=False),
        sa.Column("owner_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("chunk_index", sa.SmallInteger, nullable=False),
        sa.Column("text", sa.Text, nullable=False),
        sa.Column("token_count", sa.SmallInteger, nullable=False),
        sa.Column(
            "embedding_model_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("vectors.embedding_models.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "chunk_metadata",
            postgresql.JSONB,
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("last_used_at", sa.DateTime(timezone=True)),
        *_timestamps(),
        schema="vectors",
    )
    # Add the pgvector column via raw SQL. The `vector` extension is loaded
    # by 01-extensions.sql before any migration runs, so this is safe.
    op.execute("ALTER TABLE vectors.document_chunks ADD COLUMN embedding vector(768) NOT NULL;")

    op.create_index(
        "ix_document_chunks_owner",
        "document_chunks",
        ["owner_type", "owner_id"],
        schema="vectors",
    )
    # HNSW index on the embedding column. Raw SQL — Alembic doesn't expose
    # pgvector-specific index parameters.
    op.execute(
        "CREATE INDEX ix_document_chunks_embedding_hnsw "
        "ON vectors.document_chunks USING hnsw (embedding vector_cosine_ops) "
        "WITH (m = 16, ef_construction = 64);"
    )

    # ---------------------------------------------------------------------
    # app schema — match output
    # ---------------------------------------------------------------------
    op.create_table(
        "matches",
        _id_col(),
        sa.Column(
            "conference_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("app.conferences.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("messaging_score", sa.Float, nullable=False),
        sa.Column("pillar_score", sa.Float, nullable=False),
        sa.Column("sme_score", sa.Float, nullable=False),
        sa.Column("overall_score", sa.Float, nullable=False),
        sa.Column(
            "recommended_sme_ids",
            postgresql.ARRAY(postgresql.UUID(as_uuid=True)),
            nullable=False,
            server_default=sa.text("ARRAY[]::uuid[]"),
        ),
        sa.Column("rationale_text", sa.Text, nullable=False, server_default=sa.text("''")),
        sa.Column(
            "sme_fit_narratives",
            postgresql.JSONB,
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("algorithm_version", sa.String(40), nullable=False),
        sa.Column("computed_at", sa.DateTime(timezone=True), nullable=False),
        *_timestamps(),
        schema="app",
    )

    op.create_table(
        "match_team_recommendations",
        sa.Column(
            "match_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("app.matches.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("team_size", sa.SmallInteger, primary_key=True),
        sa.Column(
            "sme_ids",
            postgresql.ARRAY(postgresql.UUID(as_uuid=True)),
            nullable=False,
        ),
        sa.Column("team_score", sa.Float, nullable=False),
        sa.Column("coverage_breadth", sa.Float, nullable=False),
        sa.Column("redundancy", sa.Float, nullable=False),
        sa.Column("rationale_text", sa.Text, nullable=False, server_default=sa.text("''")),
        sa.Column(
            "computed_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint(
            "team_size IN (1, 2, 3)", name="ck_match_team_recommendations_team_size_range"
        ),
        schema="app",
    )

    op.create_table(
        "decisions",
        _id_col(),
        sa.Column(
            "conference_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("app.conferences.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "decided_by_label",
            sa.String(120),
            nullable=False,
            server_default=sa.text("''"),
        ),
        sa.Column("decision", sa.String(20), nullable=False),
        sa.Column("reason", sa.Text),
        sa.Column(
            "decided_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        *_timestamps(),
        schema="app",
    )

    # ---------------------------------------------------------------------
    # audit schema — append-only (role-level INSERT+SELECT only)
    # ---------------------------------------------------------------------
    op.create_table(
        "audit_log",
        _id_col(),
        sa.Column(
            "actor_label",
            sa.String(120),
            nullable=False,
            server_default=sa.text("'system'"),
        ),
        sa.Column("action", sa.String(60), nullable=False),
        sa.Column("target_type", sa.String(60), nullable=False),
        sa.Column("target_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("before", postgresql.JSONB),
        sa.Column("after", postgresql.JSONB),
        sa.Column(
            "at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        schema="audit",
    )
    op.create_index("ix_audit_log_at", "audit_log", ["at"], schema="audit")

    op.create_table(
        "content_versions",
        _id_col(),
        sa.Column("entity_type", sa.String(60), nullable=False),
        sa.Column("entity_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("version_number", sa.Integer, nullable=False),
        sa.Column("diff", postgresql.JSONB, nullable=False),
        sa.Column(
            "actor_label",
            sa.String(120),
            nullable=False,
            server_default=sa.text("'system'"),
        ),
        sa.Column(
            "changed_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("reason", sa.Text),
        schema="audit",
    )
    op.create_index(
        "ix_content_versions_entity",
        "content_versions",
        ["entity_type", "entity_id"],
        schema="audit",
    )

    # ---------------------------------------------------------------------
    # app schema — operational
    # ---------------------------------------------------------------------
    op.create_table(
        "ingest_jobs",
        _id_col(),
        sa.Column("kind", sa.String(60), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.Column(
            "stats",
            postgresql.JSONB,
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("error_text", sa.Text),
        *_timestamps(),
        schema="app",
    )

    op.create_table(
        "llm_calls",
        _id_col(),
        sa.Column("model", sa.String(120), nullable=False),
        sa.Column("purpose", sa.String(40), nullable=False),
        sa.Column("prompt_tokens", sa.Integer, nullable=False, server_default=sa.text("0")),
        sa.Column("completion_tokens", sa.Integer, nullable=False, server_default=sa.text("0")),
        sa.Column(
            "cost_usd",
            sa.Numeric(10, 6),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column("latency_ms", sa.Integer),
        sa.Column("request_id", sa.String(60)),
        sa.Column("error", sa.Text),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        schema="app",
    )
    op.create_index("ix_llm_calls_created_at", "llm_calls", ["created_at"], schema="app")
    op.create_index("ix_llm_calls_purpose", "llm_calls", ["purpose"], schema="app")

    op.create_table(
        "chat_sessions",
        _id_col(),
        sa.Column("title", sa.String(200)),
        sa.Column("archived", sa.Boolean, nullable=False, server_default=sa.text("false")),
        *_timestamps(),
        schema="app",
    )

    op.create_table(
        "chat_messages",
        _id_col(),
        sa.Column(
            "session_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("app.chat_sessions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("role", sa.String(20), nullable=False),
        sa.Column("content", sa.Text, nullable=False),
        sa.Column(
            "metadata_json",
            postgresql.JSONB,
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        schema="app",
    )
    op.create_index(
        "ix_chat_messages_session",
        "chat_messages",
        ["session_id", "created_at"],
        schema="app",
    )

    op.create_table(
        "notifications",
        _id_col(),
        sa.Column("kind", sa.String(40), nullable=False),
        sa.Column(
            "payload",
            postgresql.JSONB,
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("seen", sa.Boolean, nullable=False, server_default=sa.text("false")),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        schema="app",
    )
    op.create_index(
        "ix_notifications_unread",
        "notifications",
        ["seen", "created_at"],
        schema="app",
    )


def downgrade() -> None:
    # Reverse order — FK-dependent tables first.
    op.drop_index("ix_notifications_unread", table_name="notifications", schema="app")
    op.drop_table("notifications", schema="app")

    op.drop_index("ix_chat_messages_session", table_name="chat_messages", schema="app")
    op.drop_table("chat_messages", schema="app")
    op.drop_table("chat_sessions", schema="app")

    op.drop_index("ix_llm_calls_purpose", table_name="llm_calls", schema="app")
    op.drop_index("ix_llm_calls_created_at", table_name="llm_calls", schema="app")
    op.drop_table("llm_calls", schema="app")

    op.drop_table("ingest_jobs", schema="app")

    op.drop_index("ix_content_versions_entity", table_name="content_versions", schema="audit")
    op.drop_table("content_versions", schema="audit")

    op.drop_index("ix_audit_log_at", table_name="audit_log", schema="audit")
    op.drop_table("audit_log", schema="audit")

    op.drop_table("decisions", schema="app")
    op.drop_table("match_team_recommendations", schema="app")
    op.drop_table("matches", schema="app")

    op.execute("DROP INDEX IF EXISTS vectors.ix_document_chunks_embedding_hnsw;")
    op.drop_index("ix_document_chunks_owner", table_name="document_chunks", schema="vectors")
    op.drop_table("document_chunks", schema="vectors")
    op.drop_table("embedding_models", schema="vectors")

    op.drop_table("messaging_pillars", schema="app")
    op.drop_table("sme_audiences", schema="app")
    op.drop_table("sme_topics", schema="app")
    op.drop_table("conference_smes", schema="app")
    op.drop_table("conference_pillars", schema="app")
    op.drop_table("conference_audiences", schema="app")
    op.drop_table("conference_topics", schema="app")

    op.drop_table("conference_sources", schema="app")

    op.drop_index("ix_conferences_topics_gin", table_name="conferences", schema="app")
    op.drop_index("ix_conferences_status_active", table_name="conferences", schema="app")
    op.drop_index("ix_conferences_start_date", table_name="conferences", schema="app")
    op.drop_table("conferences", schema="app")

    op.drop_index("ix_raw_pages_url_fetched_at", table_name="raw_pages", schema="app")
    op.drop_table("raw_pages", schema="app")
    op.drop_table("sources", schema="app")

    op.drop_table("past_conferences", schema="app")
    op.drop_table("conference_series", schema="app")
    op.drop_table("topics", schema="app")
    op.drop_table("smes", schema="app")
    op.drop_table("strategic_pillars", schema="app")
    op.drop_table("audience_profiles", schema="app")
    op.drop_table("messaging_documents", schema="app")
