"""HTML → clean text via trafilatura (plan 15).

trafilatura is the canonical "boilerplate-stripping" library — it walks an
HTML tree, identifies the main content area, drops nav/footer/sidebars, and
emits plain text. Cleaner input means smaller prompts means lower LLM cost
and less room for the model to hallucinate from nav links.

We feed trafilatura the raw HTML bytes (decoded via its own detection).
For non-HTML content types we return the body as text directly.
"""

from __future__ import annotations

from pathlib import Path

import structlog

log = structlog.get_logger("scout.extraction.cleaning")

# Cap on cleaned-text length sent to the LLM. ~24 KB is enough for a typical
# conference page; longer pages get truncated with a flagged note. chat-model's
# 8B has a ~128k context, but we'd rather pay for a focused extraction than
# pour the whole sitemap into the context.
MAX_CLEANED_CHARS = 24_000


def clean_html_to_text(body: bytes | str, *, content_type: str = "") -> str:
    """Return the cleaned, plain-text representation of ``body``.

    For HTML inputs, runs trafilatura with ``include_comments=False`` and
    ``favor_precision=True``. Anything trafilatura can't parse falls back
    to the body decoded as UTF-8 (replace errors) — better something than
    nothing.
    """
    if isinstance(body, bytes):
        try:
            body_text = body.decode("utf-8", errors="replace")
        except Exception:  # noqa: BLE001
            body_text = body.decode("latin-1", errors="replace")
    else:
        body_text = body

    if "html" not in content_type.lower() and not body_text.lstrip().startswith("<"):
        # Probably not HTML — return as-is, capped.
        return _cap(body_text)

    try:
        import trafilatura
    except ImportError as exc:  # pragma: no cover — dep is pinned in pyproject
        log.error("extraction.trafilatura_missing", error=str(exc))
        return _cap(body_text)

    extracted = trafilatura.extract(
        body_text,
        include_comments=False,
        include_tables=True,
        favor_precision=True,
        deduplicate=True,
    )
    if not extracted or not extracted.strip():
        # trafilatura sometimes returns None for tiny pages; fall back to raw.
        log.info("extraction.trafilatura_empty_fallback")
        return _cap(body_text)
    return _cap(extracted)


def clean_html_file(path: str | Path) -> str:
    """Convenience: read the raw_pages file from disk and clean."""
    p = Path(path)
    return clean_html_to_text(p.read_bytes(), content_type="text/html")


def _cap(text: str) -> str:
    text = text.strip()
    if len(text) <= MAX_CLEANED_CHARS:
        return text
    head = text[: MAX_CLEANED_CHARS - 100]
    return head + "\n\n[...page truncated for extraction context window...]"
