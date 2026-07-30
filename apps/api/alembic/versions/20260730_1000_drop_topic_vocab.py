"""Drop the topic-vocabulary system.

THE PROBLEM
    The vocabulary was machine-extracted (130+ entries at removal time)
    and asked SMEs to describe themselves by picking from it. Nobody did:
    at removal, sme_topics and talk_topics were both EMPTY and the
    matcher's topic dimension — weight 0.30 — dropped for every SME on
    every score, its weight silently renormalised away.

WHAT CHANGES
    The four vocabulary tables go, along with smes.primary_topics. The
    free-text ``smes.expertise`` column (embedded with the bio, weight
    now 0.60 on bio_similarity) is the replacement: topical matching
    happens in embedding space, where "makes a model think longer at
    answer time" can match an inference-scaling conference by meaning.

    ``conferences.topics`` — the plain string array shown in the UI and
    used for display — is untouched; it never depended on these tables.

DOWNGRADE
    Recreates empty structures. The 133 vocabulary rows are
    machine-regenerable by discovery and are not preserved.
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import ARRAY, UUID

from alembic import op

revision = "20260730_1000"
down_revision = "20260729_1000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_table("conference_topics", schema="app")
    op.drop_table("sme_topics", schema="app")
    op.drop_table("talk_topics", schema="app")
    op.drop_table("topics", schema="app")
    op.drop_column("smes", "primary_topics", schema="app")


def downgrade() -> None:
    op.add_column(
        "smes",
        sa.Column(
            "primary_topics",
            ARRAY(UUID(as_uuid=True)),
            nullable=False,
            server_default=sa.text("ARRAY[]::uuid[]"),
        ),
        schema="app",
    )
    op.create_table(
        "topics",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("name", sa.String(60), nullable=False, unique=True),
        sa.Column("slug", sa.String(80), nullable=False, unique=True),
        sa.Column("aliases", ARRAY(sa.Text), nullable=False, server_default=sa.text("'{}'::text[]")),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default=sa.text("true")),
        sa.Column("pending_review", sa.Boolean, nullable=False, server_default=sa.text("false")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        schema="app",
    )
    for table, owner_col, owner_fk in (
        ("conference_topics", "conference_id", "app.conferences.id"),
        ("sme_topics", "sme_id", "app.smes.id"),
        ("talk_topics", "talk_id", "app.talks.id"),
    ):
        op.create_table(
            table,
            sa.Column(owner_col, UUID(as_uuid=True), sa.ForeignKey(owner_fk, ondelete="CASCADE"), primary_key=True),
            sa.Column("topic_id", UUID(as_uuid=True), sa.ForeignKey("app.topics.id", ondelete="CASCADE"), primary_key=True),
            sa.Column("weight", sa.Float, nullable=False, server_default=sa.text("1.0")),
            schema="app",
        )
