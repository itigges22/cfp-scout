"""Autonomous conference discovery (plan 35, PRD §1 + §4).

The piece the curated-source scraper from plan 14 doesn't cover: given a
template prompt, Scout searches the open web, fetches candidates with
Crawl4AI, and runs each through the existing extraction + matcher
pipeline.

Public surface:

  * :func:`run_discovery(db, prompt, max_results)` — one-shot orchestrator
    used by the admin endpoint + scheduled cron.
  * :class:`DiscoveryResult`                       — typed return value.
  * search-provider plumbing lives in ``search.py``; Crawl4AI wrapper in
    ``crawler.py``. Both are kept small and individually testable.
"""

from app.services.web_discovery.orchestrator import (
    DiscoveryResult,
    run_discovery,
)

__all__ = ["DiscoveryResult", "run_discovery"]
