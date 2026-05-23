"""Calendar-sync importer for the AI BU Developer Marketing events sheet.

Mirrors the parsing logic in a teammate's calendar-sync utility —
same exact columns, same date parser, same row-filter rules — so a CSV
that runs cleanly through that cron also runs cleanly through Scout.

Public entry: ``import_calendar_sync_csv``. Tries the strict linter first;
on format error (wrong columns, non-CSV upload), falls back to
Docling + LLM extraction. Returns a preview-or-apply result the endpoint
surfaces as JSON.
"""

from __future__ import annotations

from dataclasses import dataclass

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.calendar_sync.fallback import FallbackError, fallback_extract
from app.services.calendar_sync.linter import (
    LintedEvent,
    LinterFormatError,
    lint_calendar_sync_csv,
)
from app.services.calendar_sync.mapper import MapResult, map_events

log = structlog.get_logger("scout.calendar_sync")


@dataclass(slots=True)
class ImportOutcome:
    """What happened at the top level — the endpoint surfaces this as JSON."""

    source: str  # "linter" | "docling_fallback"
    skipped_rows: int  # from the linter pre-mapper
    file_warnings: list[str]
    fallback_error: str | None
    map_result: MapResult

    def to_dict(self) -> dict:
        d = {
            "source": self.source,
            "skipped_rows": self.skipped_rows,
            "file_warnings": self.file_warnings,
            "fallback_error": self.fallback_error,
        }
        d.update(self.map_result.to_dict())
        return d


async def import_calendar_sync_csv(
    db: AsyncSession,
    *,
    content: bytes,
    filename: str,
    apply: bool,
    fallback_year: int = 2026,
    actor_label: str = "calendar_sync_import",
) -> ImportOutcome:
    """Orchestrate the linter + Docling-fallback import.

    Args:
        content: raw upload bytes.
        filename: original filename — used to pick the Docling backend
                  in the fallback path.
        apply: if True, persist; if False (preview), compute decisions
               without writing.
        fallback_year: passed through to the linter for date parsing
                       when the CSV has no year in the date column.
        actor_label: audit-log + imported_from tag.
    """
    events: list[LintedEvent] = []
    file_warnings: list[str] = []
    skipped_rows = 0
    source = "linter"
    fallback_error: str | None = None

    # 1) Strict linter first.
    try:
        lint = lint_calendar_sync_csv(content, fallback_year=fallback_year)
        events = lint.events
        skipped_rows = lint.skipped
        file_warnings = lint.warnings
        log.info(
            "calendar_sync.linter.ok",
            filename=filename,
            events=len(events),
            skipped=skipped_rows,
            warnings=len(file_warnings),
        )
    except LinterFormatError as lint_err:
        # 2) Fall back to Docling + LLM.
        log.warning(
            "calendar_sync.linter.format_error",
            filename=filename,
            error=str(lint_err)[:200],
        )
        try:
            events = await fallback_extract(
                db, content=content, filename=filename, fallback_year=fallback_year
            )
            source = "docling_fallback"
            file_warnings = [
                f"linter failed ({lint_err}); used Docling + LLM extraction "
                f"as fallback. Review the rows carefully before applying."
            ]
        except FallbackError as fb_err:
            fallback_error = f"linter failed: {lint_err} · fallback failed: {fb_err}"
            log.error(
                "calendar_sync.fallback.failed",
                filename=filename,
                error=fallback_error,
            )
            return ImportOutcome(
                source="docling_fallback",
                skipped_rows=0,
                file_warnings=[],
                fallback_error=fallback_error,
                map_result=MapResult(decisions=[]),
            )

    # 3) Map the linted events into Scout rows.
    map_result = await map_events(
        db, events, apply=apply, actor_label=actor_label
    )
    if apply:
        # apply_diff-style: caller commits. We just flush so subsequent
        # SELECTs in the same request see the writes.
        await db.flush()
    return ImportOutcome(
        source=source,
        skipped_rows=skipped_rows,
        file_warnings=file_warnings,
        fallback_error=None,
        map_result=map_result,
    )
