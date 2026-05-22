"""Match output tables: matches, decisions, team recommendations.

The matcher pipeline (plan 17) writes a ``matches`` row per conference per
run. ``algorithm_version`` lets us recompute selectively.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    SmallInteger,
    String,
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.models._mixins import TimestampedMixin, uuid_pk


class Match(TimestampedMixin, Base):
    """Matcher output. One row per conference per algorithm_version."""

    __tablename__ = "matches"
    __table_args__ = {"schema": "app"}

    id: Mapped[uuid.UUID] = uuid_pk()

    conference_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("app.conferences.id", ondelete="CASCADE"),
        nullable=False,
    )

    messaging_score: Mapped[float] = mapped_column(nullable=False)
    pillar_score: Mapped[float] = mapped_column(nullable=False)
    sme_score: Mapped[float] = mapped_column(nullable=False)
    overall_score: Mapped[float] = mapped_column(nullable=False)

    recommended_sme_ids: Mapped[list[uuid.UUID]] = mapped_column(
        ARRAY(UUID(as_uuid=True)), nullable=False, server_default=text("ARRAY[]::uuid[]")
    )
    rationale_text: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("''"))

    # Keyed by sme_id (string-uuid -> narrative). Populated by plan 19.
    sme_fit_narratives: Mapped[dict] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )

    algorithm_version: Mapped[str] = mapped_column(String(40), nullable=False)
    computed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class MatchTeamRecommendation(Base):
    """Algorithmically-chosen complementary teams of size 1/2/3 (plan 32).

    Composite PK on (match_id, team_size). No TimestampedMixin: parent
    ``matches`` row owns the timeline.
    """

    __tablename__ = "match_team_recommendations"
    __table_args__ = (
        CheckConstraint("team_size IN (1, 2, 3)", name="team_size_range"),
        {"schema": "app"},
    )

    match_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("app.matches.id", ondelete="CASCADE"),
        primary_key=True,
    )
    team_size: Mapped[int] = mapped_column(SmallInteger, primary_key=True)

    sme_ids: Mapped[list[uuid.UUID]] = mapped_column(ARRAY(UUID(as_uuid=True)), nullable=False)
    team_score: Mapped[float] = mapped_column(nullable=False)
    coverage_breadth: Mapped[float] = mapped_column(nullable=False)
    redundancy: Mapped[float] = mapped_column(nullable=False)

    rationale_text: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("''"))
    computed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )


class Decision(TimestampedMixin, Base):
    """Human approve/reject/needs-review actions."""

    __tablename__ = "decisions"
    __table_args__ = {"schema": "app"}

    id: Mapped[uuid.UUID] = uuid_pk()

    conference_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("app.conferences.id", ondelete="CASCADE"),
        nullable=False,
    )
    decided_by_label: Mapped[str] = mapped_column(
        String(120), nullable=False, server_default=text("''")
    )
    decision: Mapped[str] = mapped_column(String(20), nullable=False)
    reason: Mapped[str | None] = mapped_column(Text)
    decided_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
