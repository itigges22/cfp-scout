"""Per-process async token-bucket rate limiter.

Single-user local install, single api process — one bucket is enough. If
we ever scale out the api, swap this for a Redis-backed bucket.

Two buckets:
  * requests/sec  — caps concurrent calls
  * tokens/min    — caps total tokens consumed across all calls (input+output estimate)

For Phase 1 we use generous defaults; MaaS's own rate limits are the real backstop.
"""

from __future__ import annotations

import asyncio
import time

import structlog

log = structlog.get_logger("scout.llm.rate_limit")


class TokenBucket:
    """Simple async token bucket: a refilling pool of `capacity` units."""

    def __init__(self, *, capacity: float, refill_per_second: float):
        self._capacity = capacity
        self._tokens = capacity
        self._refill_per_second = refill_per_second
        self._last_refill = time.monotonic()
        self._lock = asyncio.Lock()

    async def acquire(self, cost: float = 1.0) -> None:
        """Block until `cost` tokens are available, then consume them."""
        async with self._lock:
            while True:
                self._refill()
                if self._tokens >= cost:
                    self._tokens -= cost
                    return
                shortfall = cost - self._tokens
                wait_s = shortfall / max(self._refill_per_second, 0.01)
                log.debug("rate_limit.wait", wait_s=wait_s, shortfall=shortfall)
                await asyncio.sleep(wait_s)

    def _refill(self) -> None:
        now = time.monotonic()
        delta = now - self._last_refill
        self._tokens = min(self._capacity, self._tokens + delta * self._refill_per_second)
        self._last_refill = now


# Module-level singletons. Tuned for typical MaaS limits.
# Adjust via env in a future pass if MaaS rate limiting bites.
_REQUESTS_BUCKET = TokenBucket(capacity=20, refill_per_second=10)  # 10 rps sustained, 20 burst
_TOKENS_BUCKET = TokenBucket(capacity=100_000, refill_per_second=2000)  # ~120k tokens/min


async def acquire_request_slot() -> None:
    await _REQUESTS_BUCKET.acquire(1.0)


async def acquire_tokens(estimated_tokens: int) -> None:
    """Reserve token budget BEFORE the call. We use the prompt size as
    an estimate; the actual consumption may differ but the bucket recovers."""
    await _TOKENS_BUCKET.acquire(float(estimated_tokens))
