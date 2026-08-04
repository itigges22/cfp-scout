"""SMEs describe their expertise in their own words.

THE PROBLEM
    "Primary topics" asked an SME to tag themselves against the extracted
    topic vocabulary — 130+ machine-generated entries at the time of this
    migration, growing with every discovery run. Nobody browses a list
    that size to describe their own job, so the field was skipped, and the
    matcher's topic dimension scored those SMEs a hard 0 at weight 0.30.

WHAT CHANGES
    ``smes.expertise`` — free text, the person's own description of what
    they work on. It is appended to the bio when the SME is embedded, so
    the ranker's bio-similarity dimension (embedding cosine, weight 0.30)
    reads it directly. Vocabulary tagging becomes optional machinery
    rather than a form field; the topic dimension is now dropped and
    renormalised when either side has no tags, matching the audience
    dimension's existing missing-measurement rule.

    Text, not a new junction: the point is that natural language carries
    more signal through embeddings than a Jaccard over hand-picked IDs
    ever did. "Makes a model give better answers by letting it think
    longer at answer time" matches an inference-scaling conference by
    meaning; no vocabulary entry would.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260729_1000"
down_revision = "20260727_2700"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "smes",
        sa.Column("expertise", sa.Text(), nullable=False, server_default=""),
        schema="app",
    )


def downgrade() -> None:
    op.drop_column("smes", "expertise", schema="app")
