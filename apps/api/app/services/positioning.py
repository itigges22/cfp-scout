"""What we say we care about: messaging documents and strategic pillars.

WHAT THIS DOES
    CRUD for the product-positioning documents an operator uploads and for
    the strategic themes the org tracks, plus the LLM passes that extract
    claims from a document and flesh out a thin pillar.

HOW IT CONNECTS
    Called by   api/v1/messaging.py, api/v1/pillars.py, app/maintenance.py
    Writes      messaging_docs, pillars, pillar_docs
    Helpers     services/llm.py, services/embeddings.py, services/pdf.py

WORTH KNOWING
    One file because the matcher pools them into ONE signal: 'fit' is the
    conference text against messaging AND pillars together, rescaled once.
    They are two corpora answering a single question, and they fail the
    same way — a pillar with a one-line description embeds badly and
    matches nothing, which is exactly why enrichment exists.

    Both defined a ``_SYSTEM_PROMPT``; they are now
    ``get_settings().prompt_messaging_extraction`` and ``get_settings().prompt_pillar_enrichment``.
"""

from __future__ import annotations

import json
import re
from uuid import UUID

import structlog
from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import (
    AudienceProfile,
    Conference,
    ConferencePillar,
    DocumentChunk,
    Match,
    MessagingDocument,
    Sme,
    SmePillar,
    StrategicPillar,
    Talk,
)
from app.schemas import (
    MessagingDocumentCreate,
    MessagingDocumentRead,
    MessagingDocumentUpdate,
    MessagingDocUploadPreview,
    Page,
    PillarCreate,
    PillarRead,
    PillarUpdate,
    SmePillarLink,
    SmePillarRead,
)
from app.services.embeddings import embed_owner
from app.services.llm import ChatMessage, ChatRequest, get_llm_client
from app.services.records import model_to_audit_dict, paginate, write_audit
from app.settings import get_settings

log = structlog.get_logger("scout.positioning")


# ==========================================================================
# messaging.py
# ==========================================================================


_SCHEMA_JSON = json.dumps(
    {
        "type": "object",
        "properties": {
            "title": {
                "type": "string",
                "description": "Document title or inferred product/initiative name (3-80 chars)",
            },
            "elevator_pitch": {
                "type": "string",
                "description": (
                    "2-4 sentence summary of the product's value proposition and market position. "
                    "Should be specific enough for a conference abstract review."
                ),
            },
            "target_personas": {
                "type": "array",
                "items": {"type": "string"},
                "description": (
                    "Job titles, roles, or audience segments this product targets. "
                    "Examples: 'VP of Engineering', 'Data Scientists', 'Platform Teams'."
                ),
            },
            "key_themes": {
                "type": "array",
                "items": {"type": "string"},
                "description": (
                    "Topic areas and technology themes central to this product's story. "
                    "Examples: 'MLOps', 'developer experience', 'AI safety', 'platform engineering'. "
                    "These will be matched against conference topic vocabularies."
                ),
            },
            "talking_points": {
                "type": "array",
                "items": {"type": "string"},
                "description": (
                    "Specific claims, proof points, or messages to convey. "
                    "Keep each to 1-2 sentences."
                ),
            },
            "differentiators": {
                "type": "array",
                "items": {"type": "string"},
                "description": "What makes this product or approach distinct from alternatives.",
            },
            "competitive_position": {
                "type": "string",
                "description": (
                    "Brief summary of the competitive landscape and where this product fits. "
                    "Leave empty if not present in the document."
                ),
            },
        },
        "required": ["title", "elevator_pitch", "target_personas", "key_themes", "talking_points"],
    },
    indent=2,
)


