"""Every route hanging off a conference.

WHAT THIS DOES
    The dashboard list and its stats cards, creating one by hand, the
    duplicate report, the decision write path, the detail page and its
    sub-resources, the series endpoints, and the participation record —
    who went, what it cost, what came back.

HOW IT CONNECTS
    Calls       services/conferences.py, services/matcher.py,
                services/extraction.py, services/records.py
    Serves      /api/v1/conferences*, /api/v1/conference-series*,
                /api/v1/participation*

WORTH KNOWING
    REGISTRATION ORDER IS LOAD-BEARING. ``/stats`` and ``/duplicates`` are
    registered before ``/{conference_id}``; the other way round, the path
    parameter swallows them and both endpoints 404 with a UUID parse
    error. The combine block at the bottom of this file is the only thing
    holding that order, so do not sort it.

    ``status`` is not editable through PATCH — it is a decision, and
    decisions go through /decisions so they get a Decision row and an
    audit entry rather than being quietly overwritten.

    Route paths did not change in this merge. ``apps/web/e2e/
    api-contract.spec.ts`` fetches the live schema and asserts every path
    the SPA calls still resolves.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from itertools import combinations
from typing import Literal
from uuid import UUID

import structlog
from fastapi import APIRouter, HTTPException, Query, Response, UploadFile, status
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError

from app.db.models import (
    Conference,
    ConferenceSeries,
    ConferenceSource,
    Decision,
    Match,
    Participation,
    RawPage,
    Sme,
)
from app.db.session import DbSession
from app.schemas import (
    AttendanceSummary,
    ParticipationCreate,
    ParticipationRead,
    ParticipationUpdate,
    ReadBase,
)
from app.services import conferences
from app.services import conferences as cs
from app.services.conferences import (
    assign_conference_to_series,
    conference_embed_text,
    create_series,
    deactivate_series,
    duplicate_key,
    is_previously_attended,
    load_attended_names,
    looks_like_duplicate,
    unassign_conference_from_series,
    update_series,
)
from app.services.embeddings import embed_owner
from app.services.extraction import build_slug, find_duplicate, year_for
from app.services.matcher import (
    ALGORITHM_VERSION,
    assign_ranks,
    compute_boosts,
    live_overall_score,
    load_boost_context,
    rank_smes_for_conference,
    rank_talks_for_conference,
    run_fit_match,
    tie_summary,
)
from app.services.records import model_to_audit_dict, write_audit
from app.services.reports import export_rows_to_csv, export_rows_to_xlsx
from app.settings import get_settings

log = structlog.get_logger("scout.api.conferences")


# ---------------------------------------------------------------------------
# Response models for what used to be bare ``dict`` returns.
#
# A route annotated ``-> dict`` publishes ``additionalProperties: true`` in the
# schema, which tells a client precisely nothing. The SPA responded the only
# way it could: by hand-writing 25 type names for shapes the server never
# promised, which then drifted silently. These models say what the endpoints
# already return — no payload changed — so the generated client is derived
# from the server instead of guessed at.
# ---------------------------------------------------------------------------


class BoostBreakdownRead(ReadBase):
    """Why the live score differs from the stored blend."""

    cfp_urgency: float
    recency_penalty: float
    series_memory: float
    total: float


class MatchRead(ReadBase):
    id: str
    fit_score: float
    speaker_score: float
    judge_verdict: str | None = None
    judge_reason: str = ""
    overall_score: float
    #: What the matcher stored when it last ran. ``overall_score`` above is
    #: recomputed live, so the two differ whenever a boost input changed
    #: since the last rescore — showing both is what makes that legible.
    overall_score_at_scoring_time: float
    boosts: BoostBreakdownRead
    recommended_sme_ids: list[str] = Field(default_factory=list)
    rationale_text: str | None = None
    computed_at: str | None = None


class ConferenceMatchResponse(ReadBase):
    conference_id: str
    algorithm_version: str
    #: None when the matcher has never scored this conference.
    match: MatchRead | None = None


class SmeDimensionScores(ReadBase):
    #: null = not measured (no tags on one side) — dropped from the
    #: composite and its weight renormalised away. NOT a zero.
    audience_overlap: float | None = None
    bio_similarity: float
    location: float
    past_attendance: float


class SmeBreakdownRead(ReadBase):
    sme_id: str
    full_name: str
    team: str
    location_country: str | None = None
    location_city: str | None = None
    is_external: bool
    dimensions: SmeDimensionScores
    composite: float
    above_gate: bool


class SmeWeights(ReadBase):
    audience: float
    bio: float
    location: float
    past: float


class ConferenceSmesResponse(ReadBase):
    conference_id: str
    gate: float
    #: Sent because a dimension with no measurable input is DROPPED and the
    #: rest renormalised — the numbers only add up if the client can see
    #: which weights actually applied.
    weights: SmeWeights
    above_gate: list[SmeBreakdownRead] = Field(default_factory=list)
    near_misses: list[SmeBreakdownRead] = Field(default_factory=list)


class TalkMatchRead(ReadBase):
    talk_id: str
    title: str
    #: Same top-K-cosine measure as the SME bio dimension, so this number
    #: is comparable to the bio_similarity shown in the SME list.
    similarity: float
    primary_sme_id: str | None = None
    primary_sme_name: str | None = None
    pillar_id: str | None = None
    pillar_name: str | None = None
    review_status: str
    already_submitted: bool
    #: False = the talk has no chunks (embed failed or predates talk
    #: embedding); its 0.0 means "not indexed", not "bad fit".
    has_embedding: bool


class ConferenceTalksResponse(ReadBase):
    conference_id: str
    talks: list[TalkMatchRead] = Field(default_factory=list)


# ==========================================================================
# conferences/_schemas.py
# ==========================================================================


class ConferenceRead(BaseModel):
    model_config = ConfigDict(from_attributes=True, extra="ignore")

    id: UUID
    name: str
    slug: str
    status: str
    event_kind: str = "corporate"
    series_id: UUID | None = None
    assigned_pillar_id: UUID | None = None
    confidence_score: float | None = None
    start_date: str | None = None
    end_date: str | None = None
    location_city: str | None = None
    location_country: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    is_virtual: bool
    website: str | None = None
    cfp_url: str | None = None
    topics: list[str] = []
    cfp_topics_of_interest: list[str] = []
    cfp_close_at: str | None = None

    # These were WRITE-ONLY: accepted by ConferenceCreate, persisted, and
    # then absent from every read. estimated_cost_usd could be filtered on
    # (?max_cost_usd=) but never seen, so the operator filtered against a
    # number they could not inspect. cfp_open_at was worse — cfp_is_open()
    # branches on it, so the open/closed verdict shown on screen depended
    # on a field the client had no way to read or correct.
    description: str | None = None
    venue: str | None = None
    estimated_cost_usd: int | None = None
    acceptance_rate_percent: int | None = None
    cfp_open_at: str | None = None
    cfp_deadlines: list[dict] = []

    # The attended half of the record. Previously reachable only through
    # /attendance, so a list view could not show what an event cost or
    # whether it was judged worth going to.
    spend_usd: int | None = None
    leads_generated: int | None = None
    attendance_verdict: str | None = None
    logistics_travel: str = ""
    logistics_lodging: str = ""
    logistics_booth: str = ""
    logistics_sponsorship: str = ""

    created_at: datetime
    updated_at: datetime


class ConferenceListItem(ConferenceRead):
    """List-row shape — adds matcher scores from the latest match row."""

    overall_score: float | None = None
    fit_score: float | None = None
    speaker_score: float | None = None
    # True when the team has been to this event or another edition of its
    # series — i.e. some conference sharing its series identity has
    # participation rows recorded against it.
    previously_attended: bool = False
    #: Position in the FULL ranked cohort, not in the filtered slice.
    rank: int | None = None
    #: True when another conference shares this rank. The UI should show
    #: these as tied rather than implying an order the scores do not support.
    tied: bool = False


def cfp_is_open(conf: Conference) -> bool:
    """Can we still submit to this one today?

    A recorded close date in the future is the clear case. Failing that, an
    open date already passed with no close date recorded counts as open —
    scrapes often catch the announcement and miss the deadline, and treating
    that as closed would hide conferences we can still apply to.

    Nothing recorded at all is NOT open. Guessing "yes" would put a
    conference in an operator's submit queue on no evidence.
    """
    today = date.today()
    if conf.cfp_close_at is not None:
        return conf.cfp_close_at >= today
    if conf.cfp_open_at is not None:
        return conf.cfp_open_at <= today
    return False


class ConferenceListResponse(BaseModel):
    items: list[ConferenceListItem]
    #: Rows matching the filters — what pagination walks.
    total: int
    page: int
    per_page: int
    #: Size of the ranked cohort the ranks refer to. ``total`` is the slice;
    #: this is what "#7 of 48" counts against, so the UI must use this one.
    ranked_total: int = 0
    #: How many of the cohort share a rank with something else. A large
    #: number is the ranking saying it cannot separate them on the evidence
    #: available (D10) — worth surfacing, not hiding.
    tied_count: int = 0
    distinct_ranks: int = 0


def _validate_kind(v: str) -> str:
    """Reject an event kind the operator has not configured.

    Deliberately names what IS allowed in the error. The old Literal put
    the options in the schema where a client could read them; a runtime
    check has to put them in the message or the 422 is unactionable.
    """
    allowed = get_settings().event_kinds
    if v not in allowed:
        raise ValueError(
            f"{v!r} is not a configured event kind. Configured: "
            f"{sorted(allowed)}. Add it under Settings -> Conferences."
        )
    return v


def kinds_skipping_review() -> frozenset[str]:
    """Kinds created already approved and kept out of the finder.

    Read from settings rather than hardcoded: once an operator can rename
    or remove an event kind, behaviour attached to a specific name has to
    be addressable on its own or it silently detaches from whatever they
    renamed it to.
    """
    return frozenset(get_settings().event_kinds_skipping_review)


class ConferenceCreate(BaseModel):
    """POST /conferences payload. Slug is server-derived from name+year."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    name: str = Field(min_length=2, max_length=200)
    # Validated against settings.event_kinds at request time, not as a
    # Literal. The operator owns this vocabulary now, so it cannot be
    # baked into the type.
    #
    # COST WORTH KNOWING: a Literal also published the allowed values in
    # /api/openapi.json. A runtime check does not, so the generated API
    # docs no longer list them. GET /admin/settings is where a client
    # should read the current vocabulary.
    event_kind: str = "corporate"

    @field_validator("event_kind")
    @classmethod
    def _kind_is_configured(cls, v: str) -> str:
        return _validate_kind(v)

    assigned_pillar_id: UUID | None = None
    start_date: date | None = None
    end_date: date | None = None
    location_city: str | None = Field(default=None, max_length=120)
    location_country: str | None = Field(
        default=None, min_length=2, max_length=2, description="ISO-3166-1 alpha-2."
    )
    is_virtual: bool = False
    venue: str | None = Field(default=None, max_length=200)
    website: str | None = Field(default=None, max_length=2000)
    cfp_url: str | None = Field(default=None, max_length=2000)
    cfp_open_at: date | None = None
    cfp_close_at: date | None = None
    cfp_topics_of_interest: list[str] = Field(default_factory=list, max_length=30)
    topics: list[str] = Field(default_factory=list, max_length=30)
    acceptance_rate_percent: int | None = Field(default=None, ge=0, le=100)
    estimated_cost_usd: int | None = Field(default=None, ge=0, le=100_000)
    actor_label: str = Field(default="manual_entry", max_length=120)


