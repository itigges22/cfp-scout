"""Shared pytest configuration (plan 27).

We deliberately avoid an autoused DB or HTTP fixture here — the unit
suite tests pure functions; integration tests against a real Postgres
live separately (plan 27 pass 2 will wire testcontainers).

A few env defaults are stamped so a developer running `pytest` outside
the container doesn't need to set up `.env` first.
"""

from __future__ import annotations

import os


def _ensure(env_key: str, default: str) -> None:
    os.environ.setdefault(env_key, default)


# Settings the validator requires before app imports work. These are
# safe-to-default; tests that need real connectivity supply their own.
_ensure("DATABASE_URL", "postgresql+asyncpg://app:app@postgres:5432/scout")
_ensure("POSTGRES_USER", "scout")
_ensure("POSTGRES_PASSWORD", "scoutdev")
_ensure("POSTGRES_DB", "scout")
_ensure("LLM_BASE_URL", "https://llm.example.invalid/v1")
_ensure("LLM_API_KEY", "sk-test-not-real")
_ensure("LLM_DRY_RUN", "true")

# ...but setdefault loses to a real key already exported in the shell, and
# then the suite calls the operator's production LLM: slow, flaky on any
# upstream blip, and it spends real budget. One upstream 500 failed
# tests/integration/test_talks.py with a traceback that looked like a code
# bug and was not one. So this is FORCED rather than defaulted.
# Opt out deliberately with SCOUT_TEST_ALLOW_REAL_LLM=1.
if os.environ.get("SCOUT_TEST_ALLOW_REAL_LLM") != "1":
    os.environ["LLM_DRY_RUN"] = "true"
_ensure("SCRAPER_USER_AGENT", "Scout-Test/1.0")
_ensure("DECAY_ENABLED", "true")
