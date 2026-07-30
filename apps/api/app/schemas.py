"""The API's data shapes: what a request may contain, what a response says.

WHAT THIS DOES
    The shared primitives first — constrained string types, country and
    language validators, the strict request base and the read base — then
    the per-entity request and response models built from them.

HOW IT CONNECTS
    Imported by  app/api/v1/*.py and the services that build responses
    Helpers      none; these are pure Pydantic

WORTH KNOWING
    Nine files, and every one of the eight entity modules imported the
    same primitives from ``common`` and had exactly two consumers. The
    constrained types ARE the contract — ``ShortName``, ``Description``,
    ``CountryCode`` — and reading a model meant opening common.py beside it
    to learn what its fields actually permit.

    ``StrictBase`` forbids unknown fields so a typo in a request body is a
    422 rather than a silently ignored key. ``ReadBase`` does not, because
    responses grow fields and old clients must keep working.

    EVENT_KINDS lives here and is the single source for the event-kind
    vocabulary; app/settings.py seeds its default from it rather than
    restating the list.
"""

from __future__ import annotations

from datetime import date, datetime
from enum import StrEnum
from typing import Annotated, Literal, TypeVar
from uuid import UUID
from uuid import UUID as UUIDType

from pydantic import (
    BaseModel,
    ConfigDict,
    EmailStr,
    Field,
    HttpUrl,
    StringConstraints,
    field_validator,
    model_validator,
)
from pydantic.functional_validators import AfterValidator
from slugify import slugify

# ==========================================================================
# schemas.py
# ==========================================================================


EVENT_KINDS: tuple[str, ...] = (
    "corporate",
    "grassroot",
    "developer_day",
    "research",
    "hackathon",
)


BASE_CONFIG = ConfigDict(
    extra="forbid",
    str_strip_whitespace=True,
    use_enum_values=False,  # keep StrEnum members typed, not stringified yet
)


class StrictBase(BaseModel):
    """All Scout input schemas inherit from this. Centralises model_config."""

    model_config = BASE_CONFIG


class ReadBase(BaseModel):
    """Base for *Read* schemas — permissive on extras, supports ORM-to-schema.

    Read schemas serialize ORM rows to JSON. They need ``from_attributes=True``
    so FastAPI can pull values via attribute access. They tolerate extra
    fields because the ORM may carry private attributes we don't surface.
    """

    model_config = ConfigDict(from_attributes=True, extra="ignore")


T = TypeVar("T")


class Page[T](BaseModel):
    """Generic paginated response wrapper.

    Routes that list resources return Page[ResourceRead]. The frontend
    consumes ``items`` + ``total`` for pagination controls.
    """

    items: list[T]
    total: int
    page: int
    per_page: int


READ_CONFIG = ConfigDict(from_attributes=True, extra="ignore")


class RoleSeniority(StrEnum):
    EXECUTIVE = "executive"
    DIRECTOR = "director"
    MANAGER = "manager"
    IC = "ic"
    MIXED = "mixed"


class MessagingSourceType(StrEnum):
    STRUCTURED = "structured"
    PDF = "pdf"


ShortTitle = Annotated[str, StringConstraints(strip_whitespace=True, min_length=3, max_length=120)]


ShortName = Annotated[str, StringConstraints(strip_whitespace=True, min_length=3, max_length=100)]


AudienceName = Annotated[str, StringConstraints(strip_whitespace=True, min_length=3, max_length=80)]


Description = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=50, max_length=500)
]


ConferenceName = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=3, max_length=150)
]


ShortNote = Annotated[str, StringConstraints(strip_whitespace=True, max_length=500)]


ListItem = Annotated[str, StringConstraints(strip_whitespace=True, min_length=2, max_length=200)]


ElevatorPitch = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=50, max_length=600)
]


TalkingPoint = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=5, max_length=200)
]


SmeBio = Annotated[str, StringConstraints(strip_whitespace=True, min_length=200, max_length=2000)]


CountryCode = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=2, max_length=2, to_upper=True)
]


