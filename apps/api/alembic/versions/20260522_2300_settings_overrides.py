"""Runtime settings overrides table (P3 UX work).

A singleton-style key/value table that lets admins tune knobs from the UI
without editing ``.env`` and restarting. Loaded at api startup; mutated by
``PATCH /api/v1/admin/settings``.

Schema design choices:
  * Primary key on ``name`` — one row per setting, upsert on update.
  * ``value`` is TEXT holding the JSON-encoded value so we can survive
    type changes without a column-shape migration.
  * ``actor_label`` is captured so the audit log can attribute each tweak.

Revision ID: 20260522_2300_settings
Revises: 20260522_2100_seed_series
Create Date: 2026-05-22 23:30:00
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260522_2300_settings"
down_revision: str | None = "20260522_2100_seed_series"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "app_setting_overrides",
        sa.Column("name", sa.String(80), primary_key=True),
        sa.Column("value", sa.Text(), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "actor_label",
            sa.String(120),
            nullable=False,
            server_default=sa.text("'system'"),
        ),
        schema="app",
    )


def downgrade() -> None:
    op.drop_table("app_setting_overrides", schema="app")
