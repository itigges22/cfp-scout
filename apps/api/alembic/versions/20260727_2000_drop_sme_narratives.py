"""Drop matches.sme_fit_narratives and the machinery that filled it.

A background job made one LLM call per (conference, top-K SME) pair and
stored a 2-3 sentence paragraph explaining why that person suited that
event. Its full consumer list was two display sites: the SME panel on the
conference detail page, and the printable brief. No scoring path, filter,
gate or decision ever read it.

The cost scaled as conferences x SMEs on every match run, and discovery
now ingests far more conferences than it used to (W1), so this was the
line item most likely to grow without anyone deciding it should.

About sixty of the module's lines were anti-fabrication machinery —
post-validation, an inputs fingerprint, a quoted-text regex, and a
retry-once-then-give-up path — which existed because the model invented
quotes and attributed them to named colleagues. That is a lot of guarding
for a feature nothing depended on, and the failure mode it guarded
against (putting words in a real coworker's mouth) is worse than the
feature was valuable.

The mechanical per-dimension scores the SME ranker already produces
(topic / audience / bio / location / past attendance) say the same thing
without an LLM, without a cost that scales, and without the possibility
of being wrong about a person.

Removed with it: services/matcher/sme_narrative.py,
tasks/compute_sme_fit_narrative.py, three admin endpoints, the diagnostics
retry path, the settings_spec entry, the dry-run canned response, and the
enqueue in the matcher pipeline.

Revision ID: 20260727_2000
Revises: 20260727_1800
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "20260727_2000"
down_revision = "20260727_1800"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_column("matches", "sme_fit_narratives", schema="app")


def downgrade() -> None:
    op.add_column(
        "matches",
        sa.Column(
            "sme_fit_narratives",
            JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        schema="app",
    )
