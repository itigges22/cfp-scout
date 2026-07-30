"""Drop talk_tags and talk_tag_assignments — labels nothing could attach.

``talk_tags`` had four endpoints, a service section, Pydantic schemas and
a typed frontend client. ``talk_tag_assignments`` — the junction that
would connect a tag to a talk — was never written by anything: zero
constructor calls anywhere under app/, verified by
tests/unit/test_no_tables_read_but_never_written.py.

So an operator could create a tag, name it, colour it, and then never put
it on a talk. ``GET /talks?tag_id=X`` always returned empty, and
``TalkRead.tags`` was always ``[]``.

Nothing failed. The feature simply did half of what it looked like it
did, which is the failure mode that guard test exists to catch.

Tag data is not migrated anywhere. There is nothing to migrate: the
assignment table is empty by construction, so any tag rows describe
labels that were never applied to anything.

Revision ID: 20260727_2400
Revises: 20260727_2300
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision = "20260727_2400"
down_revision = "20260727_2300"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_table("talk_tag_assignments", schema="app")
    op.drop_table("talk_tags", schema="app")


def downgrade() -> None:
    op.create_table(
        "talk_tags",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("name", sa.String(length=60), nullable=False, unique=True),
        sa.Column("color", sa.String(length=20), nullable=False, server_default=sa.text("''")),
        schema="app",
    )
    op.create_table(
        "talk_tag_assignments",
        sa.Column(
            "talk_id",
            UUID(as_uuid=True),
            sa.ForeignKey("app.talks.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "tag_id",
            UUID(as_uuid=True),
            sa.ForeignKey("app.talk_tags.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        schema="app",
    )
    op.create_index(
        "ix_talk_tag_assignments_tag_id", "talk_tag_assignments", ["tag_id"], schema="app"
    )
