"""The missing middle of the lifecycle: planning to attend.

The data model runs discovered -> planning to attend -> attended. Only
the two ends existed.

``approved`` was fully wired, and attendance was inferred from
participation rows existing. Between them there was nothing — no way to
say "we intend to send Alice to KubeCon, arriving Tuesday, working the
booth". That is where a conference sits for most of its life, and it is
where "track when and who is going" lives.

WHAT THIS ADDS

  participation.arrives_on / departs_on
      When each person travels, which is not the conference's own dates:
      people arrive late, leave early, or cover one day of three. Their
      presence is what makes a participation row a PLAN rather than a
      record of something finished.

  participation.attended_at
      Set when someone confirms the person actually went.

  conferences.leads_generated
      The last of the four things an attended conference is supposed to
      carry, and the only one with no representation anywhere — no
      column, no schema field, no endpoint. Without it the feedback loop
      into matching carried a three-value verdict and nothing else.

WHAT THIS DELIBERATELY DOES NOT ADD

  A status value. "Planning" and "attended" are NOT written to
  ``conferences.status``. Attendance is answered by
  ``attended_at IS NOT NULL OR departs_on < today`` — an explicit
  confirmation, or the dates having passed, which are the two routes the
  operator described. Both are queries.

  Status is already overloaded: it carries extraction state, gate
  outcomes, the judge's veto AND the operator's approve/reject decision.
  A nightly job writing one more meaning into it is exactly how the decay
  pass came to overwrite recorded decisions (20260727_1400). Deriving
  costs one predicate and cannot be silently clobbered by a cron.

All columns nullable. Nothing backfills, nothing is required, and the
post-event fields stay answerable weeks later — the operator asked for
them to be deferrable.

Revision ID: 20260727_1800
Revises: 20260727_1600
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260727_1800"
down_revision = "20260727_1600"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "participation",
        sa.Column("arrives_on", sa.Date(), nullable=True),
        schema="app",
    )
    op.add_column(
        "participation",
        sa.Column("departs_on", sa.Date(), nullable=True),
        schema="app",
    )
    op.add_column(
        "participation",
        sa.Column("attended_at", sa.DateTime(timezone=True), nullable=True),
        schema="app",
    )
    op.add_column(
        "conferences",
        sa.Column("leads_generated", sa.Integer(), nullable=True),
        schema="app",
    )
    # Finding "who is going, and when" is a listing query the UI runs on
    # every planning view, so it gets an index. departs_on is the one the
    # attended-vs-planned predicate tests.
    op.create_index(
        "ix_participation_departs_on",
        "participation",
        ["departs_on"],
        schema="app",
    )


def downgrade() -> None:
    op.drop_index("ix_participation_departs_on", table_name="participation", schema="app")
    op.drop_column("conferences", "leads_generated", schema="app")
    op.drop_column("participation", "attended_at", schema="app")
    op.drop_column("participation", "departs_on", schema="app")
    op.drop_column("participation", "arrives_on", schema="app")