LanguageCode = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=2, max_length=2, to_lower=True)
]


def _iso_3166_alpha2_codes() -> frozenset[str]:
    """Build the canonical set of ISO-3166-1 alpha-2 country codes via pycountry.

    Defined as a function so the import cost is paid once at module load.
    pycountry ships the lists; we never maintain country data ourselves.
    """
    import pycountry  # local import to keep startup graph tidy

    return frozenset(country.alpha_2 for country in pycountry.countries)


def _iso_639_1_codes() -> frozenset[str]:
    """ISO-639-1 (2-letter) language codes."""
    import pycountry

    return frozenset(lang.alpha_2 for lang in pycountry.languages if hasattr(lang, "alpha_2"))


_COUNTRY_CODES = _iso_3166_alpha2_codes()


_LANGUAGE_CODES = _iso_639_1_codes()


def validate_country_code(value: str) -> str:
    """Validator: must be a real ISO-3166-1 alpha-2 code."""
    upper = value.upper()
    if upper not in _COUNTRY_CODES:
        raise ValueError(
            f"'{value}' is not a valid ISO-3166-1 alpha-2 country code. "
            f"Use codes like 'US', 'DE', 'JP'."
        )
    return upper


def validate_language_code(value: str) -> str:
    """Validator: must be a real ISO-639-1 (2-letter) language code."""
    lower = value.lower()
    if lower not in _LANGUAGE_CODES:
        raise ValueError(
            f"'{value}' is not a valid ISO-639-1 language code. Use codes like 'en', 'de', 'ja'."
        )
    return lower


# ==========================================================================
# schemas.py
# ==========================================================================


class AudienceProfileBase(StrictBase):
    name: AudienceName
    description: Description

    # Industry is text now; runtime validation against the
    # `industries` lookup table lives in the service
    # layer, not the schema, so we don't have to migrate every time a new
    # industry is added.
    industry: Annotated[str, Field(min_length=2, max_length=80)]

    role_seniority: RoleSeniority

    primary_pain_points: Annotated[list[ListItem], Field(min_length=2, max_length=8)]
    key_messages: Annotated[list[ListItem], Field(min_length=2, max_length=8)]
    exclusion_criteria: Annotated[list[ListItem], Field(max_length=5)] = []

    pillar_id: UUID | None = None

    is_active: bool = True


class AudienceProfileCreate(AudienceProfileBase):
    pass


class AudienceProfileUpdate(AudienceProfileBase):
    pass


class AudienceProfileRead(AudienceProfileBase):
    model_config = READ_CONFIG

    id: UUID
    pillar_id: UUID | None = None
    created_at: datetime
    updated_at: datetime


# ==========================================================================
# schemas.py
# ==========================================================================


DOC_KIND_VALUES = ("gtm_strategy", "content_roadmap", "other")


class MessagingDocumentBase(StrictBase):
    """Fields common to create + update."""

    title: ShortTitle
    source_type: MessagingSourceType
    doc_kind: Literal[DOC_KIND_VALUES] = "other"  # type: ignore[valid-type]

    elevator_pitch: ElevatorPitch
    target_personas: Annotated[list[ListItem], Field(min_length=1, max_length=8)]
    key_themes: Annotated[list[ListItem], Field(min_length=3, max_length=12)]
    talking_points: Annotated[list[TalkingPoint], Field(min_length=3, max_length=15)]

    differentiators: Annotated[list[ListItem], Field(max_length=8)] = []
    competitive_position: Annotated[ShortNote, Field(default="")] = ""

    pillar_id: UUIDType | None = None
    is_active: bool = True

    @model_validator(mode="after")
    def _check_source_type_consistency(self) -> MessagingDocumentBase:
        return self


class MessagingDocumentCreate(MessagingDocumentBase):
    """POST body. Accepts both structured and pdf source types."""


class MessagingDocumentUpdate(MessagingDocumentBase):
    """PUT body. Same shape; the api wires partial-update vs replace
    semantics. The shape stays strict either way."""


