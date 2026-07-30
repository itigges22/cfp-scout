"""event_kind: align the CHECK constraints with the canonical value set.

Replaces the stale CHECK on app.conferences (which allowed the pre-v2
values corporate/developer_day/team_managed/meetup/research) with one over
the current set, and adds the equivalent constraint to
app.past_conferences, which had none.

Both tables are normalised first — legacy team_managed/meetup rows become
grassroot, anything else out of set becomes corporate — so the migration
cannot fail on pre-existing data.

The canonical set lives in app/schemas/common.py::EVENT_KINDS. This file
holds a frozen copy, as migrations must.

Note: db/base.py's naming convention is ck_%(table_name)s_%(constraint_name)s,
so a constraint already named "conferences_event_kind_check" landed in
Postgres as ck_conferences_conferences_event_kind_check. The drop below
uses the real name.
"""

from alembic import op

revision = "20260725_1000"
down_revision = "20260705_1000_embed_v2moe"
branch_labels = None
depends_on = None

_SCHEMA = "app"

# Frozen copy of app/schemas/common.py::EVENT_KINDS as of this revision.
# 'grassroot' carries behaviour (auto-approved on create, excluded from the
# matcher), so adding a kind is a code + migration change, not a setting.
_KINDS = ("corporate", "grassroot", "developer_day", "research", "hackathon")

_OLD_CONFERENCES_CHECK = "ck_conferences_conferences_event_kind_check"


def _kinds_sql() -> str:
    return ", ".join(f"'{k}'" for k in _KINDS)


def upgrade() -> None:
    kinds = _kinds_sql()

    # --- app.conferences ---------------------------------------------------
    # Drop by the real (convention-mangled) name. IF EXISTS so a database
    # that never received 20260603_0900's constraint still upgrades.
    op.execute(
        f"ALTER TABLE {_SCHEMA}.conferences "
        f"DROP CONSTRAINT IF EXISTS {_OLD_CONFERENCES_CHECK}"
    )
    # Fold any legacy value into the canonical set before constraining.
    op.execute(
        f"UPDATE {_SCHEMA}.conferences SET event_kind = 'grassroot' "
        f"WHERE event_kind IN ('team_managed', 'meetup')"
    )
    op.execute(
        f"UPDATE {_SCHEMA}.conferences SET event_kind = 'corporate' "
        f"WHERE event_kind IS NULL OR event_kind NOT IN ({kinds})"
    )
    op.create_check_constraint(
        "event_kind_allowed",
        "conferences",
        f"event_kind IN ({kinds})",
        schema=_SCHEMA,
    )

    # --- app.past_conferences ---------------------------------------------
    op.execute(
        f"UPDATE {_SCHEMA}.past_conferences SET event_kind = 'grassroot' "
        f"WHERE event_kind IN ('team_managed', 'meetup')"
    )
    op.execute(
        f"UPDATE {_SCHEMA}.past_conferences SET event_kind = 'corporate' "
        f"WHERE event_kind IS NULL OR event_kind NOT IN ({kinds})"
    )
    op.create_check_constraint(
        "event_kind_allowed",
        "past_conferences",
        f"event_kind IN ({kinds})",
        schema=_SCHEMA,
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_past_conferences_event_kind_allowed",
        "past_conferences",
        schema=_SCHEMA,
        type_="check",
    )
    op.drop_constraint(
        "ck_conferences_event_kind_allowed",
        "conferences",
        schema=_SCHEMA,
        type_="check",
    )
    # Deliberately NOT restoring the old constraint: it forbade
    # 'grassroot', which the data has legitimately contained since
    # 20260604_1100. Recreating it would make the downgrade fail.