async def extract_messaging_from_text(
    *,
    db: AsyncSession,
    full_text: str,
    doc_kind: str = "other",
) -> MessagingDocUploadPreview:
    """Call the LLM and parse MessagingDocUploadPreview from raw document text."""
    kind_hint = {
        "gtm_strategy": "This is a GTM (Go-To-Market) Strategy document.",
        "content_roadmap": "This is a Content Roadmap document.",
    }.get(doc_kind, "This is a product positioning or marketing document.")

    user_prompt = (
        f"{kind_hint}\n\n"
        f"Extract the messaging fields from the document below.\n\n"
        # Spelled out because Qwen otherwise echoes the schema itself and
        # nests the answers under "properties" — which parsed, validated,
        # and produced a blank review form.
        f"Return a FLAT JSON object whose top-level keys are exactly the "
        f"field names from the schema. Do NOT echo the schema, do NOT wrap "
        f"anything in 'properties'.\n\n"
        f"Output schema:\n{_SCHEMA_JSON}\n\n"
        f"<doc_text>\n{full_text[:12000]}\n</doc_text>"
    )

    req = ChatRequest(
        messages=[
            ChatMessage(role="system", content=get_settings().prompt_messaging_extraction),
            ChatMessage(role="user", content=user_prompt),
        ],
        purpose="extract:messaging",
    )

    response = await get_llm_client().chat(req, db=db)
    raw = response.content.strip()
    # Always log a fingerprint of what came back. An extraction that "works"
    # but returns an empty object is invisible without this — it validated,
    # so parse_failed never fired, and the operator just saw a blank form.
    log.info(
        "messaging.extraction.response",
        chars=len(raw),
        head=raw[:300],
    )

    raw = re.sub(r"^```(?:json)?\s*", "", raw)
    raw = re.sub(r"\s*```$", "", raw)

    try:
        data = json.loads(raw)
        # Qwen frequently echoes the JSON-Schema wrapper and nests the real
        # values under "properties". That parsed cleanly, validation ignored
        # the unknown keys, and every field fell back to its empty default —
        # so the operator got a blank review form presented as success.
        if (
            isinstance(data, dict)
            and "title" not in data
            and isinstance(data.get("properties"), dict)
        ):
            data = data["properties"]
        preview = MessagingDocUploadPreview.model_validate(data)
        preview.doc_kind = doc_kind
        # Clamp to the SAVE schema's limits (ShortTitle 120, ElevatorPitch
        # 600, ListItem/TalkingPoint 200 each). The LLM writes to the
        # prompt's "1-2 sentences" guidance, not to the validators — so an
        # extraction could be perfectly good and still 422 the moment the
        # operator hit Save, with the review form born invalid through no
        # action of theirs. Trimming here means the form starts saveable
        # and anything cut is visible on screen for them to restore.
        preview.title = preview.title[:120].strip()
        preview.elevator_pitch = preview.elevator_pitch[:600].strip()
        preview.competitive_position = (preview.competitive_position or "")[:500].strip()
        for attr in ("target_personas", "key_themes", "talking_points", "differentiators"):
            items = [i[:200].strip() for i in getattr(preview, attr) if i and i.strip()]
            setattr(preview, attr, items[:12])
        if not (preview.title or preview.elevator_pitch or preview.key_themes):
            # Shaped like a preview, contains nothing. Failing loudly beats
            # returning a blank form the operator has to type into.
            raise ValueError("extraction returned an empty preview")
        return preview
    except Exception as exc:
        log.warning("messaging.extraction.parse_failed", error=str(exc), raw_preview=raw[:200])
        first_line = full_text.split("\n")[0][:120].strip()
        return MessagingDocUploadPreview(
            doc_kind=doc_kind,
            title=first_line or "Untitled Document",
            elevator_pitch=full_text[:300],
        )


def messaging_embed_text(m: MessagingDocument) -> str:
    """Compose the text we embed for similarity search against this messaging doc.

    The structured fields are joined into a single document so the matcher's
    the fit signal can hit any of them.
    """
    parts = [
        m.title,
        m.elevator_pitch,
        "Target personas: " + "; ".join(m.target_personas),
        "Key themes: " + "; ".join(m.key_themes),
        "Talking points: " + "; ".join(m.talking_points),
    ]
    if m.differentiators:
        parts.append("Differentiators: " + "; ".join(m.differentiators))
    if m.competitive_position:
        parts.append(f"Competitive position: {m.competitive_position}")
    if m.raw_content:
        # PDF-source docs have raw_content populated at upload; include it
        # so chunking can split across the body too.
        parts.append(m.raw_content)
    return "\n".join(parts)


