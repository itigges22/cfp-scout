"""Periodic heartbeat task — sanity check that the scheduler is alive.

Registered to run every 10 minutes by :func:`app.scheduler.register_jobs`.
Each fire writes a `heartbeat` row in ``app.ingest_jobs`` so operators can
verify the scheduler from psql:

    SELECT MAX(started_at) FROM app.ingest_jobs WHERE kind = 'heartbeat';

If that timestamp is older than ~20 minutes, the scheduler has fallen over.
"""

from __future__ import annotations

from app.tasks._runner import run_as_job


async def _do_heartbeat() -> dict[str, str]:
    return {"alive": "true"}


async def heartbeat() -> dict[str, object]:
    """APScheduler-callable entry point."""
    return await run_as_job("heartbeat", _do_heartbeat)