class MessagingDocumentRead(MessagingDocumentBase):
    """Read response. Adds server-managed fields + relaxes extras for ORM serialization."""

    model_config = READ_CONFIG

    id: UUIDType
    file_path: str | None = None
    created_at: datetime
    updated_at: datetime


class MessagingDocUploadPreview(BaseModel):
    """Relaxed preview returned by the PDF upload endpoint.

    No min_length constraints — the LLM may not extract every field perfectly.
    The operator reviews and edits before saving via the normal create endpoint.
    """

    model_config = ConfigDict(extra="ignore")

    doc_kind: str = "other"
    title: str = ""
    elevator_pitch: str = ""
    target_personas: list[str] = []
    key_themes: list[str] = []
    talking_points: list[str] = []
    differentiators: list[str] = []
    competitive_position: str = ""


# ==========================================================================
# schemas.py
# ==========================================================================


ACTIVITIES = ("talk", "booth", "attend", "sponsor")


Activity = Literal["talk", "booth", "attend", "sponsor"]


AttendanceVerdict = Literal["would_attend", "unsure", "would_not_attend"]


class ParticipationBase(StrictBase):
    sme_id: UUID | None = None
    # May be left blank when sme_id is given — the service fills it in from
    # the SME's name. Required otherwise, since a row with neither an id nor
    # a name records that somebody was there without saying who.
    person_label: str = Field(default="", max_length=200)
    activity: Activity
    talk_id: UUID | None = None

    # When this person travels. Not the conference's dates — people arrive
    # late, leave early, or cover one day of three, and "who is on the
    # ground on Wednesday" is a question the team actually asks.
    #
    # Their presence is also what makes a row a PLAN. A participation row
    # with dates and no attended_at means "we intend to send them", which
    # is the state between saying yes and having gone.
    arrives_on: date | None = None
    departs_on: date | None = None

    notes: ShortNote | None = ""

    @model_validator(mode="after")
    def _departure_cannot_precede_arrival(self) -> ParticipationBase:
        if (
            self.arrives_on is not None
            and self.departs_on is not None
            and self.departs_on < self.arrives_on
        ):
            raise ValueError("departs_on cannot be before arrives_on")
        return self

    @model_validator(mode="after")
    def _somebody_must_be_named(self) -> ParticipationBase:
        if self.sme_id is None and not self.person_label.strip():
            raise ValueError("person_label is required when sme_id is not given")
        return self

    @model_validator(mode="after")
    def _only_a_talk_has_an_abstract(self) -> ParticipationBase:
        """A booth shift has no abstract.

        Allowing one would let the UI store combinations that read as
        meaningful and are not, which is how a field ends up being
        ignored by everyone who reads it.
        """
        if self.activity != "talk" and self.talk_id is not None:
            raise ValueError("talk_id only applies to activity='talk'")
        return self


class ParticipationCreate(ParticipationBase):
    pass


class ParticipationUpdate(ParticipationBase):
    pass


class ParticipationRead(ParticipationBase):
    model_config = READ_CONFIG

    id: UUID
    conference_id: UUID
    #: Set when someone confirms this person actually went. NULL means the
    #: row is still a plan.
    attended_at: datetime | None = None
    #: Derived, never stored: attended_at is set, or the departure date has
    #: passed. Both routes the operator described ("by acknowledgement of
    #: the dates attending or by setting it to attended"), and computing it
    #: means no background job owns a state a human also owns.
    has_attended: bool = False
    created_at: datetime
    updated_at: datetime


class AttendanceSummary(StrictBase):
    """The event-level facts, edited as one form alongside the people.

    Every field is optional and stays answerable later. The operator
    records cost and leads when they have them, which is usually weeks
    after the event — a form that refused to save without them would just
    mean nothing gets recorded at all.
    """

    edition_year: int | None = Field(default=None, ge=1990, le=2100)
    spend_usd: int | None = Field(default=None, ge=0)
    #: How many leads the event produced. Previously had no representation
    #: anywhere in the codebase, so the feedback loop into matching carried
    #: only a three-value verdict.
    leads_generated: int | None = Field(default=None, ge=0)
    audience_size_estimate: int | None = Field(default=None, ge=0)
    attendance_verdict: AttendanceVerdict | None = None
    attendance_notes: str = ""


