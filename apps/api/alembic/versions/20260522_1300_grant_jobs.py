"""grant CREATE on jobs schema to app role

Plan 13 (APScheduler) needs the runtime ``app`` role to be able to create the
``jobs.apscheduler_jobs`` table at startup. New installs get this grant via
``infra/postgres/init/02-roles-and-schemas.sql``; this migration brings
existing databases up to the same state idempotently.

GRANT is non-destructive: running it twice is a no-op.

Revision ID: 20260522_1300_jobs
Revises: 20260521_1210_seed
Create Date: 2026-05-22 13:00:00
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "20260522_1300_jobs"
down_revision: str | None = "20260521_1210_seed"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("GRANT CREATE ON SCHEMA jobs TO app;")


def downgrade() -> None:
    op.execute("REVOKE CREATE ON SCHEMA jobs FROM app;")
