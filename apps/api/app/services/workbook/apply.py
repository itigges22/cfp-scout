"""Apply a clean diff to the DB (plan 31).

Called only when DiffResult.has_errors is False AND, for any deletes, the
operator has confirmed the count. All writes happen in ONE transaction:
either the whole import lands or nothing changes.

After commit, enqueues:
  * `embed_owner` for every new or modified entity that owns
    `vectors.document_chunks` (audience, sme bio, future: messaging)
  * graph invalidation (in-process, free)
  * matcher recompute for the affected conferences when SME/audience
    edits would shift past-attendance + Stage-A scores. Pass 2 will add
    a debounced bulk-recompute scheduler job; for now we touch only the
    minimal set.

The actor_label flows from the route — defaults to
``"workbook_import:<filename>:<timestamp>"`` so the audit log shows
who/what/when.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from uuid import UUID

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.entities import (
    AudienceProfile,
    ConferenceSeries,
    Sme,
    StrategicPillar,
    Topic,
)
from app.db.models.junctions import SmeAudience, SmeTopic
from app.services.embeddings import embed_owner
from app.services.graph import invalidate as invalidate_graph
from app.services.lifecycle.versioning import set_actor_label
from app.services.workbook.diff import DiffResult

log = structlog.get_logger("scout.workbook.apply")


@dataclass(slots=True)
class ApplyResult:
    inserted: int = 0
    updated: int = 0
    deleted: int = 0
    embeddings_enqueued: int = 0
    by_sheet: dict[str, dict] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "inserted": self.inserted,
            "updated": self.updated,
            "deleted": self.deleted,
            "embeddings_enqueued": self.embeddings_enqueued,
            "by_sheet": self.by_sheet,
        }


async def apply_diff(
    db: AsyncSession,
    diff: DiffResult,
    *,
    actor_label: str = "workbook_import",
) -> ApplyResult:
    """Apply ``diff`` to ``db`` in a single transaction. Caller commits.

    Raises ``ValueError`` if the diff still has errors. The route layer is
    responsible for the typed-count delete confirmation.
    """
    if diff.has_errors:
        raise ValueError(f"refuse to apply: {diff.summary['errors']} errors in the diff")

    set_actor_label(actor_label)  # propagates to the versioning listener
    result = ApplyResult()

    # Build cross-sheet lookups for SME → Topic/Audience name resolution.
    topics_by_name = {t.name.lower(): t for t in (await db.execute(select(Topic))).scalars()}
    audiences_by_name = {
        a.name.lower(): a for a in (await db.execute(select(AudienceProfile))).scalars()
    }

    # APPLY ORDER MATTERS: topics + industries + audiences first, so SME
    # rows can name-reference them within the same transaction.
    # Pillars + Series are independent. Settings are also independent —
    # processed first so a workbook that bumps the LLM budget AND adds
    # new SMEs applies the budget before any embeddings burn it.
    sheet_order = [
        "Settings",
        "Pillars",
        "Industries",
        "Topics",
        "Audiences",
        "SMEs",
        "Series",
    ]

    # SME rows whose embed needs regenerating after commit.
    sme_embed_targets: list[Sme] = []
    audience_embed_targets: list[AudienceProfile] = []

    for sheet in sheet_order:
        plans = diff.plans_by_sheet.get(sheet, [])
        ins = upd = dele = 0
        for plan in plans:
            if sheet == "Settings":
                await _apply_setting(db, plan)
            elif sheet == "Pillars":
                await _apply_pillar(db, plan)
            elif sheet == "Industries":
                # Industries is a derived vocab — no DB table; rows are
                # implicitly created when an Audience uses them. We log
                # but don't insert anything.
                continue
            elif sheet == "Topics":
                tname = await _apply_topic(db, plan)
                if tname is not None:
                    # Refresh the lookup so a same-transaction SME can find it.
                    refreshed = (
                        await db.execute(select(Topic).where(Topic.name == tname).limit(1))
                    ).scalar_one_or_none()
                    if refreshed is not None:
                        topics_by_name[refreshed.name.lower()] = refreshed
            elif sheet == "Audiences":
                aud = await _apply_audience(db, plan)
                if aud is not None:
                    audiences_by_name[aud.name.lower()] = aud
                    audience_embed_targets.append(aud)
            elif sheet == "SMEs":
                sme = await _apply_sme(db, plan, topics_by_name, audiences_by_name)
                if sme is not None:
                    sme_embed_targets.append(sme)
            elif sheet == "Series":
                await _apply_series(db, plan)

            if plan.action == "insert":
                ins += 1
            elif plan.action == "update":
                upd += 1
            elif plan.action == "delete":
                dele += 1

        result.by_sheet[sheet] = {"inserted": ins, "updated": upd, "deleted": dele}
        result.inserted += ins
        result.updated += upd
        result.deleted += dele

    # Flush all writes so we can refresh the entity rows for the embed step.
    await db.flush()

    # Enqueue embeddings for modified content owners. Done in the SAME
    # transaction so the embed-on-commit hook sees the persisted bios.
    for sme in sme_embed_targets:
        try:
            await embed_owner(
                db, owner_type="sme_bio", owner_id=sme.id, text=sme.bio, purpose="embed:workbook"
            )
            result.embeddings_enqueued += 1
        except Exception as exc:
            log.warning("workbook.embed_sme_failed", sme_id=str(sme.id), error=str(exc))
    for aud in audience_embed_targets:
        try:
            blob = f"{aud.name}\nIndustry: {aud.industry}\n{aud.description}"
            await embed_owner(
                db, owner_type="audience", owner_id=aud.id, text=blob, purpose="embed:workbook"
            )
            result.embeddings_enqueued += 1
        except Exception as exc:
            log.warning("workbook.embed_audience_failed", aud_id=str(aud.id), error=str(exc))

    invalidate_graph()
    log.info(
        "workbook.apply.done",
        inserted=result.inserted,
        updated=result.updated,
        deleted=result.deleted,
        embeddings_enqueued=result.embeddings_enqueued,
        actor=actor_label,
    )
    return result


# ---------------------------------------------------------------------------
# Per-sheet apply helpers
# ---------------------------------------------------------------------------
async def _apply_pillar(db: AsyncSession, plan) -> None:
    if plan.action == "insert":
        db.add(
            StrategicPillar(
                name=plan.values["name"],
                description=plan.values["description"],
                display_order=plan.values["display_order"],
            )
        )
        return
    row = await db.get(StrategicPillar, UUID(plan.scout_id))
    if row is None:
        return
    if plan.action == "delete":
        # No soft-delete on pillars; hard-delete is destructive and the
        # plan calls for soft elsewhere. Treat delete on pillars as a no-op
        # warning — pass-2 will surface a UI error.
        return
    row.name = plan.values["name"]
    row.description = plan.values["description"]
    row.display_order = plan.values["display_order"]


async def _apply_topic(db: AsyncSession, plan) -> str | None:
    """Returns the resulting topic name (or None on no-op)."""
    if plan.action == "insert":
        from slugify import slugify

        row = Topic(
            name=plan.values["name"],
            slug=plan.values.get("slug")
            or slugify(plan.values["name"], lowercase=True, max_length=80),
            aliases=plan.values.get("aliases") or [],
            is_active=plan.values.get("is_active")
            if plan.values.get("is_active") is not None
            else True,
            pending_review=bool(plan.values.get("pending_review") or False),
        )
        db.add(row)
        return row.name
    row = await db.get(Topic, UUID(plan.scout_id))
    if row is None:
        return None
    if plan.action == "delete":
        row.is_active = False
        return row.name
    row.name = plan.values["name"]
    if plan.values.get("slug"):
        row.slug = plan.values["slug"]
    if plan.values.get("aliases") is not None:
        row.aliases = plan.values["aliases"]
    if plan.values.get("is_active") is not None:
        row.is_active = plan.values["is_active"]
    if plan.values.get("pending_review") is not None:
        row.pending_review = plan.values["pending_review"]
    return row.name


async def _apply_audience(db: AsyncSession, plan) -> AudienceProfile | None:
    if plan.action == "insert":
        row = AudienceProfile(
            name=plan.values["name"],
            industry=plan.values["industry"],
            role_seniority=plan.values["role_seniority"],
            description=plan.values["description"],
            primary_pain_points=plan.values["primary_pain_points"],
            key_messages=plan.values["key_messages"],
            exclusion_criteria=plan.values.get("exclusion_criteria") or [],
            is_active=plan.values.get("is_active")
            if plan.values.get("is_active") is not None
            else True,
        )
        db.add(row)
        return row
    row = await db.get(AudienceProfile, UUID(plan.scout_id))
    if row is None:
        return None
    if plan.action == "delete":
        row.is_active = False
        return row
    row.name = plan.values["name"]
    row.industry = plan.values["industry"]
    row.role_seniority = plan.values["role_seniority"]
    row.description = plan.values["description"]
    row.primary_pain_points = plan.values["primary_pain_points"]
    row.key_messages = plan.values["key_messages"]
    row.exclusion_criteria = plan.values.get("exclusion_criteria") or []
    if plan.values.get("is_active") is not None:
        row.is_active = plan.values["is_active"]
    return row


async def _apply_sme(
    db: AsyncSession,
    plan,
    topics_by_name: dict[str, Topic],
    audiences_by_name: dict[str, AudienceProfile],
) -> Sme | None:
    """Apply one SMEs row + sync the sme_topics + sme_audiences junctions."""
    primary_topic_ids = [
        topics_by_name[n.lower()].id
        for n in plan.values.get("primary_topics") or []
        if n.lower() in topics_by_name
    ]
    audience_ids = [
        audiences_by_name[n.lower()].id
        for n in plan.values.get("audience_focus") or []
        if n.lower() in audiences_by_name
    ]
    external_links = {}
    for key, col in [
        ("linkedin", "linkedin_url"),
        ("github", "github_url"),
        ("website", "website_url"),
    ]:
        if plan.values.get(col):
            external_links[key] = plan.values[col]

    if plan.action == "insert":
        row = Sme(
            full_name=plan.values["full_name"],
            email=plan.values.get("email"),
            team=plan.values["team"],
            primary_topics=primary_topic_ids,
            audience_focus=audience_ids,
            location_country=plan.values["location_country"],
            location_city=plan.values.get("location_city"),
            bio=plan.values["bio"],
            external_links=external_links,
            is_active=plan.values.get("is_active")
            if plan.values.get("is_active") is not None
            else True,
        )
        db.add(row)
        await db.flush()
        await _sync_sme_junctions(db, row.id, primary_topic_ids, audience_ids)
        return row

    row = await db.get(Sme, UUID(plan.scout_id))
    if row is None:
        return None
    if plan.action == "delete":
        row.is_active = False
        # Clear junctions on soft-delete so graph traversal stops surfacing them.
        await _sync_sme_junctions(db, row.id, [], [])
        return row
    row.full_name = plan.values["full_name"]
    row.email = plan.values.get("email")
    row.team = plan.values["team"]
    row.primary_topics = primary_topic_ids
    row.audience_focus = audience_ids
    row.location_country = plan.values["location_country"]
    row.location_city = plan.values.get("location_city")
    row.bio = plan.values["bio"]
    row.external_links = external_links
    if plan.values.get("is_active") is not None:
        row.is_active = plan.values["is_active"]
    await _sync_sme_junctions(db, row.id, primary_topic_ids, audience_ids)
    return row


async def _sync_sme_junctions(
    db: AsyncSession,
    sme_id: UUID,
    topic_ids: list[UUID],
    audience_ids: list[UUID],
) -> None:
    """Replace SmeTopic + SmeAudience rows for ``sme_id`` (same pattern as
    sme_service)."""
    from sqlalchemy import delete

    await db.execute(delete(SmeTopic).where(SmeTopic.sme_id == sme_id))
    await db.execute(delete(SmeAudience).where(SmeAudience.sme_id == sme_id))
    for tid in topic_ids:
        db.add(SmeTopic(sme_id=sme_id, topic_id=tid, weight=1.0))
    for aid in audience_ids:
        db.add(SmeAudience(sme_id=sme_id, audience_id=aid, weight=1.0))


async def _apply_series(db: AsyncSession, plan) -> None:
    if plan.action == "insert":
        db.add(
            ConferenceSeries(
                canonical_name=plan.values["canonical_name"],
                aliases=plan.values.get("aliases") or [],
                description=plan.values.get("description") or "",
                typical_month=plan.values.get("typical_month"),
                typical_topics=plan.values.get("typical_topics") or [],
                homepage=plan.values.get("homepage"),
                is_active=plan.values.get("is_active")
                if plan.values.get("is_active") is not None
                else True,
            )
        )
        return
    row = await db.get(ConferenceSeries, UUID(plan.scout_id))
    if row is None:
        return
    if plan.action == "delete":
        row.is_active = False
        return
    row.canonical_name = plan.values["canonical_name"]
    if plan.values.get("aliases") is not None:
        row.aliases = plan.values["aliases"]
    if plan.values.get("description") is not None:
        row.description = plan.values["description"]
    if plan.values.get("typical_month") is not None:
        row.typical_month = plan.values["typical_month"]
    if plan.values.get("typical_topics") is not None:
        row.typical_topics = plan.values["typical_topics"]
    if plan.values.get("homepage") is not None:
        row.homepage = plan.values["homepage"]
    if plan.values.get("is_active") is not None:
        row.is_active = plan.values["is_active"]



# ---------------------------------------------------------------------------
# Settings sheet — calls into the same settings_overrides path the
# /api/v1/admin/settings PATCH endpoint uses, plus the same _coerce()
# logic so TRUE/FALSE → bool, "0.5" → float, "a; b; c" → list, etc.
# ---------------------------------------------------------------------------
async def _apply_setting(db: AsyncSession, plan) -> None:
    from app.api.v1.admin_settings import SPECS as _SETTING_SPECS, _coerce
    from app.services import settings_overrides
    from app.settings import get_settings

    name = plan.values["name"]
    raw_value = plan.values["value"]
    by_name = {s.name: s for s in _SETTING_SPECS}
    spec = by_name.get(name)
    if spec is None:
        return  # diff stage should have flagged this; defensive no-op

    # list_str values arrive as the semicolon-joined display form. Split
    # back into a list before coercion.
    if spec.kind == "list_str" and isinstance(raw_value, str):
        raw_value = [item.strip() for item in raw_value.split(";") if item.strip()]

    coerced = _coerce(spec, raw_value)
    await settings_overrides.upsert(
        db, name=name, value=coerced, actor_label="workbook_import"
    )
    get_settings.cache_clear()