async def _embed_safely(db: AsyncSession, obj: MessagingDocument, *, purpose: str) -> None:
    """Embed in a separate logical step; failures don't break the create flow."""
    try:
        await embed_owner(
            db,
            owner_type="messaging",
            owner_id=obj.id,
            text=messaging_embed_text(obj),
            purpose=purpose,
        )
        await db.commit()
    except Exception as exc:
        log.warning(
            "messaging.embed_failed",
            messaging_id=str(obj.id),
            error=f"{type(exc).__name__}: {exc}",
        )
        await db.rollback()


async def list_messaging_documents(
    db: AsyncSession,
    *,
    page: int = 1,
    per_page: int = 20,
    q: str | None = None,
    is_active: bool | None = None,
    pillar_id: UUID | None = None,
) -> Page[MessagingDocumentRead]:
    stmt = select(MessagingDocument).order_by(MessagingDocument.updated_at.desc())
    if q:
        stmt = stmt.where(MessagingDocument.title.ilike(f"%{q}%"))
    if is_active is not None:
        stmt = stmt.where(MessagingDocument.is_active.is_(is_active))
    if pillar_id is not None:
        stmt = stmt.where(MessagingDocument.pillar_id == pillar_id)

    rows, total = await paginate(db, stmt, page=page, per_page=per_page)
    return Page[MessagingDocumentRead](
        items=[MessagingDocumentRead.model_validate(r) for r in rows],
        total=total,
        page=page,
        per_page=per_page,
    )


async def get_messaging_document(db: AsyncSession, doc_id: UUID) -> MessagingDocument:
    obj = await db.get(MessagingDocument, doc_id)
    if obj is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"messaging_document {doc_id} not found",
        )
    return obj


async def create_messaging_document(
    db: AsyncSession,
    payload: MessagingDocumentCreate,
    *,
    actor_label: str = "system",
) -> MessagingDocument:
    obj = MessagingDocument(**payload.model_dump())
    db.add(obj)
    await db.flush()  # populate obj.id without committing yet

    await write_audit(
        db,
        action="create",
        target_type="messaging_document",
        target_id=obj.id,
        before=None,
        after=model_to_audit_dict(obj),
        actor_label=actor_label,
    )
    await db.commit()
    await db.refresh(obj)
    await _embed_safely(db, obj, purpose="embed:messaging:create")
    return obj


async def update_messaging_document(
    db: AsyncSession,
    doc_id: UUID,
    payload: MessagingDocumentUpdate,
    *,
    actor_label: str = "system",
) -> MessagingDocument:
    obj = await get_messaging_document(db, doc_id)
    before = model_to_audit_dict(obj)

    for key, value in payload.model_dump().items():
        setattr(obj, key, value)
    await db.flush()
    # TimestampedMixin.updated_at has onupdate=func.now(); flush expires it
    # so a synchronous model_to_audit_dict access would trip MissingGreenlet.
    await db.refresh(obj)

    await write_audit(
        db,
        action="update",
        target_type="messaging_document",
        target_id=obj.id,
        before=before,
        after=model_to_audit_dict(obj),
        actor_label=actor_label,
    )
    await db.commit()
    await db.refresh(obj)
    await _embed_safely(db, obj, purpose="embed:messaging:update")
    return obj


async def deactivate_messaging_document(
    db: AsyncSession,
    doc_id: UUID,
    *,
    actor_label: str = "system",
) -> None:
    """Soft-delete via is_active=false. Hard delete is intentionally not exposed."""
    obj = await get_messaging_document(db, doc_id)
    if not obj.is_active:
        return  # idempotent

    before = model_to_audit_dict(obj)
    obj.is_active = False
    await db.flush()
    await db.refresh(obj)  # see update_messaging_document

    await write_audit(
        db,
        action="deactivate",
        target_type="messaging_document",
        target_id=obj.id,
        before=before,
        after=model_to_audit_dict(obj),
        actor_label=actor_label,
    )
    await db.commit()


