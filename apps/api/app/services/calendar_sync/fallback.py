"""Docling-based fallback for the calendar-sync importer.

Triggered when the CSV linter raises (wrong columns, non-CSV file,
unreadable encoding). The strategy:

  1. Write the upload to a temp file.
  2. Run Docling's DocumentConverter to get text (handles PDF, DOCX,
     XLSX, HTML, MD, PNG).
  3. Hand the text to an LLM with a focused prompt that emits a JSON
     list of events with the same shape as LintedEvent — so the mapper
     code path stays shared.

If Docling itself can't read the file (truly garbage upload), we surface
that as a clean error rather than 500-ing.
"""

from __future__ import annotations

import json
import tempfile
from datetime import datetime
from pathlib import Path

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.calendar_sync.linter import LintedEvent
from app.services.llm import ChatMessage as LLMChatMessage
from app.services.llm import ChatRequest, get_llm_client

log = structlog.get_logger("scout.calendar_sync.fallback")

_PROMPT_VERSION = "calendar_sync.fallback.v1"

_SYSTEM_PROMPT = """\
You extract a list of professional events from arbitrary document text \
(could be a CSV, a calendar export, a PDF schedule, a Word doc, etc.).

Output STRICTLY valid JSON in this shape — no commentary, no markdown:

{
  "events": [
    {
      "complete": false,
      "type": "Corporate" | "Grassroots" | "Meetups" | "Developer Days" | "Research" | "",
      "name": "string (required)",
      "start_date": "YYYY-MM-DD" | null,
      "end_date": "YYYY-MM-DD" | null,
      "city": "string",
      "country": "string (ISO-3166-1 alpha-2 if known, else full name)",
      "attendees_raw": "comma-separated names of people attending",
      "description": "string",
      "activities": "string"
    }
  ]
}

Rules:
- `name` is mandatory; skip rows with no name.
- `complete` should be true ONLY if the event has already happened
  (start_date in the past) or the document explicitly marks it complete.
- Use null for `start_date` / `end_date` if you can't determine them.
- If only one of start/end is known, set the other to the same value.
- Be conservative: if a row looks like a header, quarter marker, or
  navigation, skip it. Don't invent events that aren't in the text."""


class FallbackError(RuntimeError):
    """Both linter and Docling+LLM failed. Caller surfaces as 422."""


