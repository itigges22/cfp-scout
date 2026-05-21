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
    RawPage,
    Sme,
    Source,
    StrategicPillar,
    Topic,
)
from app.db.models.junctions import (
    ConferenceAudience,
    ConferencePillar,
    ConferenceSme,
    ConferenceTopic,
    MessagingPillar,
    SmeAudience,
    SmeTopic,
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
    "Base",
    "TimestampedMixin",
    "uuid_pk",
    # entities
    "AudienceProfile",
    "Conference",
    "ConferenceSeries",
    "ConferenceSource",
    "MessagingDocument",
    "PastConference",
    "RawPage",
    "Sme",
    "Source",
    "StrategicPillar",
    "Topic",
    # junctions
    "ConferenceAudience",
    "ConferencePillar",
    "ConferenceSme",
    "ConferenceTopic",
    "MessagingPillar",
    "SmeAudience",
    "SmeTopic",
    # vectors
    "DocumentChunk",
    "EmbeddingModel",
    # matching
    "Decision",
    "Match",
    "MatchTeamRecommendation",
    # audit
    "AuditLog",
    "ContentVersion",
    # ops
    "ChatMessage",
    "ChatSession",
    "IngestJob",
    "LLMCall",
    "Notification",
]
