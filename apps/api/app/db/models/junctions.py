"""Junction tables — the edges of Scout's knowledge graph.

NetworkX (plan 16) loads these in memory and computes traversals. Each
junction has a composite PK on the two FK columns plus a ``weight`` or
``score`` column the matcher consumes.

No TimestampedMixin: the parent entities carry timestamps; junctions are
join records, treated as ephemeral relationships.
"""

from __future__ import annotations

import uuid

from sqlalchemy import Boolean, ForeignKey
from sqlalchemy.dialects.postgresql import ARRAY, UUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy import Numeric

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


class SmePillar(Base):
    """Junction: SME ↔ pillar (many-to-many). Migration C."""

    __tablename__ = "sme_pillars"
    __table_args__ = {"schema": "app"}

    sme_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("app.smes.id", ondelete="CASCADE"),
        primary_key=True,
    )
    pillar_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("app.strategic_pillars.id", ondelete="CASCADE"),
        primary_key=True,
    )
    is_primary: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)


class TalkTagAssignment(Base):
    """Junction: talk ↔ tag. Migration E."""

    __tablename__ = "talk_tag_assignments"
    __table_args__ = {"schema": "app"}

    talk_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("app.talks.id", ondelete="CASCADE"),
        primary_key=True,
    )
    tag_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("app.talk_tags.id", ondelete="CASCADE"),
        primary_key=True,
    )


class TalkTopic(Base):
    """Junction: talk ↔ topic (used by matcher). Migration F."""

    __tablename__ = "talk_topics"
    __table_args__ = {"schema": "app"}

    talk_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("app.talks.id", ondelete="CASCADE"),
        primary_key=True,
    )
    topic_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("app.topics.id", ondelete="CASCADE"),
        primary_key=True,
    )
    weight: Mapped[float] = mapped_column(Numeric, nullable=False, default=1.0)
