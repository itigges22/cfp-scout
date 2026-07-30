"""Trip logistics move out of the browser and into the database.

The brief exposed a "logistics_placeholder" containing a localStorage
key and four field names — travel, lodging, swag_booth,
sponsorship_status. The backend computed the key; the values were typed
into a contenteditable div and never left the browser that typed them.

So four facts the team most needs to share — is the flight booked, is
the hotel sorted, are we sponsoring — were visible to exactly one person,
on one machine, until a cache clear removed them. For a tool whose stated
purpose is "full tracking of all of it", that is the wrong storage.

Free text rather than structured fields. "Flights booked, Anna has the
confirmation" is the real shape of this information, and a structured
travel model would be a guess at a workflow nobody described.

Non-null with an empty default so every conference has the slots and no
read path needs a None check.

Revision ID: 20260727_2600
Revises: 20260727_2500
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260727_2600"
down_revision = "20260727_2500"
branch_labels = None
depends_on = None

_COLUMNS = (
    "logistics_travel",
    "logistics_lodging",
    "logistics_booth",
    "logistics_sponsorship",
)


def upgrade() -> None:
    for name in _COLUMNS:
        op.add_column(
            "conferences",
            sa.Column(name, sa.Text(), nullable=False, server_default=sa.text("''")),
            schema="app",
        )


def downgrade() -> None:
    for name in _COLUMNS:
        op.drop_column("conferences", name, schema="app")
