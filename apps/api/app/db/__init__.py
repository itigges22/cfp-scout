"""Database layer.

This package owns SQLAlchemy ORM machinery: declarative base, async session
factory, and the per-table ORM models (in ``models/``, landing in plan 06
pass 2).

The runtime connection uses the limited ``app`` role created by
``infra/postgres/init/02-roles-and-schemas.sql``. Alembic uses the
superuser DSN built from POSTGRES_* env vars (see ``Settings.superuser_sync_dsn``).
"""
