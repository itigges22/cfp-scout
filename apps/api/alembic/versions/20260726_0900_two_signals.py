"""Two ranking signals instead of three stage scores.

``messaging_score`` and ``pillar_score`` measured the same thing — they
correlate at r=0.86 on the labelled corpus, one question asked twice — so
they collapse into ``fit_score``. ``sme_score`` becomes ``speaker_score``,
which is what it always meant: can we show up well.

The old scores are NOT carried across, and the columns land NULL-equivalent
(0.0) on existing rows.

An earlier version of this migration did carry them —
``fit_score = max(messaging_score, pillar_score)``, ``speaker_score =
sme_score`` — with a comment saying it kept the conference list from going
blank. That was wrong, and instructively so: every read path joins matches on
``algorithm_version == ALGORITHM_VERSION``, and this migration does not
change the version stamp on existing rows. So the carried values sat in
columns that no query could ever reach. The list went blank anyway, and the
carry bought a false sense that it had not.

Stamping the rows with the new version instead would be worse: it would
claim an approximation was computed by the new formula.

The real fix is elsewhere — ``rescore_stale_matches`` (app/tasks/run_fit_match.py,
scheduled hourly in app/scheduler.py) rescores exactly the conferences that have
no match at the current version, so a version bump heals itself within the
hour instead of waiting for someone to notice and click recompute-all.

Revision ID: 20260726_0900
Revises: 20260725_1200
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260726_0900"
down_revision = "20260725_1200"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "matches",
        sa.Column("fit_score", sa.Float(), nullable=False, server_default=sa.text("0")),
        schema="app",
    )
    op.add_column(
        "matches",
        sa.Column(
            "speaker_score", sa.Float(), nullable=False, server_default=sa.text("0")
        ),
        schema="app",
    )
    # No carry. See the module docstring: existing rows keep their old
    # algorithm_version, so nothing can read whatever we put here.
    # rescore_stale_matches repopulates them properly within the hour.
    #
    # The server defaults existed only to make the columns NOT NULL on a
    # populated table. A match row must carry real scores.
    op.alter_column("matches", "fit_score", server_default=None, schema="app")
    op.alter_column("matches", "speaker_score", server_default=None, schema="app")

    op.drop_column("matches", "messaging_score", schema="app")
    op.drop_column("matches", "pillar_score", schema="app")
    op.drop_column("matches", "sme_score", schema="app")


def downgrade() -> None:
    for name in ("messaging_score", "pillar_score", "sme_score"):
        op.add_column(
            "matches",
            sa.Column(name, sa.Float(), nullable=False, server_default=sa.text("0")),
            schema="app",
        )
    # fit_score cannot be split back into its two halves; both get the same
    # value, which is the honest reconstruction.
    op.execute(
        "UPDATE app.matches SET "
        "messaging_score = fit_score, pillar_score = fit_score, "
        "sme_score = speaker_score"
    )
    for name in ("messaging_score", "pillar_score", "sme_score"):
        op.alter_column("matches", name, server_default=None, schema="app")

    op.drop_column("matches", "speaker_score", schema="app")
    op.drop_column("matches", "fit_score", schema="app")
