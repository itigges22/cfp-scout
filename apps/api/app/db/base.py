"""SQLAlchemy declarative base + project-wide naming conventions.

ORM models inherit from :class:`Base`. The naming convention below makes
Alembic's auto-naming of constraints deterministic — without it, every
``alembic revision --autogenerate`` produces churn in random-looking
constraint names.
"""

from __future__ import annotations

from sqlalchemy import MetaData
from sqlalchemy.orm import DeclarativeBase

# ---------------------------------------------------------------------------
# Naming convention for indexes + constraints
# ---------------------------------------------------------------------------
# Required for stable Alembic autogenerate output. See:
#   https://alembic.sqlalchemy.org/en/latest/naming.html
#
# Pattern keys:
#   ix  - index
#   uq  - unique constraint
#   ck  - check constraint
#   fk  - foreign key
#   pk  - primary key
NAMING_CONVENTION = {
    "ix": "ix_%(table_name)s_%(column_0_N_name)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}

# A shared MetaData ensures every model registers against the same metadata
# object — critical for Alembic's autogenerate to see them all.
metadata = MetaData(naming_convention=NAMING_CONVENTION)


class Base(DeclarativeBase):
    """Declarative base for every ORM model in the project.

    Per-model ``__table_args__`` should set ``{"schema": "<schema_name>"}`` so
    tables land in the correct schema (app / vectors / audit / jobs). See
    ADR-0002 for the schema layout.
    """

    metadata = metadata