# ==========================================================================
# pillars.py
# ==========================================================================


PROMPT_VERSION = "pillar.enrichment.v1"


def _build_user_prompt(
    *, pillar_name: str, pillar_tagline: str, doc_texts: list[tuple[str, str]]
) -> str:
    """Compose the per-pillar user message.

    ``doc_texts`` is a list of (title, raw_text) tuples — each
    messaging document's full content. We concatenate them inside a
    single ``<documents>`` block so the model can't be confused into
    treating instruction-like content inside the docs as instructions.
    """
    doc_block_lines: list[str] = []
    for title, text in doc_texts:
        # Tag each doc internally so the LLM can attribute content to
        # the right source if it chooses to (we don't require it to,
        # but it helps the model stay grounded).
        doc_block_lines.append(f"\n--- DOCUMENT: {title} ---\n{text}\n")
    docs_blob = "\n".join(doc_block_lines)
    return (
        f"Pillar: {pillar_name}\n"
        f"Pillar tagline (existing short description): {pillar_tagline}\n\n"
        f"<documents>{docs_blob}</documents>\n\n"
        "Write the 500-800 word long-form description of this pillar now, "
        "drawing only on the documents above."
    )


async def load_messaging_corpus(db: AsyncSession) -> list[tuple[str, str]]:
    """Return ``[(title, full_text), ...]`` for every active messaging
    document.

    ``MessagingDocument.raw_content`` is often NULL on docs ingested
    via the structured-form path (only the chunked text survives in
    ``vectors.document_chunks``). To stay robust we prefer
    ``raw_content`` when present and fall back to concatenating that
    doc's chunks in chunk-index order.
    """
    docs = (
        (
            await db.execute(
                select(MessagingDocument)
                .where(MessagingDocument.is_active.is_(True))
                .order_by(MessagingDocument.created_at)
            )
        )
        .scalars()
        .all()
    )
    if not docs:
        return []
    doc_ids = [d.id for d in docs]
    # One round-trip — pull every chunk for every active doc, then
    # bucket them in memory.
    chunk_rows = (
        await db.execute(
            select(DocumentChunk.owner_id, DocumentChunk.text)
            .where(
                DocumentChunk.owner_type == "messaging",
                DocumentChunk.owner_id.in_(doc_ids),
            )
            .order_by(DocumentChunk.owner_id, DocumentChunk.id)
        )
    ).all()
    chunks_by_doc: dict = {}
    for owner_id, text in chunk_rows:
        chunks_by_doc.setdefault(owner_id, []).append(text)

    out: list[tuple[str, str]] = []
    for d in docs:
        if d.raw_content and d.raw_content.strip():
            out.append((d.title, d.raw_content))
            continue
        chunks = chunks_by_doc.get(d.id, [])
        joined = "\n\n".join(c for c in chunks if c and c.strip())
        if joined:
            out.append((d.title, joined))
    return out