class ConferenceUpdate(BaseModel):
    """PATCH /conferences/{id} payload — correcting a conference.

    Every field is optional, and the route writes only what the caller
    actually sent (``exclude_unset``). That distinction matters: sending
    ``{"venue": "Hall 4"}`` must not blank the dates, while sending
    ``{"venue": null}`` must clear the venue. A model where "absent" and
    "null" mean the same thing cannot express "undo a bad extraction".

    ``status`` is absent on purpose. Changing it is a decision, and
    decisions go through POST /decisions so they produce a Decision row
    and an audit entry. An edit form that could quietly flip an approval
    would be the same defect the decay pass had, with a human driving.

    ``slug`` is absent too — it is derived identity, and rewriting it
    would orphan the dedup key that stops the same conference being
    ingested twice.
    """

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    name: str | None = Field(default=None, min_length=2, max_length=200)
    description: str | None = None
    event_kind: str | None = None

    @field_validator("event_kind")
    @classmethod
    def _kind_is_configured(cls, v: str | None) -> str | None:
        return None if v is None else _validate_kind(v)

    assigned_pillar_id: UUID | None = None
    start_date: date | None = None
    end_date: date | None = None
    location_city: str | None = Field(default=None, max_length=120)
    location_country: str | None = Field(default=None, min_length=2, max_length=2)
    is_virtual: bool | None = None
    venue: str | None = Field(default=None, max_length=200)
    website: str | None = Field(default=None, max_length=2000)
    cfp_url: str | None = Field(default=None, max_length=2000)
    cfp_open_at: date | None = None
    cfp_close_at: date | None = None
    cfp_topics_of_interest: list[str] | None = Field(default=None, max_length=30)
    topics: list[str] | None = Field(default=None, max_length=30)
    acceptance_rate_percent: int | None = Field(default=None, ge=0, le=100)
    estimated_cost_usd: int | None = Field(default=None, ge=0, le=100_000)

    # Trip logistics. Free text — "flights booked, Anna has the
    # confirmation" is the real shape of this, and a structured travel
    # model would be a guess at a workflow nobody described.
    logistics_travel: str | None = None
    logistics_lodging: str | None = None
    logistics_booth: str | None = None
    logistics_sponsorship: str | None = None

    @model_validator(mode="after")
    def _end_cannot_precede_start(self) -> ConferenceUpdate:
        if (
            self.start_date is not None
            and self.end_date is not None
            and self.end_date < self.start_date
        ):
            raise ValueError("end_date cannot be before start_date")
        return self


class ConferenceCreateResponse(BaseModel):
    """Return shape for POST /conferences — the new row plus the matcher
    verdict from the auto-run that fires right after the insert commit."""

    conference: ConferenceRead
    match: dict | None = None
    match_error: str | None = None


