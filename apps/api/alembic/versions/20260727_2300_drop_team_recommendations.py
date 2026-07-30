"""Drop match_team_recommendations and the optimiser behind it.

``services/matcher/teams.py`` enumerated every combination of the top-K
SMEs at sizes 1, 2 and 3 and scored each on a four-term objective:

    team_w_individual * avg_fit
  + team_w_coverage   * topic_coverage
  - team_w_redundancy * mean_pairwise_jaccard(topics)
  - team_w_location   * fraction_of_pairs_sharing_a_city

Two of those terms measure nothing the team asked about. The data model
says track WHO IS GOING — a fact a person records after deciding — and
this computed an optimal answer to a question nobody posed, persisted it,
generated a paragraph explaining it, and re-ran on every match.

Its consumers were both display: the SME panel and the printable brief.
Nothing scored, filtered or decided on a team recommendation.

It existed partly because there was nowhere to record actual attendance.
Migration 20260727_1800 fixed that — participation rows now carry the
person, their activity (talk / booth / attend / sponsor) and their travel
dates — so the brief's "attendees" section reads real participation
instead of an optimiser's guess. That is a strictly better answer to the
same question: it says who IS going rather than who a scoring function
thinks SHOULD go.

Removed with it: services/matcher/teams.py, tasks/recommend_teams.py, two
admin endpoints, GET /conferences/{id}/team-recommendations, the
five team_* settings and their settings_spec entries, and the enqueue in
the matcher pipeline.

Note the dropped table carried a CHECK whose name Postgres had truncated
to 63 characters — ck_match_team_recommendations_ck_match_team_recommendat_0fa3.
It goes with the table.

Revision ID: 20260727_2300
Revises: 20260727_2200
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import ARRAY, UUID

revision = "20260727_2300"
down_revision = "20260727_2200"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_table("match_team_recommendations", schema="app")


def downgrade() -> None:
    # Structure only. The rows were derived output — re-running the
    # optimiser would regenerate them, and the optimiser is gone, so
    # there is nothing to restore them from.
    op.create_table(
        "match_team_recommendations",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "match_id",
            UUID(as_uuid=True),
            sa.ForeignKey("app.matches.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("team_size", sa.SmallInteger(), nullable=False),
        sa.Column("sme_ids", ARRAY(UUID(as_uuid=True)), nullable=False),
        sa.Column("team_score", sa.Float(), nullable=False),
        sa.Column("coverage_breadth", sa.Float(), nullable=False),
        sa.Column("redundancy", sa.Float(), nullable=False),
        sa.Column("rationale_text", sa.Text(), nullable=False, server_default=sa.text("''")),
        schema="app",
    )