async def enrich_pillar(
    *,
    db: AsyncSession,
    pillar: StrategicPillar,
    corpus: list[tuple[str, str]] | None = None,
) -> str | None:
    """Generate a 500-800 word pillar-specific description by extracting
    content from the operator's active messaging documents.

    ``corpus`` can be passed pre-loaded by the caller when enriching
    multiple pillars in one batch — avoids re-querying the messaging
    docs N times. Otherwise we load it ourselves.

    Returns the description text, or None on LLM failure / empty
    corpus. Non-fatal — caller decides what to do (we don't raise so
    a single bad pillar doesn't poison a 4-pillar batch).
    """
    if corpus is None:
        corpus = await load_messaging_corpus(db)
    if not corpus:
        log.warning(
            "pillar_enrichment.no_corpus",
            pillar=pillar.name,
            reason="no active messaging documents with raw_content",
        )
        return None
    user_prompt = _build_user_prompt(
        pillar_name=pillar.name,
        pillar_tagline=pillar.description,
        doc_texts=corpus,
    )
    req = ChatRequest(
        messages=[
            ChatMessage(role="system", content=get_settings().prompt_pillar_enrichment),
            ChatMessage(role="user", content=user_prompt),
        ],
        purpose="enrich:pillar",
        temperature=0.2,
        # 500-800 words is roughly 700-1100 tokens; cap at 1200 with a
        # small safety margin so the LLM never truncates mid-sentence.
        max_tokens=1200,
    )
    try:
        resp = await get_llm_client().chat(req, db=db)
    except Exception as exc:
        log.warning(
            "pillar_enrichment.llm_failed",
            pillar=pillar.name,
            error=str(exc)[:200],
        )
        return None
    text = (resp.content or "").strip()
    if not text:
        return None
    # Sanity bound — anything over ~6000 chars (~1000 words) is the LLM
    # rambling beyond our 800-word ask.
    if len(text) > 6000:
        text = text[:6000].rsplit(".", 1)[0] + "."
    return text


async def _get_pillar_or_404(db: AsyncSession, pillar_id: UUID) -> StrategicPillar:
    obj = await db.get(StrategicPillar, pillar_id)
    if obj is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"pillar {pillar_id} not found",
        )
    return obj


async def _build_pillar_read(db: AsyncSession, p: StrategicPillar) -> PillarRead:
    """Attach aggregate counts to a pillar row."""
    sme_count = (
        await db.execute(select(func.count()).where(SmePillar.pillar_id == p.id))
    ).scalar_one()
    talk_count = (
        await db.execute(
            select(func.count()).where(Talk.pillar_id == p.id, Talk.is_active.is_(True))
        )
    ).scalar_one()
    audience_count = (
        await db.execute(
            select(func.count()).where(
                AudienceProfile.pillar_id == p.id, AudienceProfile.is_active.is_(True)
            )
        )
    ).scalar_one()
    conference_count = (
        await db.execute(select(func.count()).where(Conference.assigned_pillar_id == p.id))
    ).scalar_one()

    data = PillarRead.model_validate(p)
    data.sme_count = int(sme_count)
    data.talk_count = int(talk_count)
    data.audience_count = int(audience_count)
    data.conference_count = int(conference_count)
    return data


async def delete_pillar(db: AsyncSession, pillar_id: UUID) -> None:
    p = await _get_pillar_or_404(db, pillar_id)
    await db.delete(p)
    await db.commit()


async def create_pillar(db: AsyncSession, payload: PillarCreate) -> PillarRead:
    max_order = (await db.execute(select(func.max(StrategicPillar.display_order)))).scalar_one()
    order = (max_order or 0) + 1 if payload.display_order is None else payload.display_order
    p = StrategicPillar(name=payload.name, description=payload.description, display_order=order)
    db.add(p)
    await db.commit()
    await db.refresh(p)
    return await _build_pillar_read(db, p)


async def list_pillars(db: AsyncSession) -> list[PillarRead]:
    rows = (
        (await db.execute(select(StrategicPillar).order_by(StrategicPillar.display_order)))
        .scalars()
        .all()
    )
    return [await _build_pillar_read(db, p) for p in rows]


async def get_pillar(db: AsyncSession, pillar_id: UUID) -> PillarRead:
    p = await _get_pillar_or_404(db, pillar_id)
    return await _build_pillar_read(db, p)


async def update_pillar(db: AsyncSession, pillar_id: UUID, payload: PillarUpdate) -> PillarRead:
    p = await _get_pillar_or_404(db, pillar_id)
    p.name = payload.name
    p.description = payload.description
    await db.commit()
    await db.refresh(p)
    return await _build_pillar_read(db, p)


