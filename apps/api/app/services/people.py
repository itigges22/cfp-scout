"""Our speakers, and the talks they can give.

WHAT THIS DOES
    CRUD for SMEs — bio, expertise, audiences, location — and for the talks
    library, including parsing an uploaded abstract or deck into a talk.

HOW IT CONNECTS
    Called by   api/v1/smes.py, api/v1/talks.py
    Writes      smes, talks and their topic/audience junctions
    Helpers     services/records.py, services/embeddings.py,
                services/llm.py, services/pdf.py

WORTH KNOWING
    One file because the matcher treats these as ONE signal: the speaker
    score compares a conference against SME bios AND the talks those
    people can give, pooled. A talk with no embedding is invisible to
    matching, and so is an SME with no bio — the same failure, in what
    used to be two files.
"""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime, timedelta
from uuid import UUID

import structlog
from fastapi import HTTPException, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import (
    AudienceProfile,
    Conference,
    ConferenceSeries,
    Sme,
    SmeAudience,
    SmePillar,
    Talk,
    TalkSubmission,
)
from app.schemas import (
    Page,
    ReuseCheckResult,
    SeriesReuseItem,
    SmeCreate,
    SmeRead,
    SmeUpdate,
    TalkCreate,
    TalkRead,
    TalkSubmissionCreate,
    TalkSubmissionRead,
    TalkSubmissionUpdate,
    TalkUpdate,
)
from app.services.embeddings import embed_owner
from app.services.llm import ChatMessage, ChatRequest, get_llm_client
from app.services.records import model_to_audit_dict, paginate, write_audit
from app.settings import get_settings

log = structlog.get_logger("scout.people")


# ==========================================================================
# sme_service.py
# ==========================================================================


async def _sync_sme_junctions(
    db: AsyncSession,
    sme_id: UUID,
    *,
    audience_ids: list[UUID],
    pillar_ids: list[UUID] | None = None,
) -> None:
    """Replace the SME's edges in ``sme_audiences`` and, when given,
    ``sme_pillars``.

    The denormalized arrays on the SME row are the user-facing surface; the
    junctions are the source of truth. Keeping them in
    sync is a single delete-then-insert per call, which fits this tiny scale.
    """
    await db.execute(delete(SmeAudience).where(SmeAudience.sme_id == sme_id))
    for aid in audience_ids:
        db.add(SmeAudience(sme_id=sme_id, audience_id=aid, weight=1.0))
    # None means "not mentioned" — a PATCH that never sends pillar_ids must
    # not silently unlink every pillar the SME already had.
    if pillar_ids is not None:
        await db.execute(delete(SmePillar).where(SmePillar.sme_id == sme_id))
        for pid in pillar_ids:
            db.add(SmePillar(sme_id=sme_id, pillar_id=pid))


async def _embed_bio_safely(db: AsyncSession, obj: Sme, *, purpose: str) -> None:
    """Embed the SME's bio + expertise. Failure leaves the row un-indexed; admin can retry.

    Expertise rides in the same vector as the bio on purpose: the ranker's
    bio-similarity dimension and the agent's retrieval both read sme_bio
    chunks, so free text typed into the expertise box starts influencing
    matches on the very next rescore with no new dimension, no new weight,
    and no new storage.
    """
    text = obj.bio if not (obj.expertise or "").strip() else f"{obj.bio}\n\n{obj.expertise}"
    try:
        await embed_owner(
            db,
            owner_type="sme_bio",
            owner_id=obj.id,
            text=text,
            purpose=purpose,
        )
        await db.commit()
    except Exception as exc:
        log.warning(
            "sme.embed_failed",
            sme_id=str(obj.id),
            error=f"{type(exc).__name__}: {exc}",
        )
        await db.rollback()


async def _embed_talk_safely(db: AsyncSession, obj: Talk, *, purpose: str) -> None:
    """Embed the talk's title + abstract. Failure leaves it un-indexed.

    A talk with no chunks is invisible to matching: the conference-detail
    talk ranking and the speaker signal both read talk chunks, so this is
    what makes a library talk participate in scoring at all.
    """
    text = talk_embed_text(obj)
    try:
        await embed_owner(
            db,
            owner_type="talk",
            owner_id=obj.id,
            text=text,
            purpose=purpose,
        )
        await db.commit()
    except Exception as exc:
        log.warning(
            "talk.embed_failed",
            talk_id=str(obj.id),
            error=f"{type(exc).__name__}: {exc}",
        )
        await db.rollback()