async def fallback_extract(
    db: AsyncSession,
    *,
    content: bytes,
    filename: str,
    fallback_year: int = 2026,
) -> list[LintedEvent]:
    """Parse `content` with Docling, then LLM-extract a list of events.

    Returns LintedEvent rows in the same shape the strict CSV linter
    produces, so the mapper handles both paths identically.
    """
    # 1) Docling parse to text.
    text = await _docling_to_text(content, filename)
    if not text or len(text.strip()) < 50:
        raise FallbackError(
            "Docling could not extract enough text from the upload "
            f"({len(text or '')} chars). File may be empty or unsupported."
        )

    # Cap context — large XLSX dumps can produce hundreds of KB of text
    # and the model has a context budget. 60K chars ≈ 15K tokens, well
    # within llama-scout-17b's window with room for response.
    if len(text) > 60_000:
        text = text[:60_000] + "\n…(truncated)"

    # 2) LLM extract → JSON.
    req = ChatRequest(
        messages=[
            LLMChatMessage(role="system", content=_SYSTEM_PROMPT),
            LLMChatMessage(
                role="user",
                content=(
                    f"Document text:\n\n{text}\n\n"
                    "Return the events JSON now."
                ),
            ),
        ],
        purpose="calendar_sync_fallback",
        temperature=0.1,
        max_tokens=4000,
    )
    resp = await get_llm_client().chat(req, db=db)
    payload = _parse_json_block(resp.content)
    raw_events = payload.get("events") or []
    if not isinstance(raw_events, list):
        raise FallbackError(
            f"LLM returned non-list `events` field ({type(raw_events).__name__})"
        )

    out: list[LintedEvent] = []
    for idx, raw in enumerate(raw_events, start=1):
        if not isinstance(raw, dict):
            continue
        name = (raw.get("name") or "").strip()
        if not name:
            continue
        start = _parse_iso(raw.get("start_date"))
        end = _parse_iso(raw.get("end_date")) or start
        warnings: list[str] = []
        if start is None:
            warnings.append("LLM-extracted: no start date")
        out.append(
            LintedEvent(
                complete=bool(raw.get("complete", False)),
                type=str(raw.get("type") or "").strip(),
                name=name,
                start_date=start,
                end_date=end,
                city=str(raw.get("city") or "").strip(),
                country=str(raw.get("country") or "").strip(),
                attendees_raw=str(raw.get("attendees_raw") or "").strip(),
                description=str(raw.get("description") or "").strip(),
                activities=str(raw.get("activities") or "").strip(),
                # Source row index is synthetic for the fallback path;
                # 1000+ to disambiguate from real CSV row numbers.
                source_row=1000 + idx,
                warnings=warnings,
            )
        )
    log.info(
        "calendar_sync.fallback.done",
        filename=filename,
        text_chars=len(text),
        events_extracted=len(out),
        prompt_version=_PROMPT_VERSION,
    )
    return out


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
async def _docling_to_text(content: bytes, filename: str) -> str:
    """Write to temp file, run Docling's DocumentConverter, return text.

    Synchronous Docling call wrapped in run_in_threadpool. Cheap to write
    a temp file — Docling needs a path, not bytes."""
    from anyio import to_thread

    # Pick a suffix that hints at the format so Docling routes the
    # right backend. .csv / .xlsx / .pdf / .docx etc.
    suffix = Path(filename).suffix or ".bin"
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        tmp.write(content)
        tmp_path = Path(tmp.name)

    try:
        return await to_thread.run_sync(_docling_sync, tmp_path)
    finally:
        tmp_path.unlink(missing_ok=True)


def _docling_sync(path: Path) -> str:
    try:
        from docling.document_converter import DocumentConverter
    except ImportError as exc:
        raise FallbackError(
            "Docling is not installed in this environment — fallback unavailable."
        ) from exc

    converter = DocumentConverter()
    try:
        result = converter.convert(str(path))
    except Exception as exc:  # noqa: BLE001 — bubble as a clean FallbackError
        raise FallbackError(f"Docling failed to parse the file: {exc}") from exc

    doc = result.document
    if doc is None:
        raise FallbackError("Docling returned no document for this file.")
    # `export_to_markdown` covers tables in XLSX and structure in PDFs;
    # both work fine for the LLM prompt downstream.
    return doc.export_to_markdown() or ""


def _parse_json_block(text: str) -> dict:
    """LLM occasionally wraps JSON in code fences or adds a preamble.
    Strip the wrapper and parse."""
    if not text:
        return {}
    s = text.strip()
    # Strip leading/trailing code fences.
    if s.startswith("```"):
        # ```json\n{...}\n```
        s = s.split("\n", 1)[1] if "\n" in s else s
        if s.endswith("```"):
            s = s[: -3]
    # Find first { and last } to handle stray preambles.
    start = s.find("{")
    end = s.rfind("}")
    if start == -1 or end == -1 or end <= start:
        raise FallbackError(f"LLM did not return JSON. Got: {text[:200]!r}")
    try:
        return json.loads(s[start : end + 1])
    except json.JSONDecodeError as exc:
        raise FallbackError(f"LLM returned malformed JSON: {exc}") from exc


def _parse_iso(value) -> datetime | None:
    if value in (None, "", "null"):
        return None
    if not isinstance(value, str):
        return None
    for fmt in ("%Y-%m-%d", "%Y-%m-%dT%H:%M:%S"):
        try:
            return datetime.strptime(value, fmt)
        except ValueError:
            continue
    return None
