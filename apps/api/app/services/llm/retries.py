"""Retry policy for transient LLM API errors.

Retries on:
  * 429 Too Many Requests
  * 5xx server errors
  * Network errors (connection reset, timeout)

Does NOT retry on:
  * 400/401/403/404 — those are client bugs, not transient
  * Pydantic validation errors — same
"""

from __future__ import annotations

import logging

from openai import APIConnectionError, APITimeoutError, RateLimitError
from tenacity import (
    AsyncRetrying,
    before_sleep_log,
    retry_if_exception_type,
    stop_after_attempt,
    wait_random_exponential,
)

# tenacity's before_sleep_log wants a stdlib logger, not a structlog binder.
# Stdlib logging is already wired into the structlog pipeline (plan 06's
# `configure_logging`), so log records still flow through the JSON renderer.
_stdlib_log = logging.getLogger("scout.llm.retries")

# Maximum attempts including the first try. 4 = first + 3 retries.
MAX_ATTEMPTS = 4

# Jittered exponential backoff. wait = random(0, 2^attempt) up to max.
WAIT = wait_random_exponential(multiplier=1, min=1, max=30)


# Server-side openai errors that are worth retrying.
RETRYABLE_TYPES = (
    APIConnectionError,
    APITimeoutError,
    RateLimitError,
    # InternalServerError lives in openai.InternalServerError but inheritance
    # chains differ across versions; the generic APIError covers 5xx too.
)


def get_retry() -> AsyncRetrying:
    """Create a fresh AsyncRetrying configured per the policy above."""
    return AsyncRetrying(
        stop=stop_after_attempt(MAX_ATTEMPTS),
        wait=WAIT,
        retry=retry_if_exception_type(RETRYABLE_TYPES),
        before_sleep=before_sleep_log(_stdlib_log, logging.WARNING),
        reraise=True,
    )
