"""event_kind: normalize to 5 canonical values.

Old values: corporate, developer_day, team_managed, meetup, research
New values: corporate, grassroot, developer_day, research, hackathon

- team_managed → grassroot  (owned events, auto-approved)
- meetup       → grassroot  (community meetups we run)
- everything else unchanged

Revision ID: 20260604_1100
Revises: 20260604_1000
"""

from alembic import op

revision = "20260604_1100"
down_revision = "20260604_1000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        UPDATE app.conferences
        SET event_kind = 'grassroot'
        WHERE event_kind IN ('team_managed', 'meetup')
    """)
    op.execute("""
        UPDATE app.past_conferences
        SET event_kind = 'grassroot'
        WHERE event_kind IN ('team_managed', 'meetup')
    """)


def downgrade() -> None:
    # Best-effort: map grassroot back to meetup (can't distinguish original)
    op.execute("""
        UPDATE app.conferences SET event_kind = 'meetup' WHERE event_kind = 'grassroot'
    """)
    op.execute("""
        UPDATE app.past_conferences SET event_kind = 'meetup' WHERE event_kind = 'grassroot'
    """)
