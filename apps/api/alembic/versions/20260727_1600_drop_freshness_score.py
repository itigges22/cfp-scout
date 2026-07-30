"""Drop conferences.freshness_score and the nightly job that maintained it.

A daily 03:00 cron recomputed this column for every conference — an
exponential half-life curve over ``updated_at``. Its full consumer list:

  * one number printed on the brief (services/brief/builder.py)
  * one histogram on the diagnostics page

Nothing ranked, sorted, filtered, or decided on it. The task's own
docstring claimed "events nobody has touched recently drift down the
dashboard", which was never true — no query ordered by it.

It is also the wrong measurement. ``updated_at`` records when someone last
edited a row, so the score answered "how recently did we do bookkeeping on
this", not "does this event still matter". A conference nobody had
corrected looked stale; one that got a typo fixed looked fresh.

Chunk-level decay is a different thing and stays: it uses each chunk's own
``last_used_at``/``created_at`` and genuinely tilts ranking. Those pure
functions moved to services/matcher/_scoring.py, beside their only caller,
which also removed the import cycle the old package needed a lazy import
to avoid.

With the archive step already removed (20260727_1400), dropping this
leaves the decay pass with nothing to do, so the job, the cron, its manual
trigger and the whole services/lifecycle package go with it.

Revision ID: 20260727_1600
Revises: 20260727_1400
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260727_1600"
down_revision = "20260727_1400"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_column("conferences", "freshness_score", schema="app")


def downgrade() -> None:
    op.add_column(
        "conferences",
        sa.Column(
            "freshness_score",
            sa.Float(),
            nullable=False,
            server_default=sa.text("1.0"),
        ),
        schema="app",
    )
