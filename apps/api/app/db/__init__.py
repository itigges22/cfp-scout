"""The database layer -- engine, sessions, and one class per table.

WHAT THIS DOES
    Holds everything that talks to Postgres: the declarative base every
    table class inherits (``base.py``), the async engine and session
    factory (``session.py``), and the ORM models (``models/``). No
    business logic lives here -- services and API routes import from this
    package and do the thinking themselves.

    Postgres is split into four schemas: ``app`` (working data),
    ``vectors`` (embeddings), ``audit`` (append-only history), and
    ``jobs`` (APScheduler's own bookkeeping). Every model declares which
    one it belongs to.

HOW IT CONNECTS
    Called by   app/api/v1/*, app/services/*, app/tasks/*,
                app/maintenance.py, alembic/env.py
    Reads       all four Postgres schemas
    Helpers     app/settings.py for the connection URLs
    Tuning      settings.database_url (the limited ``app`` role used at
                runtime); settings.superuser_sync_dsn, built from the
                POSTGRES_* variables and used only by Alembic

WORTH KNOWING
    The runtime role is not the superuser. It is created by
    ``infra/postgres/init/02-roles-and-schemas.sql`` and has, for example,
    no UPDATE or DELETE on the audit schema. Code that needs more than
    that privilege set belongs in a migration, not in the app.
"""
