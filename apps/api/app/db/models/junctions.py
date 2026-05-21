"""Junction tables — the edges of Scout's knowledge graph.

NetworkX (plan 16) loads these in memory and computes traversals. Each
junction has a composite PK on the two FK columns plus a ``weight`` or
``score`` column the matcher consumes.

No TimestampedMixin: the parent entities carry timestamps; junctions are
join records, treated as ephemeral relationships.
"""

from __future__ import annotations

import uuid

from sqlalchemy import ForeignKey
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class ConferenceTopic(Base):
    __tablename__ = "conference_topics"
    __table_args__ = {"schema": "app"}

    conference_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("app.conferences.id", ondelete="CASCADE"),
        primary_key=True,
    )
    topic_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("app.topics.id", ondelete="CASCADE"),
        primary_key=True,
    )
    weight: Mapped[float] = mapped_column(default=1.0, nullable=False)


class ConferenceAudience(Base):
    __tablename__ = "conference_audiences"
    __table_args__ = {"schema": "app"}

    conference_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("app.conferences.id", ondelete="CASCADE"),
        primary_key=True,
    )
    audience_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("app.audience_profiles.id", ondelete="CASCADE"),
        primary_key=True,
    )
    weight: Mapped[float] = mapped_column(default=1.0, nullable=False)


class ConferencePillar(Base):
    """Matcher-computed alignment between a conference and a strategic pillar."""

    __tablename__ = "conference_pillars"
    __table_args__ = {"schema": "app"}

    conference_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("app.conferences.id", ondelete="CASCADE"),
        primary_key=True,
    )
    pillar_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("app.strategic_pillars.id", ondelete="CASCADE"),
        primary_key=True,
    )
    score: Mapped[float] = mapped_column(default=0.0, nullable=False)


class ConferenceSme(Base):
    """Matcher-computed recommendation. Populated by plan 17 + 18."""

    __tablename__ = "conference_smes"
    __table_args__ = {"schema": "app"}

    conference_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("app.conferences.id", ondelete="CASCADE"),
        primary_key=True,
    )
    sme_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("app.smes.id", ondelete="CASCADE"),
        primary_key=True,
    )
    score: Mapped[float] = mapped_column(default=0.0, nullable=False)


class SmeTopic(Base):
    __tablename__ = "sme_topics"
    __table_args__ = {"schema": "app"}

    sme_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("app.smes.id", ondelete="CASCADE"),
        primary_key=True,
    )
    topic_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("app.topics.id", ondelete="CASCADE"),
        primary_key=True,
    )
    weight: Mapped[float] = mapped_column(default=1.0, nullable=False)


class SmeAudience(Base):
    __tablename__ = "sme_audiences"
    __table_args__ = {"schema": "app"}

    sme_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("app.smes.id", ondelete="CASCADE"),
        primary_key=True,
    )
    audience_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("app.audience_profiles.id", ondelete="CASCADE"),
        primary_key=True,
    )
    weight: Mapped[float] = mapped_column(default=1.0, nullable=False)


class MessagingPillar(Base):
    """Which messaging documents support which strategic pillars."""

    __tablename__ = "messaging_pillars"
    __table_args__ = {"schema": "app"}

    messaging_document_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("app.messaging_documents.id", ondelete="CASCADE"),
        primary_key=True,
    )
    pillar_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("app.strategic_pillars.id", ondelete="CASCADE"),
        primary_key=True,
    )
    weight: Mapped[float] = mapped_column(default=1.0, nullable=False)