# ==========================================================================
# schemas.py
# ==========================================================================


class PillarRead(BaseModel):
    model_config = READ_CONFIG

    id: UUID
    name: str
    description: str
    enriched_description: str | None = None
    display_order: int
    created_at: datetime
    updated_at: datetime

    # Aggregate counts populated by service layer
    sme_count: int = 0
    talk_count: int = 0
    audience_count: int = 0
    conference_count: int = 0


class PillarCreate(StrictBase):
    name: str = Field(min_length=2, max_length=80)
    description: str = Field(min_length=2)
    display_order: int | None = None


class PillarUpdate(StrictBase):
    name: str = Field(min_length=2, max_length=80)
    description: str = Field(min_length=2)


class SmePillarLink(StrictBase):
    is_primary: bool = False


class SmePillarRead(BaseModel):
    model_config = READ_CONFIG

    sme_id: UUID
    pillar_id: UUID
    is_primary: bool


# ==========================================================================
# schemas.py
# ==========================================================================


class SmeExternalLinks(StrictBase):
    """Allowed link keys for an SME profile. Add new keys here with intent."""

    linkedin: str | None = None
    github: str | None = None
    website: str | None = None


class SmeBase(StrictBase):
    full_name: ShortName
    email: EmailStr | None = None

    # team: free-form for now (your team + sibling team names). A future
    # iteration could enum-ify this once we know the closed set.
    team: Annotated[str, Field(min_length=2, max_length=60)]

    #: Was min_length=1, which made SME creation impossible on a fresh
    #: install: audiences are created under a pillar, so the only path to a
    #: first SME was pillar -> audience -> SME, with nothing telling you so.
    #: The form just refused to submit. SmeRead already permits an empty list
    #: and its docstring calls "fill in later" a deliberate workflow — the
    #: write side simply disagreed with the read side.
    audience_focus: Annotated[list[UUID], Field(max_length=8)]
    #: What they work on, in their own words. An ancestor of this field
    #: (expertise_areas) was once removed in favour of the sme_topics
    #: junction; this deliberately reverses that. Vocabulary tagging asked
    #: people to self-describe from 130+ machine-extracted entries, so
    #: they didn't — free text goes into the embedding, which is what the
    #: ranker actually reads.
    expertise: Annotated[str, Field(max_length=6000)] = ""

    location_country: CountryCode
    location_city: Annotated[str | None, Field(default=None, max_length=100)] = None

    bio: SmeBio

    languages: list[LanguageCode] = []

    external_links: SmeExternalLinks = SmeExternalLinks()

    is_active: bool = True

    # ----- runtime validation ----------------------------------------------
    @field_validator("location_country")
    @classmethod
    def _validate_country(cls, value: str) -> str:
        return validate_country_code(value)

    @field_validator("languages")
    @classmethod
    def _validate_languages(cls, value: list[str]) -> list[str]:
        return [validate_language_code(code) for code in value]



class SmeCreate(SmeBase):
    #: Strategic pillars this person covers. The sme_pillars junction and its
    #: link/unlink endpoints already existed, but only the PILLAR page could
    #: reach them — so an SME added from the SME page was saved with no pillar
    #: at all and the matcher had one less thing to reason about.
    pillar_ids: list[UUID] = Field(default_factory=list)

    pass


class SmeUpdate(SmeBase):
    #: Replaces the whole set. None means "leave the links alone", which is
    #: what a PATCH that never mentions pillars should do.
    pillar_ids: list[UUID] | None = None

    pass