def talk_embed_text(obj: Talk) -> str:
    return f"{obj.title}\n\n{obj.abstract or ''}".strip()


async def _check_audience_ids(db: AsyncSession, ids: list[UUID]) -> None:
    if not ids:
        return
    count = (
        await db.execute(
            select(func.count(AudienceProfile.id)).where(
                AudienceProfile.id.in_(ids),
                AudienceProfile.is_active.is_(True),
            )
        )
    ).scalar_one()
    if int(count) != len(set(ids)):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="one or more audience_focus ids do not exist or are inactive",
        )


async def to_read(db: AsyncSession, obj: Sme) -> SmeRead:
    """SmeRead plus its pillar links.

    The junction is the source of truth and there is no column on the SME
    row for it, so a plain model_validate returns an empty list and the
    edit form silently drops every pillar on save.
    """
    read = SmeRead.model_validate(obj)
    pids = (
        (await db.execute(select(SmePillar.pillar_id).where(SmePillar.sme_id == obj.id)))
        .scalars()
        .all()
    )
    read.pillar_ids = list(pids)
    return read


async def list_smes(
    db: AsyncSession,
    *,
    page: int = 1,
    per_page: int = 20,
    q: str | None = None,
    team: str | None = None,
    #: True selects everyone NOT on the primary team. The SPA had an "other
    #: teams" tab that filtered the CURRENT PAGE client-side, so the count
    #: and the pagination were both wrong — a page of 20 could show 3 rows
    #: and the next page could be empty. The exclusion has to happen in the
    #: query for paging to mean anything.
    external_only: bool | None = None,
    is_active: bool | None = None,
) -> Page[SmeRead]:
    stmt = select(Sme).order_by(Sme.full_name.asc())
    if q:
        stmt = stmt.where(Sme.full_name.ilike(f"%{q}%"))
    if team:
        stmt = stmt.where(Sme.team == team)
    if external_only is not None:
        primary = get_settings().primary_team_label
        stmt = stmt.where(Sme.team != primary if external_only else Sme.team == primary)
    if is_active is not None:
        stmt = stmt.where(Sme.is_active.is_(is_active))

    rows, total = await paginate(db, stmt, page=page, per_page=per_page)
    return Page[SmeRead](
        items=[await to_read(db, r) for r in rows],
        total=total,
        page=page,
        per_page=per_page,
    )


async def get_sme(db: AsyncSession, sme_id: UUID) -> Sme:
    obj = await db.get(Sme, sme_id)
    if obj is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"sme {sme_id} not found",
        )
    return obj


async def create_sme(
    db: AsyncSession,
    payload: SmeCreate,
    *,
    actor_label: str = "system",
) -> Sme:
    # FK existence checks on the denormalized array columns.
    await _check_audience_ids(db, payload.audience_focus)

    data = payload.model_dump()
    # Not a column on Sme — it is a junction, handled below.
    pillar_ids = data.pop("pillar_ids", []) or []
    # external_links is a Pydantic model; flatten to dict for JSONB column.
    data["external_links"] = payload.external_links.model_dump(exclude_none=True)

    obj = Sme(**data)
    db.add(obj)
    await db.flush()

    await _sync_sme_junctions(
        db,
        obj.id,
        audience_ids=list(payload.audience_focus),
        pillar_ids=list(pillar_ids),
    )

    await write_audit(
        db,
        action="create",
        target_type="sme",
        target_id=obj.id,
        before=None,
        after=model_to_audit_dict(obj),
        actor_label=actor_label,
    )
    await db.commit()
    await db.refresh(obj)
    await _embed_bio_safely(db, obj, purpose="embed:sme_bio:create")
    await db.refresh(obj)  # _embed_bio_safely commits/rolls back, which expires obj
    return obj


