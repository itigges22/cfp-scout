"""Mixins shared across ORM models.

Keep this thin — only patterns that apply to many tables. Per-model
behaviour stays in the model file itself.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func


def uuid_pk() -> Mapped[uuid.UUID]:
    """Standard UUID primary key, server-side default via ``gen_random_uuid()``.

    Helper exists because every table uses this exact pattern. Returning the
    Mapped column directly lets each model class declare:

        id: Mapped[uuid.UUID] = uuid_pk()
    """
    return mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )


class TimestampedMixin:
    """Adds ``created_at`` and ``updated_at`` to a model.

    Server-side defaults via ``now()`` so insertions don't require a
    Python-side timestamp. ``updated_at`` updates on UPDATE via
    ``onupdate=func.now()``.
    """

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