class DecisionCreate(BaseModel):
    """POST /conferences/{id}/decisions payload."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    decision: Literal["approved", "rejected", "needs_review"]
    reason: str | None = Field(default=None, max_length=2000)
    decided_by_label: str = Field(default="anonymous", max_length=120)


class DecisionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True, extra="ignore")

    id: UUID
    conference_id: UUID
    decision: str
    reason: str | None
    decided_by_label: str
    decided_at: datetime
    created_at: datetime


class StatsCard(BaseModel):
    upcoming_approved: int
    pending_review: int
    cfp_closing_soon: int
    low_coverage_smes: int


class TopConferenceSummary(BaseModel):
    id: UUID
    name: str
    slug: str
    status: str
    overall_score: float | None
    start_date: str | None


class DashboardStats(BaseModel):
    cards: StatsCard
    top_conferences: list[TopConferenceSummary]


def to_read(row: Conference) -> ConferenceRead:
    return ConferenceRead(
        id=row.id,
        name=row.name,
        slug=row.slug,
        status=row.status,
        event_kind=row.event_kind,
        series_id=row.series_id,
        assigned_pillar_id=row.assigned_pillar_id,
        confidence_score=row.confidence_score,
        start_date=row.start_date.isoformat() if row.start_date else None,
        end_date=row.end_date.isoformat() if row.end_date else None,
        location_city=row.location_city,
        location_country=row.location_country,
        is_virtual=row.is_virtual,
        website=row.website,
        cfp_url=row.cfp_url,
        topics=list(row.topics or []),
        cfp_topics_of_interest=list(row.cfp_topics_of_interest or []),
        cfp_close_at=row.cfp_close_at.isoformat() if row.cfp_close_at else None,
        description=row.description,
        venue=row.venue,
        estimated_cost_usd=row.estimated_cost_usd,
        acceptance_rate_percent=row.acceptance_rate_percent,
        cfp_open_at=row.cfp_open_at.isoformat() if row.cfp_open_at else None,
        cfp_deadlines=list(row.cfp_deadlines or []),
        spend_usd=row.spend_usd,
        leads_generated=row.leads_generated,
        attendance_verdict=row.attendance_verdict,
        logistics_travel=row.logistics_travel,
        logistics_lodging=row.logistics_lodging,
        logistics_booth=row.logistics_booth,
        logistics_sponsorship=row.logistics_sponsorship,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


# ==========================================================================
# conferences/stats.py
# ==========================================================================


_r_stats = APIRouter(prefix="/api/v1/conferences", tags=["conferences"])


@_r_stats.get("/stats/by-location")
async def stats_by_location(db: DbSession) -> dict:
    """Geocoded conferences for the dashboard map.

    Returns one item per conference with non-null lat/lng. The UI clusters
    by (lat, lng) to draw a single dot per city; clicking it shows the
    list of conferences at that point.

    Excludes virtual events (they have no physical location) and
    quarantined / rejected conferences (clutter, not actionable).

    Tags each conference with ``attendance_status``:
      - ``planned``  → status is ``approved``, or operator's decisions
        table has an ``approved`` decision for this conference
      - ``attended`` → matches a conference the team recorded attendance at
        (same event or same franchise — see ``services/conferences/series_identity.py``)
      - ``new``      → none of the above; we have no history with this
        series
    """

    attended_names = await load_attended_names(db)

    # Set of conference IDs the operator has approved in app.decisions.
    # Cheap: one query for the small decisions set.
    approved_ids = set(
        (await db.execute(select(Decision.conference_id).where(Decision.decision == "approved")))
        .scalars()
        .all()
    )

    rows = (
        await db.execute(
            select(
                Conference.id,
                Conference.name,
                Conference.location_city,
                Conference.location_country,
                Conference.latitude,
                Conference.longitude,
                Conference.status,
                Conference.start_date,
            )
            .where(Conference.latitude.is_not(None))
            .where(Conference.longitude.is_not(None))
            .where(Conference.is_virtual.is_(False))
            .where(Conference.status.not_in(list(cs.HIDDEN_FROM_FINDER)))
        )
    ).all()

    def _status_of(conf_id, conf_name: str, conf_status: str) -> str:
        # planned wins over attended wins over new — strongest first.
        if conf_status == "approved" or conf_id in approved_ids:
            return "planned"
        if is_previously_attended(conf_name, attended_names):
            return "attended"
        return "new"

    return {
        "items": [
            {
                "id": str(r.id),
                "name": r.name,
                "city": r.location_city,
                "country": r.location_country,
                "lat": float(r.latitude),
                "lng": float(r.longitude),
                "status": r.status,
                "start_date": r.start_date.isoformat() if r.start_date else None,
                "attendance_status": _status_of(r.id, r.name, r.status),
            }
            for r in rows
        ]
    }


@_r_stats.get("/stats/dashboard", response_model=DashboardStats)
async def dashboard_stats(db: DbSession) -> DashboardStats:
    """Aggregates the four headline numbers + top-N conferences for the
    dashboard. Bounded; single round-trip per card to keep this snappy."""
    today = date.today()
    next_90 = today + timedelta(days=90)
    next_30 = today + timedelta(days=30)

    upcoming_approved = (
        await db.execute(
            select(func.count(Conference.id))
            .where(Conference.status == "approved")
            .where(Conference.start_date.is_not(None))
            .where(Conference.start_date.between(today, next_90))
        )
    ).scalar_one()

    pending_review = (
        await db.execute(
            select(func.count(Conference.id)).where(
                Conference.status.in_(
                    [
                        "needs_review",
                        "needs_review_pillar",
                        "needs_sme_review",
                    ]
                )
            )
        )
    ).scalar_one()

    cfp_closing_soon = (
        await db.execute(
            select(func.count(Conference.id))
            .where(Conference.cfp_close_at.is_not(None))
            .where(Conference.cfp_close_at.between(today, next_30))
            .where(Conference.status != "quarantined")
        )
    ).scalar_one()

    # "Low coverage" SME = active SME with no expertise text OR empty
    # audience_focus. A cheap proxy for coverage, not a precise measure.

    low_coverage_smes = (
        await db.execute(
            select(func.count(Sme.id))
            .where(Sme.is_active.is_(True))
            .where(
                (func.length(func.trim(Sme.expertise)) == 0)
                | (func.array_length(Sme.audience_focus, 1).is_(None))
            )
        )
    ).scalar_one()

    # Top conferences for the dashboard card. Ordered by the LIVE score,
    # not the persisted one: a thumbs-up changes a boost, and the card must
    # agree with the list the operator clicks through to.
    #
    # SQL cannot rank on it — the boosts depend on today's date and current
    # verdicts — so the candidates come back ordered by the stored score as
    # a cheap prefilter, then get rescored and re-sorted in Python. The
    # prefilter takes more than 5 so a conference lifted by a fresh boost
    # can still reach the card.
    candidate_rows = (
        await db.execute(
            select(Conference, Match)
            .outerjoin(
                Match,
                (Match.conference_id == Conference.id)
                & (Match.algorithm_version == ALGORITHM_VERSION),
            )
            .where(Conference.status.not_in(list(cs.HIDDEN_FROM_FINDER)))
            .order_by(Match.overall_score.desc().nullslast())
            .limit(40)
        )
    ).all()

    dash_settings = get_settings()
    dash_ctx = await load_boost_context(db)
    scored_top: list[tuple[float | None, Conference]] = []
    for c, m in candidate_rows:
        live = (
            await live_overall_score(
                db=db,
                conference=c,
                fit=m.fit_score,
                speakers=m.speaker_score,
                settings=dash_settings,
                context=dash_ctx,
            )
            if m is not None
            else None
        )
        scored_top.append((live, c))
    scored_top.sort(key=lambda p: (p[0] is None, -(p[0] or 0.0)))

    top = [
        TopConferenceSummary(
            id=c.id,
            name=c.name,
            slug=c.slug,
            status=c.status,
            overall_score=live,
            start_date=c.start_date.isoformat() if c.start_date else None,
        )
        for live, c in scored_top[:5]
    ]

    return DashboardStats(
        cards=StatsCard(
            upcoming_approved=int(upcoming_approved),
            pending_review=int(pending_review),
            cfp_closing_soon=int(cfp_closing_soon),
            low_coverage_smes=int(low_coverage_smes),
        ),
        top_conferences=top,
    )


# ==========================================================================
# conferences/duplicates.py
# ==========================================================================


_r_duplicates = APIRouter(prefix="/api/v1/conferences", tags=["conferences"])


class DuplicateMember(BaseModel):
    id: str
    name: str
    slug: str
    status: str
    start_date: str | None = None
    location_country: str | None = None


class DuplicatePair(BaseModel):
    """Two conferences that may be the same event. Advisory only."""

    key: str
    left: DuplicateMember
    right: DuplicateMember


class DuplicatesResponse(BaseModel):
    pairs: list[DuplicatePair]
    #: Conferences compared. Useful for telling "none found" apart from
    #: "nothing to compare".
    scanned: int


def _member(c: Conference) -> DuplicateMember:
    return DuplicateMember(
        id=str(c.id),
        name=c.name,
        slug=c.slug,
        status=c.status,
        start_date=c.start_date.isoformat() if c.start_date else None,
        location_country=c.location_country,
    )


@_r_duplicates.get("/duplicates", response_model=DuplicatesResponse)
async def list_possible_duplicates(
    db: DbSession,
    limit: int = Query(default=200, ge=1, le=1000),
) -> DuplicatesResponse:
    """Pairs worth a human look. Read-only — nothing is merged."""
    rows = (await db.execute(select(Conference))).scalars().all()

    # Only compare conferences in the same year. Different years of one
    # event are SEPARATE conferences on purpose — that is what makes "we
    # attended this last year" meaningful — so pairing them would flood
    # the list with things nobody should merge.
    pairs: list[DuplicatePair] = []
    for a, b in combinations(rows, 2):
        ya = a.start_date.year if a.start_date else None
        yb = b.start_date.year if b.start_date else None
        if ya is not None and yb is not None and ya != yb:
            continue
        if not looks_like_duplicate(a.name, b.name):
            continue
        pairs.append(DuplicatePair(key=duplicate_key(a.name), left=_member(a), right=_member(b)))
        if len(pairs) >= limit:
            break

    log.info("conferences.duplicates.scanned", scanned=len(rows), pairs=len(pairs))
    return DuplicatesResponse(pairs=pairs, scanned=len(rows))


# ==========================================================================
# conferences/create.py
# ==========================================================================


_r_create = APIRouter(prefix="/api/v1/conferences", tags=["conferences"])


@_r_create.post("", response_model=ConferenceCreateResponse, status_code=status.HTTP_201_CREATED)
async def create_conference(
    db: DbSession,
    payload: ConferenceCreate,
) -> ConferenceCreateResponse:
    """Manually add a conference + immediately run the matcher.

    Slug is derived from ``name + year`` server-side (mirrors the extraction
    pipeline's dedup contract). 409 if a conference with the same slug
    already exists. `confidence_score=1.0` for manual entries since a human
    just vouched for them; the matcher will set ``status`` based on its
    gates.

    Returns as soon as the row and its embedding exist — scoring happens
    when the detail page loads (GET /{id}/match auto-runs the matcher
    behind a skeleton). ``match`` in the response is therefore always
    None; it is kept for shape stability.
    """

    slug = build_slug(payload.name, year_for(payload.start_date))
    existing = await find_duplicate(db, slug=slug)
    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"Conference with slug '{slug}' already exists "
                f"(id={existing.id}). Open it instead of recreating."
            ),
        )

    # Grassroot events are immediately approved; skip matcher gates
    initial_status = "approved" if payload.event_kind in kinds_skipping_review() else "discovered"

    conf = Conference(
        name=payload.name,
        slug=slug,
        event_kind=payload.event_kind,
        assigned_pillar_id=payload.assigned_pillar_id,
        start_date=payload.start_date,
        end_date=payload.end_date,
        location_city=payload.location_city,
        location_country=payload.location_country,
        is_virtual=payload.is_virtual,
        venue=payload.venue,
        website=payload.website,
        cfp_url=payload.cfp_url,
        cfp_open_at=payload.cfp_open_at,
        cfp_close_at=payload.cfp_close_at,
        cfp_topics_of_interest=list(payload.cfp_topics_of_interest),
        cfp_deadlines=[],
        topics=list(payload.topics),
        acceptance_rate_percent=payload.acceptance_rate_percent,
        estimated_cost_usd=payload.estimated_cost_usd,
        confidence_score=1.0,
        status=initial_status,
    )
    db.add(conf)
    try:
        await db.flush()
    except IntegrityError as exc:
        await db.rollback()
        # Static message on purpose. `exc.orig` is asyncpg's error, whose
        # str() includes `DETAIL: Key (...)=(...)` — i.e. the failing row's
        # column values — which this used to interpolate straight into the
        # response body. Every other IntegrityError site in the codebase
        # already used a safe message; this was the outlier.
        log.warning("conference.create.integrity_error", error_type=type(exc).__name__)
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "A conference with this slug already exists, or a referenced record is missing."
            ),
        ) from exc

    await write_audit(
        db,
        action="conference.manual_create",
        target_type="conference",
        target_id=conf.id,
        before=None,
        after=model_to_audit_dict(conf),
        actor_label=payload.actor_label,
    )
    await db.commit()

    # Embed the conference's structural blob synchronously so the matcher's
    # the matcher has a chunk to compare messaging documents against. Without
    # this, manually-created conferences always score 0 on messaging /
    # pillar because the embed-on-extract path that the scraper relies
    # on never runs for them. Mirrors the same code in
    # services/extraction.py.
    try:
        blob = conference_embed_text(conf)
        if blob:
            await embed_owner(
                db,
                owner_type="conference",
                owner_id=conf.id,
                text=blob,
                purpose="embed:conference",
            )
            await db.commit()
    except Exception as exc:
        log.warning(
            "conference.manual_create.embed_failed",
            conference_id=str(conf.id),
            error=str(exc),
        )

    log.info(
        "conference.manual_create",
        conference_id=str(conf.id),
        slug=conf.slug,
        actor_label=payload.actor_label,
    )

    # The matcher used to run INLINE here, which held the request open for
    # ~16 seconds against a live LLM — the user sat on a frozen dialog while
    # the score computed. It is not run here at all now: the detail page's
    # /match endpoint already auto-runs the matcher on first view behind a
    # loading skeleton (its docstring calls the page self-sufficient), and
    # the create dialog always navigates there on success. Enqueuing a
    # background run here as well would just race that auto-run and pay for
    # the same LLM calls twice.
    match_error: str | None = None
    if payload.event_kind in kinds_skipping_review():
        match_error = "skipped: grassroot events do not require matcher scoring"

    return ConferenceCreateResponse(
        conference=to_read(conf),
        match=None,
        match_error=match_error,
    )


# ==========================================================================
# conferences/listing.py
# ==========================================================================


_r_listing = APIRouter(prefix="/api/v1/conferences", tags=["conferences"])


@_r_listing.get("", response_model=ConferenceListResponse)
async def list_conferences(
    db: DbSession,
    page: int = Query(default=1, ge=1),
    per_page: int = Query(default=50, ge=1, le=200),
    status_in: list[str] | None = Query(default=None, alias="status"),
    sort: Literal["score", "fit", "speakers", "date", "name", "cfp_close"] = Query(
        default="score",
    ),
    then_by: Literal["score", "fit", "speakers", "date", "name", "cfp_close"] | None = Query(
        default=None,
        description=(
            "Secondary sort key — breaks ties the primary `sort` leaves. "
            "Most useful behind a date key: sort=cfp_close&then_by=fit is "
            "'soonest deadline first, best fit within each day'."
        ),
    ),
    attendance_filter: Literal["all", "new", "returning"] = Query(
        default="all",
        description=(
            "Filter by past-attendance status: 'all' (default), 'new' "
            "(conferences whose normalized name doesn't match any "
            "conference somebody was recorded against), 'returning' "
            "(conferences whose normalized name DOES match a past-attended "
            "edition)."
        ),
    ),
    exclude_grassroot: bool = Query(
        default=True,
        description="Exclude grassroot/owned events from the finder. Default true.",
    ),
    event_kind: list[str] | None = Query(default=None),
    # --- slice filters: predicates over the ranked list, NOT cohort
    # filters. Applied after ranking so a filtered view keeps the global
    # rank — the best conference in Germany is "#7 overall", not "#1".
    country: list[str] | None = Query(
        default=None,
        description="ISO-3166-1 alpha-2 codes. Multiple allowed (OR).",
    ),
    city: str | None = Query(default=None, description="Case-insensitive substring."),
    starts_after: date | None = Query(default=None),
    starts_before: date | None = Query(default=None),
    cfp_open: bool | None = Query(
        default=None,
        description=(
            "True keeps only conferences whose CFP is open today — a close "
            "date in the future, or an open date already passed with no "
            "close date recorded."
        ),
    ),
    cfp_closes_within_days: int | None = Query(
        default=None,
        ge=1,
        le=365,
        description=(
            "Keep only conferences whose CFP close date falls between today "
            "and N days from now. Drops conferences with no recorded close "
            "date — an unknown deadline cannot satisfy a deadline window. "
            "Combines with sort=fit for 'best fits I can still submit to "
            "this month'."
        ),
    ),
    engagement: Literal["all", "going", "attended", "none"] = Query(
        default="all",
        description=(
            "Our own involvement, as opposed to attendance_filter which is "
            "about the event's history. 'going' has participation recorded, "
            "'attended' has an outcome recorded, 'none' is neither."
        ),
    ),
    include_closed_cfp: bool = Query(
        default=False,
        description=(
            "False (the default) hides conferences whose CFP has already "
            "closed — more than half the discovered corpus — UNLESS we are "
            "going to them or have been. A closed CFP we have no stake in is "
            "not actionable, and burying the actionable ones under it is how "
            "the list stops being useful."
        ),
    ),
    max_cost_usd: int | None = Query(
        default=None,
        ge=0,
        description="Keep conferences with no cost estimate, or one at or below this.",
    ),
    include_virtual: bool = Query(
        default=True,
        description="False drops virtual events — they cannot be filtered by geography.",
    ),
) -> ConferenceListResponse:
    """List conferences. Default excludes quarantined rows so the dashboard
    doesn't show them. Pass ``?status=quarantined`` (multi-OK) to opt in.

    LEFT JOINs the latest matches row (by algorithm_version) so the list
    can render scores without an N+1 round-trip.

    Tags each item with ``previously_attended`` based on a normalized-name
    match against conferences that have participation rows recorded
    against them. The ``attendance_filter`` query parameter narrows the
    result set by that flag.
    """

    settings = get_settings()
    attended_names = await load_attended_names(db)

    # Our own involvement, in two cheap set queries rather than per-row
    # lookups: which conferences have anyone recorded against them, and
    # which have an outcome written. Used by ``engagement`` and to decide
    # whether a closed CFP is still worth showing.
    going_ids: set[UUID] = set(
        (await db.execute(select(Participation.conference_id).distinct())).scalars().all()
    )
    attended_ids: set[UUID] = set(
        (
            await db.execute(
                select(Conference.id).where(
                    or_(
                        Conference.attendance_verdict.is_not(None),
                        Conference.spend_usd.is_not(None),
                        Conference.leads_generated.is_not(None),
                    )
                )
            )
        )
        .scalars()
        .all()
    )
    # Single-load of boost state — verdicts, approved series — used
    # below to recompute overall_score live so verdict edits take
    # effect on the next render without a rescore.
    boost_ctx = await load_boost_context(db)

    stmt = select(Conference, Match).outerjoin(
        Match,
        (Match.conference_id == Conference.id) & (Match.algorithm_version == ALGORITHM_VERSION),
    )
    if status_in:
        stmt = stmt.where(Conference.status.in_(status_in))
    else:
        stmt = stmt.where(Conference.status.not_in(list(cs.HIDDEN_FROM_FINDER)))

    if exclude_grassroot:
        stmt = stmt.where(Conference.event_kind.not_in(kinds_skipping_review()))
    if event_kind:
        stmt = stmt.where(Conference.event_kind.in_(event_kind))

    # SQL-level sort kicks in below ONLY for non-overall sorts.
    # ``score`` sort uses live-computed overall (so verdict changes
    # reorder the list instantly without persisting overall_score).
    # ``date`` / ``name`` / per-signal sorts use SQL ORDER BY since
    # the column is stable / doesn't depend on verdict state.
    if sort == "fit":
        stmt = stmt.order_by(
            Match.fit_score.desc().nullslast(),
            Conference.start_date.asc().nullslast(),
        )
    elif sort == "speakers":
        stmt = stmt.order_by(
            Match.speaker_score.desc().nullslast(),
            Conference.start_date.asc().nullslast(),
        )
    elif sort == "date":
        stmt = stmt.order_by(
            Conference.start_date.asc().nullslast(),
            Match.overall_score.desc().nullslast(),
        )
    elif sort == "name":
        stmt = stmt.order_by(Conference.name.asc())
    else:
        # sort == "score". The ordering itself is computed in Python from
        # the live overall, but this query still needs a DETERMINISTIC
        # order: assign_ranks preserves input order inside a tie group, so
        # whatever Postgres hands back decides how tied conferences are
        # displayed and paginated.
        #
        # Without this there was no ORDER BY at all (under a comment saying
        # there was). Postgres is free to return rows differently on each
        # call, so a paginated list could drop and repeat rows between
        # pages and tied conferences reshuffled on refresh.
        #
        # start_date first because "soonest" is the useful tie-break; id
        # last because it is the only column guaranteed to be unique.
        stmt = stmt.order_by(
            Conference.start_date.asc().nullslast(),
            Conference.id.asc(),
        )

    # Past-attendance filtering happens in Python because the
    # comparison key is a normalized name (year/edition stripped),
    # not a column we can directly WHERE on. The candidate set is
    # already small after status filter so over-fetch + filter
    # in-app is fine. We still cap total to keep pagination math
    # honest.
    all_rows = (await db.execute(stmt)).all()
    # Recompute overall_score LIVE using the stored signals +
    # current verdicts. This is what makes verdict edits instant —
    # the operator clicks a thumb, the verdict commits to past_
    # conferences, the next list render reads the new verdict via
    # ``boost_ctx`` and re-orders without any LLM call.
    enriched: list[tuple[Conference, Match | None, float | None]] = []
    for conf, match in all_rows:
        if match is None:
            enriched.append((conf, None, None))
            continue
        live_overall = await live_overall_score(
            db=db,
            conference=conf,
            fit=match.fit_score,
            speakers=match.speaker_score,
            settings=settings,
            context=boost_ctx,
        )
        enriched.append((conf, match, live_overall))

    # ---- Rank the WHOLE cohort, once (D11) --------------------------
    # Every filter below is a predicate over this ranked list, never a
    # change to what gets ranked. That is what makes "#7 of 48" mean the
    # same thing on every screen: filter to Germany and the top row is
    # still #7, not a freshly-minted #1.
    #
    # The cohort itself is set by status / event_kind / exclude_grassroot
    # above, which decide what is ELIGIBLE to be ranked at all. Those are
    # genuinely different from "show me a subset of the ranking".
    ranked = assign_ranks([(row, row[2] or 0.0) for row in enriched])
    ties = tie_summary(ranked)

    # ---- Slice ------------------------------------------------------
    def _keep(entry) -> bool:
        conf, _match, _ov = entry.item

        if attendance_filter != "all":
            want = attendance_filter == "returning"
            if is_previously_attended(conf.name, attended_names) != want:
                return False
        if not include_virtual and conf.is_virtual:
            return False
        if country:
            wanted = {c.strip().upper() for c in country if c and c.strip()}
            if wanted and (conf.location_country or "").upper() not in wanted:
                return False
        if city and city.strip().lower() not in (conf.location_city or "").lower():
            return False
        if starts_after and (conf.start_date is None or conf.start_date < starts_after):
            return False
        if starts_before and (conf.start_date is None or conf.start_date > starts_before):
            return False
        if cfp_open is not None and cfp_is_open(conf) != cfp_open:
            return False
        if cfp_closes_within_days is not None:
            if conf.cfp_close_at is None:
                return False
            days_left = (conf.cfp_close_at - date.today()).days
            if days_left < 0 or days_left > cfp_closes_within_days:
                return False
        # A closed CFP is only worth showing if we have a stake in it.
        if (
            not include_closed_cfp
            and not cfp_is_open(conf)
            and conf.cfp_close_at is not None
            and conf.id not in going_ids | attended_ids
        ):
            return False
        if engagement == "going" and conf.id not in going_ids:
            return False
        if engagement == "attended" and conf.id not in attended_ids:
            return False
        if engagement == "none" and conf.id in going_ids | attended_ids:
            return False
        return not (
            max_cost_usd is not None
            and conf.estimated_cost_usd is not None
            and conf.estimated_cost_usd > max_cost_usd
        )

    kept = [r for r in ranked if _keep(r)]

    # ``sort`` reorders what is displayed; it never renumbers. A conference
    # sorted to the top of a date-sorted list keeps whatever rank its score
    # earned. ``then_by`` breaks ties the primary key leaves — date keys tie
    # constantly (same-day deadlines), so "cfp_close then fit" reads as
    # "soonest first, best fit within each day". Score keys are floats and
    # rarely tie, so a secondary behind them mostly documents intent.
    def _sort_key(kind: str):
        if kind == "date":
            return lambda r: r.item[0].start_date or date.max
        if kind == "name":
            return lambda r: (r.item[0].name or "").lower()
        if kind == "cfp_close":
            # Soonest deadline first — the actionable end. No deadline
            # recorded sorts last, which is what `or date.max` buys.
            return lambda r: (
                (
                    r.item[0].cfp_close_at.date()
                    if hasattr(r.item[0].cfp_close_at, "date")
                    else r.item[0].cfp_close_at
                )
                if r.item[0].cfp_close_at
                else date.max
            )
        if kind == "fit":
            return lambda r: -(r.item[1].fit_score if r.item[1] else -1.0)
        if kind == "speakers":
            return lambda r: -(r.item[1].speaker_score if r.item[1] else -1.0)
        # "score" — the live overall, same order the ranks were assigned in.
        return lambda r: -(r.item[2] if r.item[2] is not None else -1.0)

    if sort != "score" or (then_by and then_by != sort):
        keys = [_sort_key(sort)]
        if then_by and then_by != sort:
            keys.append(_sort_key(then_by))
        kept.sort(key=lambda r: tuple(k(r) for k in keys))
    # sort == "score" with no secondary is already the ranked order.

    total = len(kept)
    page_rows = kept[(page - 1) * per_page : page * per_page]

    items: list[ConferenceListItem] = []
    for entry in page_rows:
        conf, match, live_overall = entry.item
        base = to_read(conf).model_dump()
        items.append(
            ConferenceListItem(
                **base,
                overall_score=live_overall,
                fit_score=float(match.fit_score) if match else None,
                speaker_score=float(match.speaker_score) if match else None,
                previously_attended=is_previously_attended(conf.name, attended_names),
                rank=entry.rank,
                tied=entry.tied,
            )
        )

    return ConferenceListResponse(
        items=items,
        total=int(total),
        page=page,
        per_page=per_page,
        ranked_total=ties["total"],
        tied_count=ties["tied"],
        distinct_ranks=ties["distinct_ranks"],
    )


class ImportColumnSpec(BaseModel):
    key: str
    label: str
    required: bool
    example: str


class ImportRowResult(BaseModel):
    row: int
    name: str
    outcome: str
    detail: str


class ImportResult(BaseModel):
    total_rows: int
    created: int
    updated_existing: int
    errors: int
    results: list[ImportRowResult]


@_r_listing.get("/import/format", response_model=list[ImportColumnSpec])
async def import_format() -> list[dict]:
    """The import contract, served from the same constant the parser and
    template use — the popup that shows the format can never drift from
    what the importer actually accepts."""
    return cs.IMPORT_COLUMNS


@_r_listing.get("/import/template")
async def import_template() -> Response:
    """Downloadable .xlsx starter: header row + one example row."""
    return Response(
        content=cs.build_import_template(),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={
            "Content-Disposition": 'attachment; filename="scout-past-conferences-template.xlsx"'
        },
    )


@_r_listing.post("/import", response_model=ImportResult)
async def import_past(
    db: DbSession,
    file: UploadFile,
    actor_label: str = Query(default="import"),
) -> dict:
    """Import already-attended conferences from .xlsx/.csv.

    Creates the conference (status=approved — it is history, not a
    candidate), records attendees as attended participation rows linked to
    SME records by name, and stores spend/leads/worth-it. Idempotent by
    slug: re-uploading attaches to existing records instead of duplicating.
    """
    raw = await file.read()
    if len(raw) > 10 * 1024 * 1024:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="File too large (10 MB cap).",
        )
    return await cs.import_past_conferences(
        db, filename=file.filename or "", raw=raw, actor_label=actor_label
    )


@_r_listing.get("/export")
async def export_conferences(
    db: DbSession,
    format: Literal["csv", "xlsx"] = Query(default="xlsx"),
    status_in: list[str] | None = Query(default=None, alias="status"),
    sort: Literal["score", "fit", "speakers", "date", "name", "cfp_close"] = Query(
        default="score",
    ),
    then_by: Literal["score", "fit", "speakers", "date", "name", "cfp_close"] | None = Query(
        default=None
    ),
    attendance_filter: Literal["all", "new", "returning"] = Query(default="all"),
    exclude_grassroot: bool = Query(default=True),
    event_kind: list[str] | None = Query(default=None),
    country: list[str] | None = Query(default=None),
    city: str | None = Query(default=None),
    starts_after: date | None = Query(default=None),
    starts_before: date | None = Query(default=None),
    cfp_open: bool | None = Query(default=None),
    cfp_closes_within_days: int | None = Query(default=None, ge=1, le=365),
    engagement: Literal["all", "going", "attended", "none"] = Query(default="all"),
    include_closed_cfp: bool = Query(default=False),
    max_cost_usd: int | None = Query(default=None, ge=0),
    include_virtual: bool = Query(default=True),
) -> Response:
    """Download the CURRENT filtered view as a spreadsheet.

    Same filter params as the list endpoint, minus pagination — an export
    of a view must contain the whole view, not the page the operator
    happened to be on. Every column ships even when nothing has filled it
    in yet (actual spend, leads, worth-it): the empty columns are the
    to-do list, and the boss's spreadsheet should show what tracking
    exists, not just what has data.
    """
    rows: list[dict] = []
    page_no = 1
    while True:
        batch = await list_conferences(
            db,
            page=page_no,
            per_page=200,
            status_in=status_in,
            sort=sort,
            then_by=then_by,
            attendance_filter=attendance_filter,
            exclude_grassroot=exclude_grassroot,
            event_kind=event_kind,
            country=country,
            city=city,
            starts_after=starts_after,
            starts_before=starts_before,
            cfp_open=cfp_open,
            cfp_closes_within_days=cfp_closes_within_days,
            engagement=engagement,
            include_closed_cfp=include_closed_cfp,
            max_cost_usd=max_cost_usd,
            include_virtual=include_virtual,
        )
        rows.extend(item.model_dump() for item in batch.items)
        if page_no * 200 >= batch.total or not batch.items:
            break
        page_no += 1

    # Fields the list shape doesn't carry, plus who's going. Two grouped
    # queries for the whole export, not per-row lookups.
    ids = [r["id"] for r in rows]
    extras = {
        row.id: row
        for row in (
            (
                await db.execute(
                    select(Conference).where(Conference.id.in_(ids))
                )
            ).scalars()
            if ids
            else []
        )
    }
    going: dict[UUID, list[str]] = {}
    if ids:
        for conf_id, label, activity in (
            await db.execute(
                select(
                    Participation.conference_id,
                    Participation.person_label,
                    Participation.activity,
                ).where(Participation.conference_id.in_(ids))
            )
        ).all():
            going.setdefault(conf_id, []).append(f"{label} ({activity})")

    for r in rows:
        conf = extras.get(r["id"])
        r["attendance_notes"] = conf.attendance_notes if conf else None
        r["audience_size_estimate"] = conf.audience_size_estimate if conf else None
        r["who_is_going"] = "; ".join(going.get(r["id"], []))
        for k in ("created_at", "updated_at"):
            if isinstance(r.get(k), datetime):
                r[k] = r[k].date().isoformat()

    stamp = date.today().isoformat()
    if format == "csv":
        return Response(
            content=export_rows_to_csv(rows),
            media_type="text/csv; charset=utf-8",
            headers={
                "Content-Disposition": f'attachment; filename="scout-conferences-{stamp}.csv"'
            },
        )
    return Response(
        content=export_rows_to_xlsx(rows),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={
            "Content-Disposition": f'attachment; filename="scout-conferences-{stamp}.xlsx"'
        },
    )


# ==========================================================================
# conferences/decisions.py
# ==========================================================================


_r_decisions = APIRouter(prefix="/api/v1/conferences", tags=["conferences"])


@_r_decisions.post(
    "/{conference_id}/decisions",
    response_model=DecisionRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_decision(
    db: DbSession,
    conference_id: UUID,
    payload: DecisionCreate,
) -> DecisionRead:
    """Record an approve / reject / needs_review action on this conference.

    Also bumps ``conferences.status`` to the decision value so the dashboard
    filter reflects the human-in-the-loop verdict. Audit-logged.
    """
    conference = await db.get(Conference, conference_id)
    if conference is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No conference {conference_id}",
        )

    before = model_to_audit_dict(conference)

    decision = Decision(
        conference_id=conference.id,
        decision=payload.decision,
        reason=payload.reason,
        decided_by_label=payload.decided_by_label or "anonymous",
    )
    db.add(decision)
    conference.status = payload.decision
    await db.flush()
    await db.refresh(conference)
    await db.refresh(decision)

    await write_audit(
        db,
        action=f"decision.{payload.decision}",
        target_type="conference",
        target_id=conference.id,
        before=before,
        after=model_to_audit_dict(conference),
        actor_label=payload.decided_by_label or "anonymous",
    )
    await db.commit()
    log.info(
        "conference.decision",
        conference_id=str(conference.id),
        decision=payload.decision,
        actor=payload.decided_by_label,
    )
    return DecisionRead.model_validate(decision)


@_r_decisions.get("/{conference_id}/decisions")
async def list_decisions(db: DbSession, conference_id: UUID) -> dict:
    """Decision history for this conference (newest first)."""
    rows = (
        (
            await db.execute(
                select(Decision)
                .where(Decision.conference_id == conference_id)
                .order_by(Decision.decided_at.desc())
            )
        )
        .scalars()
        .all()
    )
    return {
        "conference_id": str(conference_id),
        "decisions": [DecisionRead.model_validate(r).model_dump(mode="json") for r in rows],
    }


# ==========================================================================
# conferences/detail.py
# ==========================================================================


_r_detail = APIRouter(prefix="/api/v1/conferences", tags=["conferences"])


@_r_detail.get("/{conference_id}", response_model=ConferenceRead)
async def get_conference(db: DbSession, conference_id: UUID) -> ConferenceRead:
    row = await db.get(Conference, conference_id)
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No conference {conference_id}",
        )
    return to_read(row)


@_r_detail.patch("/{conference_id}", response_model=ConferenceRead)
async def update_conference(
    db: DbSession,
    conference_id: UUID,
    payload: ConferenceUpdate,
    actor_label: str = Query(default="user_edit", max_length=120),
) -> ConferenceRead:
    """Correct a conference's details.

    There was no write path of any kind here. A conference could be
    created and deleted, and nothing in between — so a scraped row's
    dates, location, venue or cost could never be fixed, and the
    extraction LLM's answer was final. Most rows come from the scraper,
    which makes "the machine guessed and you cannot argue" the normal
    case rather than the edge case.

    Only fields explicitly present in the request body are written
    (``exclude_unset``), so sending ``{"venue": "Hall 4"}`` cannot blank
    out the dates. Passing an explicit null DOES clear a field, which is
    how you undo a bad extraction.

    ``status`` is deliberately not editable here — that is a decision,
    and decisions go through /decisions so they get a Decision row and an
    audit entry rather than being quietly overwritten.
    """
    row = await db.get(Conference, conference_id)
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No conference {conference_id}",
        )

    changes = payload.model_dump(exclude_unset=True)
    if not changes:
        return to_read(row)

    before = model_to_audit_dict(row)
    for field, value in changes.items():
        setattr(row, field, value)
    await db.flush()
    await db.refresh(row)

    await write_audit(
        db,
        action="conference.updated",
        target_type="conference",
        target_id=row.id,
        before=before,
        after=model_to_audit_dict(row),
        actor_label=actor_label,
    )
    await db.commit()
    log.info(
        "conference.updated",
        conference_id=str(conference_id),
        fields=sorted(changes),
        actor=actor_label,
    )
    return to_read(row)


@_r_detail.delete("/{conference_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_conference(
    db: DbSession,
    conference_id: UUID,
    actor_label: str = Query(default="user_delete", max_length=120),
) -> None:
    """Hard-delete a conference + all rows that reference it.

    The model FKs are declared ``ondelete='CASCADE'`` (matches, decisions,
    conference_sources, conference_topics, conference_audiences,
    conference_pillars, conference_smes,
    raw_pages-via-conference_sources). The single DELETE cascades; we
    log the deletion afterwards so admins
    have an audit trail.
    """
    row = await db.get(Conference, conference_id)
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No conference {conference_id}",
        )
    snapshot = model_to_audit_dict(row)
    await db.delete(row)
    await write_audit(
        db,
        action="conference.delete",
        target_type="conference",
        target_id=conference_id,
        before=snapshot,
        after=None,
        actor_label=actor_label,
    )
    await db.commit()
    log.info(
        "conference.deleted",
        conference_id=str(conference_id),
        slug=snapshot.get("slug"),
        actor_label=actor_label,
    )


@_r_detail.get("/{conference_id}/match", response_model=ConferenceMatchResponse)
async def conference_match(db: DbSession, conference_id: UUID) -> dict:
    """Latest match row for this conference (current algorithm_version).

    Auto-runs the matcher inline if no match exists yet for this version.
    The detail page should be self-sufficient — the user shouldn't have
    to know about a separate "run matcher" step. UI shows a skeleton
    while this endpoint runs, so paying the matcher cost here is fine.
    """
    if await db.get(Conference, conference_id) is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No conference {conference_id}",
        )
    match = (
        await db.execute(
            select(Match)
            .where(Match.conference_id == conference_id)
            .where(Match.algorithm_version == ALGORITHM_VERSION)
        )
    ).scalar_one_or_none()
    if match is None:
        try:
            log.info("conference.match.auto_run", conference_id=str(conference_id))
            await run_fit_match(db, conference_id)
            await db.commit()
            match = (
                await db.execute(
                    select(Match)
                    .where(Match.conference_id == conference_id)
                    .where(Match.algorithm_version == ALGORITHM_VERSION)
                )
            ).scalar_one_or_none()
        except Exception as exc:
            log.warning(
                "conference.match.auto_run_failed",
                conference_id=str(conference_id),
                error=str(exc)[:200],
            )
    if match is None:
        return {
            "conference_id": str(conference_id),
            "algorithm_version": ALGORITHM_VERSION,
            "match": None,
        }
    # Compute the boost breakdown live so the UI can show exactly
    # what's lifting (or sinking) overall_score above the weighted
    # stage blend. Cheap — no LLM, no embeddings.

    conf = await db.get(Conference, conference_id)
    settings = get_settings()
    boosts = await compute_boosts(db=db, conference=conf, settings=settings)
    # The same definition the list uses. Reading matches.overall_score here
    # showed the value from whenever the matcher last ran, so the detail
    # page and the list disagreed about the same conference.
    live_overall = await live_overall_score(
        db=db,
        conference=conf,
        fit=match.fit_score,
        speakers=match.speaker_score,
        settings=settings,
    )
    return {
        "conference_id": str(conference_id),
        "algorithm_version": ALGORITHM_VERSION,
        "match": {
            "id": str(match.id),
            "fit_score": round(float(match.fit_score), 4),
            "speaker_score": round(float(match.speaker_score), 4),
            "judge_verdict": match.judge_verdict,
            "judge_reason": match.judge_reason or "",
            "overall_score": round(live_overall, 4),
            "overall_score_at_scoring_time": round(float(match.overall_score), 4),
            "boosts": boosts.as_dict(),
            "recommended_sme_ids": [str(s) for s in match.recommended_sme_ids],
            "rationale_text": match.rationale_text,
            "computed_at": match.computed_at.isoformat() if match.computed_at else None,
        },
    }


@_r_detail.get("/{conference_id}/sources")
async def conference_sources(db: DbSession, conference_id: UUID) -> dict:
    """The scraped pages this conference row was built from."""
    if await db.get(Conference, conference_id) is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No conference {conference_id}",
        )

    rows = (
        (
            await db.execute(
                select(RawPage)
                .join(ConferenceSource, ConferenceSource.raw_page_id == RawPage.id)
                .where(ConferenceSource.conference_id == conference_id)
                .order_by(RawPage.fetched_at.desc())
            )
        )
        .scalars()
        .all()
    )
    return {
        "conference_id": str(conference_id),
        "sources": [
            {
                "raw_page_id": str(r.id),
                "url": r.url,
                "fetched_at": r.fetched_at.isoformat() if r.fetched_at else None,
                "http_status": r.http_status,
                "parse_status": r.parse_status,
                "hash_prefix": (r.hash or "")[:12],
            }
            for r in rows
        ],
    }


@_r_detail.get("/{conference_id}/smes", response_model=ConferenceSmesResponse)
async def conference_smes(
    db: DbSession,
    conference_id: UUID,
    k: int = Query(default=5, ge=1, le=20),
) -> dict:
    """Ranked SMEs for this conference with the per-dimension breakdown.

    Each breakdown carries audience_overlap, bio_similarity,
    location and past_attendance, plus the composite and whether it cleared
    the gate. The weights come back too, because a dimension whose inputs
    are entirely absent is dropped and the rest renormalised — so the
    numbers only add up if the caller can see which weights applied.
    """
    if await db.get(Conference, conference_id) is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No conference {conference_id}",
        )
    settings = get_settings()
    result = await rank_smes_for_conference(db, conference_id, k=k, gate=settings.match_s_gate)

    return {
        "conference_id": str(conference_id),
        "gate": settings.match_s_gate,
        "weights": {
            "audience": settings.sme_w_audience,
            "bio": settings.sme_w_bio,
            "location": settings.sme_w_location,
            "past": settings.sme_w_past,
        },
        "above_gate": [b.to_dict() for b in result.above_gate],
        "near_misses": [b.to_dict() for b in result.near_misses],
    }


@_r_detail.get("/{conference_id}/talks", response_model=ConferenceTalksResponse)
async def conference_talks(
    db: DbSession,
    conference_id: UUID,
    k: int = Query(default=10, ge=1, le=50),
) -> dict:
    """Rank the active talk library against this conference.

    Deliberately a separate ranking from ``/smes``: CFP committees accept
    a talk first and a speaker second, so the operator wants "which of our
    talks fits this event" and "who should go" as two independent lists.
    The similarity is the same top-K-cosine measure the SME bio dimension
    uses, so the two lists' numbers are comparable.
    """
    if await db.get(Conference, conference_id) is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No conference {conference_id}",
        )
    ranked = await rank_talks_for_conference(db, conference_id, k=k)
    return {
        "conference_id": str(conference_id),
        "talks": [t.to_dict() for t in ranked],
    }


# ==========================================================================
# conference_series.py
# ==========================================================================


_r_series = APIRouter(prefix="/api/v1/conference-series", tags=["conference-series"])


class SeriesCreate(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    canonical_name: str = Field(..., min_length=2, max_length=150)
    aliases: list[str] = Field(default_factory=list, max_length=20)
    description: str = Field(default="", max_length=600)
    typical_month: int | None = Field(default=None, ge=1, le=12)
    typical_topics: list[str] = Field(default_factory=list, max_length=30)
    homepage: str | None = Field(default=None, max_length=500)


class SeriesUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    canonical_name: str | None = Field(default=None, min_length=2, max_length=150)
    aliases: list[str] | None = Field(default=None, max_length=20)
    description: str | None = Field(default=None, max_length=600)
    typical_month: int | None = Field(default=None, ge=1, le=12)
    typical_topics: list[str] | None = Field(default=None, max_length=30)
    homepage: str | None = Field(default=None, max_length=500)
    is_active: bool | None = None


class SeriesRead(BaseModel):
    model_config = ConfigDict(from_attributes=True, extra="ignore")
    id: UUID
    canonical_name: str
    aliases: list[str]
    description: str
    typical_month: int | None
    typical_topics: list[str]
    homepage: str | None
    is_active: bool
    created_at: datetime
    updated_at: datetime


class SeriesListItem(SeriesRead):
    """Listing row — includes member counts so the settings UI can render
    them in one call."""

    member_count: int


class AssignBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    conference_id: UUID


@_r_series.get("")
async def list_series(
    db: DbSession,
    include_inactive: bool = Query(default=False),
    limit: int = Query(default=200, ge=1, le=500),
) -> dict:
    """List series with their member-conference counts."""
    base = select(ConferenceSeries)
    if not include_inactive:
        base = base.where(ConferenceSeries.is_active.is_(True))
    base = base.order_by(ConferenceSeries.canonical_name.asc()).limit(limit)
    rows = (await db.execute(base)).scalars().all()

    # One small aggregation for counts.
    counts = dict(
        (
            await db.execute(
                select(Conference.series_id, func.count(Conference.id))
                .where(Conference.series_id.is_not(None))
                .group_by(Conference.series_id)
            )
        ).all()
    )

    items = [
        SeriesListItem(
            **SeriesRead.model_validate(r).model_dump(),
            member_count=int(counts.get(r.id, 0)),
        )
        for r in rows
    ]
    return {"items": [i.model_dump(mode="json") for i in items], "total": len(items)}


@_r_series.get("/{series_id}")
async def get_series(db: DbSession, series_id: UUID) -> dict:
    """Series row + member conferences ordered by start_date."""
    row = await db.get(ConferenceSeries, series_id)
    if row is None:
        raise HTTPException(status_code=404, detail=f"No conference_series {series_id}")

    members = (
        (
            await db.execute(
                select(Conference)
                .where(Conference.series_id == series_id)
                .order_by(Conference.start_date.asc().nullslast())
            )
        )
        .scalars()
        .all()
    )

    return {
        **SeriesRead.model_validate(row).model_dump(mode="json"),
        "members": [
            {
                "id": str(c.id),
                "name": c.name,
                "slug": c.slug,
                "status": c.status,
                "start_date": c.start_date.isoformat() if c.start_date else None,
            }
            for c in members
        ],
    }


@_r_series.post("", response_model=SeriesRead, status_code=status.HTTP_201_CREATED)
async def post_series(db: DbSession, payload: SeriesCreate) -> SeriesRead:
    row = await create_series(
        db,
        canonical_name=payload.canonical_name,
        aliases=payload.aliases,
        description=payload.description,
        typical_month=payload.typical_month,
        typical_topics=payload.typical_topics,
        homepage=payload.homepage,
        actor_label="api",
    )
    await db.commit()
    return SeriesRead.model_validate(row)


@_r_series.patch("/{series_id}", response_model=SeriesRead)
async def patch_series(db: DbSession, series_id: UUID, payload: SeriesUpdate) -> SeriesRead:
    row = await update_series(
        db,
        series_id,
        canonical_name=payload.canonical_name,
        aliases=payload.aliases,
        description=payload.description,
        typical_month=payload.typical_month,
        typical_topics=payload.typical_topics,
        homepage=payload.homepage,
        is_active=payload.is_active,
        actor_label="api",
    )
    await db.commit()
    return SeriesRead.model_validate(row)


@_r_series.delete("/{series_id}", status_code=status.HTTP_200_OK)
async def delete_series(db: DbSession, series_id: UUID) -> dict:
    row = await deactivate_series(db, series_id, actor_label="api")
    await db.commit()
    return {"id": str(row.id), "is_active": row.is_active}


@_r_series.post("/{series_id}/assign", status_code=status.HTTP_200_OK)
async def assign(db: DbSession, series_id: UUID, body: AssignBody) -> dict:
    """Link a conference to this series. Triggers a matcher recompute
    (past-attendance bonus may shift). Returns updated conference fields."""
    conf = await assign_conference_to_series(db, series_id, body.conference_id, actor_label="api")
    await db.commit()
    return {
        "conference_id": str(conf.id),
        "series_id": str(conf.series_id) if conf.series_id else None,
        "status": conf.status,
    }


@_r_series.post("/{series_id}/unassign", status_code=status.HTTP_200_OK)
async def unassign(db: DbSession, series_id: UUID, body: AssignBody) -> dict:
    """Unlink a conference from any series. The ``series_id`` in the path
    is matched against the conference's current ``series_id`` and errors
    if they don't match — protects against stale UI re-submitting an old link.
    """
    conf = await db.get(Conference, body.conference_id)
    if conf is None:
        raise HTTPException(status_code=404, detail=f"No conference {body.conference_id}")
    if conf.series_id != series_id:
        raise HTTPException(
            status_code=409,
            detail=(
                f"Conference {body.conference_id} is not linked to series "
                f"{series_id} (currently linked to {conf.series_id})."
            ),
        )
    conf = await unassign_conference_from_series(db, body.conference_id, actor_label="api")
    await db.commit()
    return {
        "conference_id": str(conf.id),
        "series_id": None,
        "status": conf.status,
    }


# ==========================================================================
# participation.py
# ==========================================================================


_r_participation = APIRouter(prefix="/api/v1", tags=["participation"])


@_r_participation.get("/conferences/{conference_id}/attendance", response_model=AttendanceSummary)
async def get_attendance(db: DbSession, conference_id: UUID) -> AttendanceSummary:
    return await conferences.get_attendance(db, conference_id)


@_r_participation.put("/conferences/{conference_id}/attendance", response_model=AttendanceSummary)
async def put_attendance(
    db: DbSession, conference_id: UUID, payload: AttendanceSummary
) -> AttendanceSummary:
    result = await conferences.set_attendance(db, conference_id, payload)
    await db.commit()
    return result


@_r_participation.get(
    "/conferences/{conference_id}/participation",
    response_model=list[ParticipationRead],
)
async def list_participation(db: DbSession, conference_id: UUID) -> list[ParticipationRead]:
    return await conferences.list_participation(db, conference_id)


@_r_participation.post(
    "/conferences/{conference_id}/participation",
    response_model=ParticipationRead,
    status_code=status.HTTP_201_CREATED,
)
async def add_participation(
    db: DbSession, conference_id: UUID, payload: ParticipationCreate
) -> ParticipationRead:
    result = await conferences.add_participation(db, conference_id, payload)
    await db.commit()
    return result


@_r_participation.patch("/participation/{participation_id}", response_model=ParticipationRead)
async def update_participation(
    db: DbSession, participation_id: UUID, payload: ParticipationUpdate
) -> ParticipationRead:
    result = await conferences.update_participation(db, participation_id, payload)
    await db.commit()
    return result


class MarkAttendedRequest(BaseModel):
    """Confirm, or take back, that this person actually went."""

    attended: bool = True


@_r_participation.post(
    "/participation/{participation_id}/attended",
    response_model=ParticipationRead,
)
async def mark_attended(
    db: DbSession, participation_id: UUID, payload: MarkAttendedRequest
) -> ParticipationRead:
    """Move a planned participation to attended, or back again.

    The other route to attended needs no endpoint: once ``departs_on``
    has passed, ``has_attended`` reads true on its own. This exists for
    the cases dates cannot answer — someone went at short notice, or the
    plan slipped and the trip did not happen.

    Un-confirming is deliberately allowed. A record nobody can correct
    stops being trusted, and the whole point of this table is that the
    team believes what it says.
    """
    result = await conferences.mark_attended(db, participation_id, attended=payload.attended)
    await db.commit()
    return result


@_r_participation.delete(
    "/participation/{participation_id}", status_code=status.HTTP_204_NO_CONTENT
)
async def delete_participation(db: DbSession, participation_id: UUID) -> Response:
    await conferences.delete_participation(db, participation_id)
    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ---------------------------------------------------------------------------
# ORDER MATTERS. /stats and /duplicates must be registered before the
# /{conference_id} pattern in detail, or that pattern swallows them.
# ---------------------------------------------------------------------------


router = APIRouter()
router.include_router(_r_stats)
router.include_router(_r_duplicates)
router.include_router(_r_create)
router.include_router(_r_listing)
router.include_router(_r_decisions)
router.include_router(_r_detail)
router.include_router(_r_series)
router.include_router(_r_participation)
