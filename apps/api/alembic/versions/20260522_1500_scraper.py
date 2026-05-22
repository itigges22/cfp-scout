"""scraper tweaks: timestamp precision on sources/raw_pages

Plan 14 introduces a 15-minute scrape cron, which means
``sources.last_crawled_at`` and ``raw_pages.fetched_at`` need sub-day
precision. Both were originally declared as ``Date`` columns in the baseline
migration — we convert to ``TIMESTAMPTZ`` here. Existing values are preserved
(date midnight UTC).

Revision ID: 20260522_1500_scraper
Revises: 20260522_1300_jobs
Create Date: 2026-05-22 15:00:00
"""

from __future__ import annotations

from typing import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260522_1500_scraper"
down_revision: str | None = "20260522_1300_jobs"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # sources.last_crawled_at: DATE -> TIMESTAMPTZ
    # USING coerces existing date values to midnight UTC.
    op.execute(
        """
        ALTER TABLE app.sources
            ALTER COLUMN last_crawled_at TYPE timestamptz
            USING last_crawled_at::timestamptz;
        """
    )

    # raw_pages.fetched_at: DATE NOT NULL -> TIMESTAMPTZ NOT NULL
    op.execute(
        """
        ALTER TABLE app.raw_pages
            ALTER COLUMN fetched_at TYPE timestamptz
            USING fetched_at::timestamptz;
        """
    )


def downgrade() -> None:
    op.execute(
        """
        ALTER TABLE app.sources
            ALTER COLUMN last_crawled_at TYPE date
            USING last_crawled_at::date;
        """
    )
    op.execute(
        """
        ALTER TABLE app.raw_pages
            ALTER COLUMN fetched_at TYPE date
            USING fetched_at::date;
        """
    )
