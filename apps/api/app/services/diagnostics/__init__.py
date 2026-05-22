"""Diagnostics aggregator (plan 26).

Single denormalized response that powers the ``/diagnostics`` page. Six
panels: LLM spend, jobs, scraper, data quality, digest, system.

30s in-memory cache so spamming refresh doesn't pummel Postgres + APScheduler
introspection.
"""

from app.services.diagnostics.aggregator import (
    DiagnosticsCache,
    build_diagnostics,
    invalidate_cache,
)

__all__ = ["DiagnosticsCache", "build_diagnostics", "invalidate_cache"]
