"""Event kinds become an operator setting; drop the CHECK that froze them.

``event_kind`` was a Python tuple in app/schemas/common.py with a database
CHECK behind it, so a team whose event vocabulary differed from ours could
not change it without a code change and a migration. That is the same
mistake the discovery keyword list had: a decision about the operator's
world, hardcoded.

A DDL constraint cannot enforce a list the operator edits at runtime — the
constraint is frozen when the migration runs, and the setting is not. The
alternative, regenerating the constraint whenever someone saves the
settings page, would mean a settings edit runs DDL against a live table.
A bad string in a column is a much better failure than that.

So validation moves up one layer: ``ConferenceCreate`` and
``ConferenceUpdate`` check ``settings.event_kinds``, and the extractor is
told the current list rather than a compiled-in one.

WHAT THIS GIVES UP
    The database will now accept any string in ``event_kind``. Nothing in
    the application writes one that has not been validated, but a direct
    SQL write could. That is the cost of letting the vocabulary be edited,
    and it is worth it.

WHAT IT DELIBERATELY DOES NOT DO
    Rewrite existing rows. Removing a kind from the setting leaves
    conferences that already carry it untouched — deleting a word from a
    list should not silently edit history. Those rows stay readable and
    keep working; only new writes are constrained.

Revision ID: 20260727_2200
Revises: 20260727_2000
"""

from __future__ import annotations

from alembic import op

revision = "20260727_2200"
down_revision = "20260727_2000"
branch_labels = None
depends_on = None

# BARE name, without the ck_conferences_ prefix. alembic/env.py sets a
# naming convention, and both drop_constraint(type_="check") and
# create_check_constraint APPLY it — passing the already-prefixed name
# yields ck_conferences_ck_conferences_event_kind_allowed and fails with
# "constraint ... does not exist".
_CONSTRAINT = "event_kind_allowed"
_FROZEN_KINDS = "'corporate', 'grassroot', 'developer_day', 'research', 'hackathon'"


def upgrade() -> None:
    op.drop_constraint(_CONSTRAINT, "conferences", type_="check", schema="app")


def downgrade() -> None:
    # Restores the vocabulary as it stood when this migration was written,
    # which is what a migration must do — it cannot consult a setting that
    # may have changed since. If rows have picked up kinds outside this
    # list in the meantime, this will fail, and that failure is correct:
    # it is telling you the data no longer fits the older schema.
    op.create_check_constraint(
        _CONSTRAINT,
        "conferences",
        f"event_kind IN ({_FROZEN_KINDS})",
        schema="app",
    )