class SmeRead(SmeBase):
    """SME row as returned by the API.

    Inherits the field set from ``SmeBase`` but **relaxes** the
    min-length constraints on the four fields that ``SmeBase`` requires
    on write. The read surface has to be able to serialize any row
    already in the DB — including partially-seeded rows uploaded via
    a bulk import with placeholder bios + empty topic/audience arrays,
    which is a deliberate "fill in later" workflow.

    Strict validation still applies on ``SmeCreate`` / ``SmeUpdate``.
    """

    model_config = READ_CONFIG

    audience_focus: list[UUID] = []
    bio: Annotated[str, Field(max_length=2000)] = ""

    id: UUID
    created_at: datetime
    updated_at: datetime
    #: Pillars this SME is linked to. Read-side so a form can show the
    #: current set without N calls to /pillars/{id}/smes.
    pillar_ids: list[UUID] = Field(default_factory=list)


# ==========================================================================
# schemas.py
# ==========================================================================


class SourceKind(StrEnum):
    """Crawl-strategy enum. Pass 1 ships rss + page; pass 2 adds the rest."""

    RSS = "rss"
    PAGE = "page"
    # Reserved, not yet implemented:
    SITEMAP = "sitemap"
    ICS = "ics"
    WIKICFP = "wikicfp"
    API = "api"


_VALID_CADENCE_PATTERN = (
    # very small allowlist — single positive integer + unit
    # examples: "15 minutes", "1 hour", "1 day", "7 days"
    r"^\d{1,4} (minute|minutes|hour|hours|day|days|week|weeks)$"
)


CrawlCadence = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        min_length=3,
        max_length=30,
        pattern=_VALID_CADENCE_PATTERN,
    ),
]


class SourceCreate(StrictBase):
    """POST /sources payload."""

    name: ShortName
    url: HttpUrl
    kind: SourceKind
    crawl_cadence: CrawlCadence = "1 day"
    politeness_delay_seconds: int = Field(default=3, ge=1, le=60)
    enabled: bool = True
    notes: ShortNote | None = None

    @field_validator("kind", mode="after")
    @classmethod
    def _reject_unsupported_kinds_for_pass_1(cls, kind: SourceKind) -> SourceKind:
        """Pass 1 only supports rss + page. Others land in pass 2."""
        if kind in {SourceKind.SITEMAP, SourceKind.ICS, SourceKind.WIKICFP, SourceKind.API}:
            raise ValueError(
f"Source kind {kind.value!r} is not implemented yet. "
                "For now use 'rss' or 'page'."
            )
        return kind


class SourceUpdate(StrictBase):
    """PATCH /sources/{id}. All fields optional."""

    name: ShortName | None = None
    url: HttpUrl | None = None
    crawl_cadence: CrawlCadence | None = None
    politeness_delay_seconds: int | None = Field(default=None, ge=1, le=60)
    enabled: bool | None = None
    notes: ShortNote | None = None


class SourceRead(ReadBase):
    """GET /sources response row."""

    model_config = READ_CONFIG

    id: UUID
    name: str
    url: str
    kind: str
    enabled: bool
    crawl_cadence: str
    politeness_delay_seconds: int
    robots_allowed: bool
    last_crawled_at: datetime | None = None
    notes: str | None = None
    created_at: datetime
    updated_at: datetime


# ==========================================================================
# schemas.py
# ==========================================================================


class TalkCreate(StrictBase):
    title: str = Field(min_length=1, max_length=500)
    abstract: str | None = None
    source_type: str = "manual"
    file_path: str | None = None
    pillar_id: UUID | None = None
    primary_sme_id: UUID | None = None
    co_speaker_ids: list[UUID] = Field(default_factory=list)
    talk_format: str | None = None
    suggested_duration_minutes: int | None = Field(default=None, ge=1, le=600)
    review_status: str = "draft"
    is_active: bool = True


class TalkUpdate(StrictBase):
    title: str | None = Field(default=None, min_length=1, max_length=500)
    abstract: str | None = None
    pillar_id: UUID | None = None
    primary_sme_id: UUID | None = None
    co_speaker_ids: list[UUID] | None = None
    talk_format: str | None = None
    suggested_duration_minutes: int | None = Field(default=None, ge=1, le=600)
    review_status: str | None = None
    is_active: bool | None = None


