"""Extraction package (plan 15).

Turns raw HTML scraped by plan 14 into structured ``conferences`` rows.

Public surface:
  * :func:`parse_raw_page` — full pipeline (clean → LLM extract → validate
    → dedupe → persist + topic-normalize → update raw_pages.parse_status)
  * :class:`ParseResult` — typed return record

Internals (importable but stable):
  * :mod:`.cleaning`    — trafilatura HTML → text
  * :mod:`.dedup`       — slug-based conference dedupe (same-year)
  * :mod:`.llm_extract` — single LLM call + Pydantic envelope
  * :mod:`.prompts`     — system / user prompt builders (prompt-injection
                          hardened)
  * :mod:`.schema`      — ExtractedConference + nested types
  * :mod:`.topics`      — normalize free-text topics against the controlled
                          vocabulary; insert pending_review for unknowns
  * :mod:`.validation`  — rule-set + confidence penalties
"""

from app.services.extraction.pipeline import ParseResult, parse_raw_page

__all__ = ["ParseResult", "parse_raw_page"]