async def update_sme(
    db: AsyncSession,
    sme_id: UUID,
    payload: SmeUpdate,
    *,
    actor_label: str = "system",
) -> Sme:
    obj = await get_sme(db, sme_id)
    before = model_to_audit_dict(obj)

    await _check_audience_ids(db, payload.audience_focus)

    data = payload.model_dump()
    # Junction, not a column. None here means "not mentioned by this PATCH".
    pillar_ids = data.pop("pillar_ids", None)
    data["external_links"] = payload.external_links.model_dump(exclude_none=True)
    for key, value in data.items():
        setattr(obj, key, value)
    await db.flush()
    # See audience_service.update_audience_profile: refresh after flush so
    # the next model_to_audit_dict access doesn't trip MissingGreenlet on
    # the expired onupdate=now() updated_at column.
    await db.refresh(obj)

    await _sync_sme_junctions(
        db,
        obj.id,
        audience_ids=list(payload.audience_focus),
        pillar_ids=None if pillar_ids is None else list(pillar_ids),
    )

    await write_audit(
        db,
        action="update",
        target_type="sme",
        target_id=obj.id,
        before=before,
        after=model_to_audit_dict(obj),
        actor_label=actor_label,
    )
    await db.commit()
    await db.refresh(obj)
    await _embed_bio_safely(db, obj, purpose="embed:sme_bio:update")
    await db.refresh(obj)  # _embed_bio_safely commits/rolls back, which expires obj
    return obj


async def deactivate_sme(
    db: AsyncSession,
    sme_id: UUID,
    *,
    actor_label: str = "system",
) -> None:
    obj = await get_sme(db, sme_id)
    if not obj.is_active:
        return

    before = model_to_audit_dict(obj)
    obj.is_active = False
    await db.flush()
    await db.refresh(obj)  # see update_sme

    await write_audit(
        db,
        action="deactivate",
        target_type="sme",
        target_id=obj.id,
        before=before,
        after=model_to_audit_dict(obj),
        actor_label=actor_label,
    )
    await db.commit()


# ==========================================================================
# talks.py
# ==========================================================================


_TALK_SCHEMA_JSON = json.dumps(
    {
        "type": "object",
        "properties": {
            "title": {"type": "string"},
            "abstract": {"type": "string", "description": "Clean 1-3 paragraph abstract"},
            "key_themes": {"type": "array", "items": {"type": "string"}},
            "suggested_pillar_name": {"type": ["string", "null"]},
            "target_audience_description": {"type": ["string", "null"]},
            "suggested_duration_minutes": {"type": ["integer", "null"]},
            "talk_format": {
                "type": ["string", "null"],
                "enum": ["keynote", "talk", "panel", "workshop", "tutorial", "other", None],
            },
        },
        "required": ["title", "abstract", "key_themes"],
    },
    indent=2,
)


class ExtractedTalk(BaseModel):
    model_config = ConfigDict(extra="ignore")

    title: str
    abstract: str
    key_themes: list[str] = []
    suggested_pillar_name: str | None = None
    target_audience_description: str | None = None
    suggested_duration_minutes: int | None = None
    talk_format: str | None = None


class TalkUploadPreview(BaseModel):
    extracted: ExtractedTalk


async def extract_talk_from_text(
    *,
    db: AsyncSession,
    full_text: str,
) -> ExtractedTalk:
    """Call the LLM and parse ExtractedTalk from raw text.

    Returns deterministic canned result in dry-run mode.
    """
    user_prompt = (
        f"Extract the talk fields from the document below.\n\n"
        f"Output schema:\n{_TALK_SCHEMA_JSON}\n\n"
        f"<talk_text>\n{full_text[:8000]}\n</talk_text>"
    )

    req = ChatRequest(
        messages=[
            ChatMessage(role="system", content=get_settings().prompt_talk_extraction),
            ChatMessage(role="user", content=user_prompt),
        ],
        purpose="extract:talk",
    )

    response = await get_llm_client().chat(req, db=db)
    raw = response.content.strip()

    # Strip markdown fences if model emits them
    raw = re.sub(r"^```(?:json)?\s*", "", raw)
    raw = re.sub(r"\s*```$", "", raw)

    try:
        data = json.loads(raw)
        return ExtractedTalk.model_validate(data)
    except Exception as exc:
        log.warning("talk.extraction.parse_failed", error=str(exc), raw_preview=raw[:200])
        # Return minimal structure rather than failing the whole request
        first_line = full_text.split("\n")[0][:200].strip()
        return ExtractedTalk(
            title=first_line or "Untitled Talk",
            abstract=full_text[:500],
        )


