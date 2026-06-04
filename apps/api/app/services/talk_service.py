"""Talk library service — CRUD for talks, tags, submissions, reuse checks."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from uuid import UUID

import structlog
from fastapi import HTTPException, status
from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.entities import (
    Conference,
    ConferenceSeries,
    PastConference,
    Sme,
    StrategicPillar,
    Talk,
    TalkSubmission,
    TalkTag,
    Topic,
)
from app.settings import get_settings
from app.db.models.junctions import TalkTagAssignment, TalkTopic
from app.schemas.talk import (
    ReuseCheckResult,
    SeriesReuseItem,
    TalkCreate,
    TalkRead,
    TalkSubmissionCreate,
    TalkSubmissionRead,
    TalkSubmissionUpdate,
    TalkTagCreate,
    TalkTagRead,
    TalkTagUpdate,
    TalkTopicRead,
    TalkUpdate,
)
from app.schemas.common import Page
from app.services._common import paginate

log = structlog.get_logger("scout.services.talk")


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


async def _get_talk_or_404(db: AsyncSession, talk_id: UUID) -> Talk:
    obj = await db.get(Talk, talk_id)
    if obj is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"talk {talk_id} not found")
    return obj


async def _build_talk_read(db: AsyncSession, talk: Talk) -> TalkRead:
    """Populate tags, topics, and submissions for a talk row."""
    # Tags
    tag_rows = (
        await db.execute(
            select(TalkTag)
            .join(TalkTagAssignment, TalkTagAssignment.tag_id == TalkTag.id)
            .where(TalkTagAssignment.talk_id == talk.id)
        )
    ).scalars().all()
    tags = [TalkTagRead.model_validate(t) for t in tag_rows]

    # Topics
    topic_rows = (
        await db.execute(
            select(Topic, TalkTopic.weight)
            .join(TalkTopic, TalkTopic.topic_id == Topic.id)
            .where(TalkTopic.talk_id == talk.id)
        )
    ).all()
    topics = [
        TalkTopicRead(id=t.id, name=t.name, weight=float(w))
        for t, w in topic_rows
    ]

    # Submissions
    sub_rows = (
        await db.execute(
            select(TalkSubmission)
            .where(TalkSubmission.talk_id == talk.id)
            .order_by(TalkSubmission.created_at.desc())
        )
    ).scalars().all()
    submissions = [TalkSubmissionRead.model_validate(s) for s in sub_rows]

    threshold = get_settings().talk_reuse_flag_threshold
    times_applied = len(submissions)

    data = TalkRead.model_validate(talk)
    data.tags = tags
    data.topics = topics
    data.submissions = submissions
    data.times_applied = times_applied
    data.is_flagged = times_applied >= threshold
    return data


# ---------------------------------------------------------------------------
# Talk CRUD
# ---------------------------------------------------------------------------


async def list_talks(
    db: AsyncSession,
    *,
    page: int = 1,
    per_page: int = 20,
    pillar_id: UUID | None = None,
    tag_id: UUID | None = None,
    sme_id: UUID | None = None,
    review_status: str | None = None,
    is_active: bool | None = True,
) -> Page[TalkRead]:
    stmt = select(Talk).order_by(Talk.created_at.desc())

    if pillar_id is not None:
        stmt = stmt.where(Talk.pillar_id == pillar_id)
    if tag_id is not None:
        stmt = stmt.join(
            TalkTagAssignment, TalkTagAssignment.talk_id == Talk.id
        ).where(TalkTagAssignment.tag_id == tag_id)
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
    return await _build_talk_read(db, talk)


async def update_talk(db: AsyncSession, talk_id: UUID, payload: TalkUpdate) -> TalkRead:
    talk = await _get_talk_or_404(db, talk_id)
    update_data = payload.model_dump(exclude_unset=True)
    if "co_speaker_ids" in update_data:
        update_data["co_speaker_ids"] = list(update_data["co_speaker_ids"])
    for key, value in update_data.items():
        setattr(talk, key, value)
    await db.commit()
    await db.refresh(talk)
    return await _build_talk_read(db, talk)


async def soft_delete_talk(db: AsyncSession, talk_id: UUID) -> None:
    talk = await _get_talk_or_404(db, talk_id)
    talk.is_active = False
    await db.commit()


# ---------------------------------------------------------------------------
# Submissions
# ---------------------------------------------------------------------------


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
    except IntegrityError:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="talk already submitted to this conference",
        )
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


# ---------------------------------------------------------------------------
# Reuse check
# ---------------------------------------------------------------------------


async def reuse_check(db: AsyncSession, talk_id: UUID) -> ReuseCheckResult:
    talk = await _get_talk_or_404(db, talk_id)
    cutoff = datetime.now(tz=timezone.utc).date() - timedelta(days=365)

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


# ---------------------------------------------------------------------------
# Talk tags
# ---------------------------------------------------------------------------


async def list_tags(db: AsyncSession) -> list[TalkTagRead]:
    rows = (await db.execute(select(TalkTag).order_by(TalkTag.name))).scalars().all()
    return [TalkTagRead.model_validate(r) for r in rows]


async def create_tag(db: AsyncSession, payload: TalkTagCreate) -> TalkTagRead:
    row = TalkTag(name=payload.name, color=payload.color)
    db.add(row)
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"tag '{payload.name}' already exists",
        )
    await db.refresh(row)
    return TalkTagRead.model_validate(row)


async def update_tag(db: AsyncSession, tag_id: UUID, payload: TalkTagUpdate) -> TalkTagRead:
    row = await db.get(TalkTag, tag_id)
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="tag not found")
    update_data = payload.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(row, key, value)
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"tag name already taken",
        )
    await db.refresh(row)
    return TalkTagRead.model_validate(row)


async def delete_tag(db: AsyncSession, tag_id: UUID) -> None:
    row = await db.get(TalkTag, tag_id)
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="tag not found")
    await db.delete(row)
    await db.commit()
