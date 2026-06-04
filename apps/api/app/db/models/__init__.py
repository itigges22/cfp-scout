"""ORM models package.

Importing this module registers every model against ``Base.metadata`` so
Alembic's autogenerate sees all tables in one pass. Always re-export new
models here.

See ``docs/data-model.md`` for the per-column schema reference and
``PLANS/phase-1/04-database-schema.md`` for the design doc.
"""

from app.db.base import Base
from app.db.models._mixins import TimestampedMixin, uuid_pk
from app.db.models.audit import AuditLog, ContentVersion
from app.db.models.entities import (
    AudienceProfile,
    Conference,
    ConferenceSeries,
    ConferenceSource,
    MessagingDocument,
    PastConference,
    PillarContentRoadmap,
    PillarGtmStrategy,
    RawPage,
    Sme,
    Source,
    StrategicPillar,
    Talk,
    TalkSubmission,
    TalkTag,
    Topic,
)
from app.db.models.junctions import (
    ConferenceAudience,
    ConferencePillar,
    ConferenceSme,
    ConferenceTopic,
    MessagingPillar,
    SmePillar,
    SmeAudience,
    SmeTopic,
    TalkTagAssignment,
    TalkTopic,
)
from app.db.models.matching import Decision, Match, MatchTeamRecommendation
from app.db.models.ops import (
    ChatMessage,
    ChatSession,
    IngestJob,
    LLMCall,
    Notification,
)
from app.db.models.vectors import DocumentChunk, EmbeddingModel

__all__ = [
    # entities
    "AudienceProfile",
    # audit
    "AuditLog",
    "Base",
    # ops
    "ChatMessage",
    "ChatSession",
    "Conference",
    # junctions
    "ConferenceAudience",
    "ConferencePillar",
    "ConferenceSeries",
    "ConferenceSme",
    "ConferenceSource",
    "ConferenceTopic",
    "ContentVersion",
    # matching
    "Decision",
    # vectors
    "DocumentChunk",
    "EmbeddingModel",
    "IngestJob",
    "LLMCall",
    "Match",
    "MatchTeamRecommendation",
    "MessagingDocument",
    "MessagingPillar",
    "Notification",
    "PastConference",
    "PillarContentRoadmap",
    "PillarGtmStrategy",
    "RawPage",
    "Sme",
    "SmeAudience",
    "SmePillar",
    "SmeTopic",
    "Source",
    "StrategicPillar",
    "Talk",
    "TalkSubmission",
    "TalkTag",
    "TalkTagAssignment",
    "TalkTopic",
    "TimestampedMixin",
    "Topic",
    "uuid_pk",
]