async def _get_talk_or_404(db: AsyncSession, talk_id: UUID) -> Talk:
    obj = await db.get(Talk, talk_id)
    if obj is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f"talk {talk_id} not found"
        )
    return obj


async def _build_talk_read(db: AsyncSession, talk: Talk) -> TalkRead:
    """Populate submissions (with conference names) for a talk row."""

    # Submissions, with conference names joined — the list answers "which
    # conferences did we pitch this to", and the UI was rendering truncated
    # UUIDs because that was all the payload carried.
    sub_rows = (
        await db.execute(
            select(TalkSubmission, Conference.name)
            .outerjoin(Conference, Conference.id == TalkSubmission.conference_id)
            .where(TalkSubmission.talk_id == talk.id)
            .order_by(TalkSubmission.created_at.desc())
        )
    ).all()
    submissions = []
    for s, conf_name in sub_rows:
        sub = TalkSubmissionRead.model_validate(s)
        sub.conference_name = conf_name
        submissions.append(sub)

    threshold = get_settings().talk_reuse_flag_threshold
    times_applied = len(submissions)

    data = TalkRead.model_validate(talk)
    data.submissions = submissions
    data.times_applied = times_applied
    data.is_flagged = times_applied >= threshold
    return data


async def list_talks(
    db: AsyncSession,
    *,
    page: int = 1,
    per_page: int = 20,
    pillar_id: UUID | None = None,
    sme_id: UUID | None = None,
    review_status: str | None = None,
    is_active: bool | None = True,
) -> Page[TalkRead]:
    stmt = select(Talk).order_by(Talk.created_at.desc())

    if pillar_id is not None:
        stmt = stmt.where(Talk.pillar_id == pillar_id)
    if sme_id is not None:
        stmt = stmt.where(Talk.primary_sme_id == sme_id)
    if review_status is not None:
        stmt = stmt.where(Talk.review_status == review_status)
    if is_active is not None:
        stmt = stmt.where(Talk.is_active.is_(is_active))

    rows, total = await paginate(db, stmt, page=page, per_page=per_page)
    items = [await _build_talk_read(db, r) for r in rows]
    return Page[TalkRead](items=items, total=total, page=page, per_page=per_page)


async def get_talk(db: AsyncSession, talk_id: UUID) -> TalkRead:
    talk = await _get_talk_or_404(db, talk_id)
    return await _build_talk_read(db, talk)


async def create_talk(db: AsyncSession, payload: TalkCreate) -> TalkRead:
    data = payload.model_dump(exclude={"co_speaker_ids"})
    data["co_speaker_ids"] = list(payload.co_speaker_ids)
    talk = Talk(**data)
    db.add(talk)
    await db.commit()
    await db.refresh(talk)
    await _embed_talk_safely(db, talk, purpose="embed:talk:create")
    await db.refresh(talk)  # _embed_talk_safely commits/rolls back, which expires talk
    return await _build_talk_read(db, talk)


async def update_talk(db: AsyncSession, talk_id: UUID, payload: TalkUpdate) -> TalkRead:
    talk = await _get_talk_or_404(db, talk_id)
    update_data = payload.model_dump(exclude_unset=True)
    if "co_speaker_ids" in update_data:
        update_data["co_speaker_ids"] = list(update_data["co_speaker_ids"])
    old_text = talk_embed_text(talk)
    had_chunks_deleted = not talk.is_active  # reactivation must restore the index
    for key, value in update_data.items():
        setattr(talk, key, value)
    await db.commit()
    await db.refresh(talk)
    if talk.is_active and (talk_embed_text(talk) != old_text or had_chunks_deleted):
        await _embed_talk_safely(db, talk, purpose="embed:talk:update")
        await db.refresh(talk)
    return await _build_talk_read(db, talk)


