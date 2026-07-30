"""The throttle must never become the thing that stops the app.

It sits in front of every chat and embedding call in the process, so a bug
here is not slow — it is total. Both cases below were real: one wedged the
process forever, the other turned a throttle into a global queue.
"""

from __future__ import annotations

import asyncio
import time

import pytest
from app.services.llm import TokenBucket


@pytest.mark.asyncio
async def test_a_cost_larger_than_capacity_returns_instead_of_hanging() -> None:
    """The bug that wedged the pod.

    _refill caps the pool at capacity, so `tokens >= cost` is unreachable
    for an oversized cost. The old loop waited for it anyway, forever, while
    holding the lock — every LLM call in the process blocked behind one
    large document with no error and no timeout.
    """
    bucket = TokenBucket(capacity=100.0, refill_per_second=10.0)
    await asyncio.wait_for(bucket.acquire(100_000.0), timeout=1.0)


@pytest.mark.asyncio
async def test_an_oversized_cost_does_not_block_the_next_caller() -> None:
    """The oversized request must not poison the bucket for everyone else."""
    bucket = TokenBucket(capacity=100.0, refill_per_second=1000.0)
    await asyncio.wait_for(bucket.acquire(100_000.0), timeout=1.0)
    await asyncio.wait_for(bucket.acquire(10.0), timeout=1.0)


@pytest.mark.asyncio
async def test_waiting_does_not_hold_the_lock() -> None:
    """A caller that has to wait must not serialise everyone behind it.

    Two callers each needing half the pool should overlap, not queue: the
    total should track the refill time, not the sum of two independent waits.
    """
    bucket = TokenBucket(capacity=10.0, refill_per_second=100.0)
    await bucket.acquire(10.0)  # drain

    start = time.monotonic()
    await asyncio.wait_for(
        asyncio.gather(bucket.acquire(5.0), bucket.acquire(5.0)), timeout=2.0
    )
    elapsed = time.monotonic() - start
    # 10 tokens at 100/s = 0.1s if they overlap; ~0.15s+ if serialised.
    assert elapsed < 0.4, f"waiters appear serialised ({elapsed:.3f}s)"


@pytest.mark.asyncio
async def test_it_still_actually_throttles() -> None:
    """Removing the deadlock must not remove the point of the class."""
    bucket = TokenBucket(capacity=10.0, refill_per_second=100.0)
    await bucket.acquire(10.0)
    start = time.monotonic()
    await bucket.acquire(10.0)
    assert time.monotonic() - start >= 0.05, "no throttling happened at all"


@pytest.mark.asyncio
async def test_refill_never_banks_more_than_capacity() -> None:
    """The cap is what makes an oversized cost unsatisfiable, so it is the
    reason the deadlock existed. Pin it."""
    bucket = TokenBucket(capacity=10.0, refill_per_second=1_000_000.0)
    await asyncio.sleep(0.02)  # would bank 20_000 tokens without the cap
    bucket._refill()
    assert bucket._tokens == 10.0
