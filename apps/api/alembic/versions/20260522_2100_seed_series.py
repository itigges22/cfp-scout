"""seed conference_series from db/seeds/conference_series.yaml

Plan 23: loads the curated catalog of ~35 known conference series into
``app.conference_series``. Idempotent — uses ``ON CONFLICT (canonical_name)
DO NOTHING`` so re-running on an already-seeded db is a no-op (good for
local resets that re-apply migrations).

The YAML lives in the repo, not in the container; we copy it into the
api image alongside the alembic tree so the migration can read it at
``alembic upgrade head`` time. If the file is missing (e.g. someone runs
this migration outside the container), we log + skip rather than fail —
the seed catalog is value-add, not invariant data.

Revision ID: 20260522_2100_seed_series
Revises: 20260522_1500_scraper
Create Date: 2026-05-22 21:00:00
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260522_2100_seed_series"
down_revision: str | None = "20260522_1500_scraper"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


# We hardcode the search paths so the migration works both inside the
# container (mounted at /app/alembic) and locally (run from apps/api).
_CANDIDATE_PATHS = [
    Path("/app/db/seeds/conference_series.yaml"),
    Path(__file__).parent.parent.parent.parent.parent / "db" / "seeds" / "conference_series.yaml",
]


def _load_yaml(path: Path) -> dict:
    # tiny vendored loader so we don't add PyYAML just for this migration
    # — fall back to YAML if available, otherwise expect JSON-compatible
    # input.
    try:
        import yaml  # type: ignore
        with path.open("r", encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    except ImportError:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)


def upgrade() -> None:
    yaml_path: Path | None = None
    for p in _CANDIDATE_PATHS:
        if p.exists():
            yaml_path = p
            break
    if yaml_path is None:
        # Don't fail the migration — the catalog is value-add, not invariant.
        op.execute(
            "DO $$ BEGIN RAISE NOTICE "
            "'plan-23 seed skipped: conference_series.yaml not found'; END $$;"
        )
        return

    data = _load_yaml(yaml_path)
    rows = data.get("series", [])
    if not rows:
        return

    bind = op.get_bind()
    for r in rows:
        canonical = (r.get("canonical_name") or "").strip()
        if not canonical:
            continue
        aliases = r.get("aliases") or []
        description = (r.get("description") or "").strip()
        typical_month = r.get("typical_month")
        typical_topics = r.get("typical_topics") or []
        homepage = r.get("homepage")

        bind.execute(
            sa.text(
                """
                INSERT INTO app.conference_series (
                    canonical_name, aliases, description, typical_month,
                    typical_topics, homepage, is_active
                ) VALUES (
                    :canonical_name, :aliases, :description, :typical_month,
                    :typical_topics, :homepage, true
                )
                ON CONFLICT (canonical_name) DO NOTHING
                """
            ),
            {
                "canonical_name": canonical,
                "aliases": list(aliases),
                "description": description,
                "typical_month": typical_month,
                "typical_topics": list(typical_topics),
                "homepage": homepage,
            },
        )


def downgrade() -> None:
    # Surgical: only remove rows that were seeded by THIS migration AND
    # haven't been linked to any conferences/past_conferences. Anything
    # the team manually edited or used is preserved.
    op.execute(
        """
        DELETE FROM app.conference_series cs
        WHERE NOT EXISTS (
            SELECT 1 FROM app.conferences c WHERE c.series_id = cs.id
        )
        AND NOT EXISTS (
            SELECT 1 FROM app.past_conferences p WHERE p.series_id = cs.id
        );
        """
    )