async def soft_delete_talk(db: AsyncSession, talk_id: UUID) -> None:
    talk = await _get_talk_or_404(db, talk_id)
    talk.is_active = False
    # Empty text through embed_owner deletes the talk's chunks without an
    # embedding call — a retired talk must stop influencing scores.
    await embed_owner(db, owner_type="talk", owner_id=talk.id, text="")
    await db.commit()


async def create_submission(
    db: AsyncSession, talk_id: UUID, payload: TalkSubmissionCreate
) -> TalkSubmissionRead:
    await _get_talk_or_404(db, talk_id)
    # Verify conference exists
    conf = await db.get(Conference, payload.conference_id)
    if conf is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"conference {payload.conference_id} not found",
        )
    row = TalkSubmission(
        talk_id=talk_id,
        conference_id=payload.conference_id,
        submitted_by_sme_id=payload.submitted_by_sme_id,
        submitted_at=payload.submitted_at,
        outcome=payload.outcome,
        notes=payload.notes,
    )
    db.add(row)
    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="talk already submitted to this conference",
        ) from exc
    await db.refresh(row)
    return TalkSubmissionRead.model_validate(row)


async def update_submission(
    db: AsyncSession, talk_id: UUID, sub_id: UUID, payload: TalkSubmissionUpdate
) -> TalkSubmissionRead:
    row = await db.get(TalkSubmission, sub_id)
    if row is None or row.talk_id != talk_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="submission not found")
    update_data = payload.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(row, key, value)
    await db.commit()
    await db.refresh(row)
    return TalkSubmissionRead.model_validate(row)


async def delete_submission(db: AsyncSession, talk_id: UUID, sub_id: UUID) -> None:
    row = await db.get(TalkSubmission, sub_id)
    if row is None or row.talk_id != talk_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="submission not found")
    await db.delete(row)
    await db.commit()


async def reuse_check(db: AsyncSession, talk_id: UUID) -> ReuseCheckResult:
    await _get_talk_or_404(db, talk_id)
    cutoff = datetime.now(tz=UTC).date() - timedelta(days=365)

    # Count submissions in last 12 months
    count_12m = (
        await db.execute(
            select(func.count()).where(
                TalkSubmission.talk_id == talk_id,
                TalkSubmission.submitted_at >= cutoff,
            )
        )
    ).scalar_one()
    count_12m = int(count_12m)

    # Series reuse: find all conferences this talk was submitted to and group by series
    sub_rows = (
        await db.execute(
            select(TalkSubmission, Conference)
            .join(Conference, Conference.id == TalkSubmission.conference_id)
            .where(TalkSubmission.talk_id == talk_id)
        )
    ).all()

    series_counts: dict[UUID, tuple[str, int]] = {}
    for sub, conf in sub_rows:
        if conf.series_id is not None:
            if conf.series_id not in series_counts:
                series = await db.get(ConferenceSeries, conf.series_id)
                name = series.canonical_name if series else str(conf.series_id)
                series_counts[conf.series_id] = (name, 0)
            existing = series_counts[conf.series_id]
            series_counts[conf.series_id] = (existing[0], existing[1] + 1)

    series_reuse = [
        SeriesReuseItem(series_id=sid, series_name=name, submission_count=count)
        for sid, (name, count) in series_counts.items()
        if count >= 2
    ]

    # Determine risk level
    high_series = any(item.submission_count >= 2 for item in series_reuse)
    if count_12m >= 3 or high_series:
        risk_level = "high"
        if high_series:
            worst = max(series_reuse, key=lambda x: x.submission_count)
            warning = f"Already submitted to {worst.series_name} — resubmission may be flagged"
        else:
            warning = "High reuse risk — may appear as a marketing campaign"
    elif count_12m >= 1:
        risk_level = "medium"
        warning = f"Submitted to {count_12m} conference(s) recently"
    else:
        risk_level = "low"
        warning = None

    return ReuseCheckResult(
        talk_id=talk_id,
        submission_count_12m=count_12m,
        series_reuse=series_reuse,
        risk_level=risk_level,
        warning=warning,
    )
