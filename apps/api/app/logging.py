"""structlog configuration.

Two output modes:
  * ``json``    - one structured log record per line. Production default. Parsable by jq.
  * ``console`` - pretty-printed, colored. Dev override.

A redaction processor scrubs sensitive substrings from every record. This is
the LAST line of defense — code that logs a SecretStr will still leak its
value if SecretStr.get_secret_value() is called and the result is logged.
Don't do that. The processor catches accidents like logging a dict that
includes an api_key key.
"""

from __future__ import annotations

import logging
import re
import sys
from typing import Any

import structlog
from structlog.types import EventDict, Processor

# ---------------------------------------------------------------------------
# Redaction
# ---------------------------------------------------------------------------
# Keys whose values are replaced with '***'. Matched case-insensitively on
# the key name within the EventDict and nested dicts.
_REDACT_KEYS = frozenset(
    {
        "api_key",
        "apikey",
        "authorization",
        "auth",
        "password",
        "passwd",
        "secret",
        "token",
        "access_token",
        "refresh_token",
        "x-api-key",
        "llm_api_key",
        "postgres_password",
        "set-cookie",
        "cookie",
    }
)

# Patterns that look like bearer tokens / api keys appearing in values.
# Conservative — we replace match groups rather than the whole value to
# preserve context like "request to Bearer <redacted>".
_REDACT_VALUE_PATTERNS = (
    re.compile(r"(Bearer\s+)([A-Za-z0-9._\-]+)", re.IGNORECASE),
    re.compile(r"(sk-)([A-Za-z0-9]{16,})"),
    re.compile(r"(\bapi[_-]?key\s*[:=]\s*)([^\s,]+)", re.IGNORECASE),
)


def _redact_value(value: Any) -> Any:
    """Recursively redact sensitive content in strings, dicts, and lists.

    Tuples are not used as event-dict containers; we treat them as opaque.
    """
    if isinstance(value, dict):
        return {
            k: ("***" if k.lower() in _REDACT_KEYS else _redact_value(v)) for k, v in value.items()
        }
    if isinstance(value, list):
        return [_redact_value(v) for v in value]
    if isinstance(value, str):
        result = value
        for pattern in _REDACT_VALUE_PATTERNS:
            result = pattern.sub(r"\1***", result)
        return result
    return value


def _redact_processor(_logger: Any, _name: str, event_dict: EventDict) -> EventDict:
    """structlog processor: redact known-sensitive keys and patterns."""
    return {
        k: ("***" if k.lower() in _REDACT_KEYS else _redact_value(v)) for k, v in event_dict.items()
    }


# ---------------------------------------------------------------------------
# Renderers + configuration
# ---------------------------------------------------------------------------
def configure_logging(level: str = "INFO", fmt: str = "json") -> None:
    """Wire structlog + stdlib logging.

    Call once at process startup (we do so in main.py before app creation).
    Subsequent calls reconfigure; tests rely on this.
    """
    # stdlib logging → structlog. Required because libraries (sqlalchemy,
    # uvicorn) use stdlib logging; we want their records in the same format.
    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
        level=getattr(logging, level.upper(), logging.INFO),
    )

    shared_processors: list[Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        _redact_processor,
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
    ]

    if fmt == "json":
        renderer: Processor = structlog.processors.JSONRenderer()
    else:
        renderer = structlog.dev.ConsoleRenderer(colors=True)

    structlog.configure(
        processors=[*shared_processors, renderer],
        wrapper_class=structlog.make_filtering_bound_logger(
            getattr(logging, level.upper(), logging.INFO)
        ),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )


def get_logger(name: str | None = None) -> Any:
    """Convenience wrapper. Modules just do ``log = get_logger(__name__)``."""
    return structlog.get_logger(name)