class TalkSubmissionRead(BaseModel):
    model_config = READ_CONFIG

    id: UUID
    talk_id: UUID
    conference_id: UUID
    #: Joined in by the read path — the submissions list is the answer to
    #: "which conferences did we pitch this to", and a UUID answers nothing.
    conference_name: str | None = None
    submitted_by_sme_id: UUID | None = None
    submitted_at: date | None = None
    outcome: str | None = None
    notes: str | None = None
    created_at: datetime


class TalkRead(BaseModel):
    model_config = READ_CONFIG

    id: UUID
    title: str
    abstract: str | None = None
    source_type: str
    file_path: str | None = None
    pillar_id: UUID | None = None
    primary_sme_id: UUID | None = None
    co_speaker_ids: list[UUID] = []
    talk_format: str | None = None
    suggested_duration_minutes: int | None = None
    review_status: str
    is_active: bool
    created_at: datetime
    updated_at: datetime

    submissions: list[TalkSubmissionRead] = []

    # Derived from len(submissions). Populated by the service layer.
    times_applied: int = 0
    is_flagged: bool = False


class TalkSubmissionCreate(StrictBase):
    conference_id: UUID
    submitted_by_sme_id: UUID | None = None
    submitted_at: date | None = None
    outcome: str | None = None
    notes: str | None = None


class TalkSubmissionUpdate(StrictBase):
    outcome: str | None = None
    notes: str | None = None
    submitted_at: date | None = None


class SeriesReuseItem(BaseModel):
    series_id: UUID
    series_name: str
    submission_count: int


class ReuseCheckResult(BaseModel):
    talk_id: UUID
    submission_count_12m: int
    series_reuse: list[SeriesReuseItem] = []
    risk_level: str  # 'low' | 'medium' | 'high'
    warning: str | None = None


# ==========================================================================
# schemas.py
# ==========================================================================


def slugify_topic_name(value: str) -> str:
    """Slugify a topic name. ONE implementation, shared with the extractor.

    There were two. This one stripped non-ASCII outright while
    services/extraction.py transliterated via python-slugify, so
    "Café Ops" became "caf-ops" through the API and "cafe-ops" through the
    extractor. ``topics.slug`` is unique, so the same topic could land twice
    under two spellings, and only the separate name-uniqueness constraint
    caught it — after the slugs had already diverged.
    """
    return slugify(value, max_length=80, lowercase=True)


Slug = Annotated[
    str,
    Field(min_length=2, max_length=80),
    AfterValidator(slugify_topic_name),
]


__all__ = [
    "ACTIVITIES",
    "BASE_CONFIG",
    "DOC_KIND_VALUES",
    "READ_CONFIG",
    "AttendanceSummary",
    "AudienceProfileBase",
    "AudienceProfileCreate",
    "AudienceProfileRead",
    "AudienceProfileUpdate",
    "MessagingDocUploadPreview",
    "MessagingDocumentBase",
    "MessagingDocumentCreate",
    "MessagingDocumentRead",
    "MessagingDocumentUpdate",
    "MessagingSourceType",
    "Page",
    "ParticipationBase",
    "ParticipationCreate",
    "ParticipationRead",
    "ParticipationUpdate",
    "PillarCreate",
    "PillarRead",
    "PillarUpdate",
    "ReadBase",
    "ReuseCheckResult",
    "RoleSeniority",
    "SeriesReuseItem",
    "SmeBase",
    "SmeCreate",
    "SmeExternalLinks",
    "SmePillarLink",
    "SmePillarRead",
    "SmeRead",
    "SmeUpdate",
    "SourceCreate",
    "SourceKind",
    "SourceRead",
    "SourceUpdate",
    "StrictBase",
    "T",
    "TalkCreate",
    "TalkRead",
    "TalkSubmissionCreate",
    "TalkSubmissionRead",
    "TalkSubmissionUpdate",
    "TalkUpdate",
    "slugify_topic_name",
    "validate_country_code",
    "validate_language_code",
]