async def link_sme(
    db: AsyncSession, pillar_id: UUID, sme_id: UUID, payload: SmePillarLink
) -> SmePillarRead:
    await _get_pillar_or_404(db, pillar_id)
    sme = await db.get(Sme, sme_id)
    if sme is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"sme {sme_id} not found")

    existing = await db.get(SmePillar, (sme_id, pillar_id))
    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="sme already linked to this pillar",
        )
    row = SmePillar(sme_id=sme_id, pillar_id=pillar_id, is_primary=payload.is_primary)
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return SmePillarRead.model_validate(row)


async def unlink_sme(db: AsyncSession, pillar_id: UUID, sme_id: UUID) -> None:
    row = await db.get(SmePillar, (sme_id, pillar_id))
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="sme not linked to this pillar",
        )
    await db.delete(row)
    await db.commit()


async def list_pillar_smes(db: AsyncSession, pillar_id: UUID) -> list[SmePillarRead]:
    await _get_pillar_or_404(db, pillar_id)
    rows = (
        (
            await db.execute(
                select(SmePillar)
                .where(SmePillar.pillar_id == pillar_id)
                .order_by(SmePillar.is_primary.desc())
            )
        )
        .scalars()
        .all()
    )
    return [SmePillarRead.model_validate(r) for r in rows]


async def list_pillar_conferences(
    db: AsyncSession, pillar_id: UUID, *, limit: int = 15
) -> list[dict]:
    """Conferences ranked by their alignment edge to THIS pillar.

    Reads conference_pillars (matcher-written per-pillar scores, floored at
    0.1), not assigned_pillar_id — the old filter only showed conferences
    whose TOP pillar was this one, so a conference strongly relevant to two
    pillars appeared on one page and was invisible on the other.

    overall_score goes through live_overall_score like every other surface;
    a second definition here is exactly the "two screens, two numbers" bug
    the scoring redesign existed to kill.
    """
    from app.services.matcher import live_overall_score, load_boost_context

    await _get_pillar_or_404(db, pillar_id)
    settings = get_settings()
    rows = (
        await db.execute(
            select(Conference, ConferencePillar.score, Match)
            .join(ConferencePillar, ConferencePillar.conference_id == Conference.id)
            .outerjoin(Match, Match.conference_id == Conference.id)
            .where(ConferencePillar.pillar_id == pillar_id)
            .where(Conference.status != "quarantined")
            .order_by(ConferencePillar.score.desc())
            .limit(limit)
        )
    ).all()

    boost_ctx = await load_boost_context(db) if rows else None
    items: list[dict] = []
    for conf, pillar_score, match in rows:
        overall = None
        if match is not None:
            overall = await live_overall_score(
                db=db,
                conference=conf,
                fit=match.fit_score,
                speakers=match.speaker_score,
                settings=settings,
                context=boost_ctx,
            )
        items.append(
            {
                "id": str(conf.id),
                "name": conf.name,
                "slug": conf.slug,
                "status": conf.status,
                "event_kind": conf.event_kind,
                "pillar_score": round(float(pillar_score), 4),
                "overall_score": round(overall, 4) if overall is not None else None,
                "start_date": conf.start_date,
                "cfp_close_at": conf.cfp_close_at,
            }
        )
    return items


async def list_pillar_talks(db: AsyncSession, pillar_id: UUID) -> list[dict]:
    await _get_pillar_or_404(db, pillar_id)
    rows = (
        (
            await db.execute(
                select(Talk).where(Talk.pillar_id == pillar_id, Talk.is_active.is_(True))
            )
        )
        .scalars()
        .all()
    )
    return [
        {
            "id": str(r.id),
            "title": r.title,
            "review_status": r.review_status,
        }
        for r in rows
    ]


async def list_pillar_audiences(db: AsyncSession, pillar_id: UUID) -> list[dict]:
    await _get_pillar_or_404(db, pillar_id)
    rows = (
        (
            await db.execute(
                select(AudienceProfile).where(
                    AudienceProfile.pillar_id == pillar_id,
                    AudienceProfile.is_active.is_(True),
                )
            )
        )
        .scalars()
        .all()
    )
    return [
        {
            "id": str(r.id),
            "name": r.name,
            "description": r.description,
        }
        for r in rows
    ]
