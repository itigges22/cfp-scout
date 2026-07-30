"""A home for operational state that is not a setting.

``app_setting_overrides`` had started collecting values that are not
settings. The diagnostics page stored a "when did someone last clear the
LLM error list" timestamp there — operational state, not something anyone
configures, not a field on ``Settings``, and never shown on the settings
page.

That table feeds ``get_settings()``, and every row in it should
correspond to something an operator can see and change. Without a
separate home, the settings table is the path of least resistance for
every stray value, and a typo'd real key would sit there looking
configured while changing nothing.

``upsert()`` in services/settings_overrides.py now rejects any name not
registered in settings_spec.SPECS, so this table is where the diagnostics
watermark moves.

Revision ID: 20260727_2500
Revises: 20260727_2400
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260727_2500"
down_revision = "20260727_2400"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "ops_state",
        sa.Column("key", sa.String(length=80), primary_key=True),
        sa.Column("value", sa.Text(), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        schema="app",
    )
    # Carry the one existing value across so "cleared" does not silently
    # un-clear on deploy.
    op.execute(
        """
        INSERT INTO app.ops_state (key, value)
        SELECT name, value FROM app.app_setting_overrides
        WHERE name = 'diagnostics_llm_errors_cleared_at'
        ON CONFLICT (key) DO NOTHING
        """
    )
    op.execute(
        "DELETE FROM app.app_setting_overrides "
        "WHERE name = 'diagnostics_llm_errors_cleared_at'"
    )


def downgrade() -> None:
    op.execute(
        """
        INSERT INTO app.app_setting_overrides (name, value, actor_label)
        SELECT key, value, 'migration' FROM app.ops_state
        WHERE key = 'diagnostics_llm_errors_cleared_at'
        ON CONFLICT (name) DO NOTHING
        """
    )
    op.drop_table("ops_state", schema="app")
