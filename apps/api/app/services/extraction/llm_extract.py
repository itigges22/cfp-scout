"""Single LLM call → Pydantic-validated ``ExtractedConference`` (plan 15).

Wraps the LLM client with two responsibilities:
  * JSON-only output guard: strips markdown fences if the model emits any,
    then ``json.loads`` + ``ExtractedConference.model_validate``.
  * Failure mode: returns ``(None, error)`` rather than raising, so the
    pipeline can route the page to ``parse_status='extraction_failed'``
    instead of dying.

Dry-run note: with ``LLM_DRY_RUN=true`` the canned chat path in
``app.services.llm.dry_run.fake_chat`` recognises the ``extract:conference``
purpose and returns a valid JSON envelope; the rest of this module flows
through unchanged.
"""

from __future__ import annotations

import json
from typing import Final

import structlog
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.extraction.prompts import (
    PROMPT_VERSION,
    SYSTEM_PROMPT,
    build_user_prompt,
    extracted_conference_schema_json,
)
from app.services.extraction.schema import ExtractedConference
from app.services.llm import ChatMessage, ChatRequest, get_llm_client

log = structlog.get_logger("scout.extraction.llm")

# Stash for the cached schema string so we don't re-build per call.
_SCHEMA_JSON: Final[str] = extracted_conference_schema_json()


class ExtractionError(RuntimeError):
    """Raised internally; surfaced as ``(None, str)`` from :func:`extract`."""


async def extract(
    *,
    db: AsyncSession,
    page_text: str,
    source_url: str,
) -> tuple[ExtractedConference | None, str | None]:
    """Call the LLM, parse, validate. Returns ``(model, None)`` on success,
    ``(None, error_message)`` on failure."""
    if not page_text or not page_text.strip():
        return None, "empty page_text"

    user_prompt = build_user_prompt(
        page_text=page_text,
        source_url=source_url,
        schema_json=_SCHEMA_JSON,
    )

    req = ChatRequest(
        messages=[
            ChatMessage(role="system", content=SYSTEM_PROMPT),
            ChatMessage(role="user", content=user_prompt),
        ],
        purpose="extract:conference",
        # JSON tasks want low temperature; defaults to 0.2 in our client.
        temperature=0.0,
        max_tokens=2000,
    )

    try:
        resp = await get_llm_client().chat(req, db=db)
    except Exception as exc:  # noqa: BLE001 — surface as routed failure
        log.warning("extraction.llm_call_failed", error=str(exc))
        return None, f"llm_call_failed: {exc}"

    raw = resp.content.strip()
    cleaned = _strip_markdown_fences(raw)

    try:
        payload = json.loads(cleaned)
    except json.JSONDecodeError as exc:
        log.info(
            "extraction.json_decode_failed",
            preview=cleaned[:200],
            error=str(exc),
        )
        return None, f"non_json_output: {exc}"

    try:
        model = ExtractedConference.model_validate(payload)
    except ValidationError as exc:
        log.info(
            "extraction.schema_validation_failed",
            errors=exc.errors(include_url=False)[:5],
        )
        return None, f"schema_validation_failed: {exc.error_count()} errors"

    log.info(
        "extraction.ok",
        name=model.name,
        llm_confidence=model.confidence,
        prompt_version=PROMPT_VERSION,
    )
    return model, None


def _strip_markdown_fences(s: str) -> str:
    r"""Strip ```json ... ``` or ``` ... ``` wrappers.

    Models that disobey the "no markdown" instruction still typically just
    add fenced blocks; we accept those rather than failing.
    """
    s = s.strip()
    if s.startswith("```"):
        # Remove the opening fence (optionally with ``json`` language tag)
        nl = s.find("\n")
        if nl == -1:
            return s.strip("` \n")
        s = s[nl + 1 :]
    if s.endswith("```"):
        s = s[:-3]
    return s.strip()
