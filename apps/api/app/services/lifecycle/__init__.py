"""Data lifecycle (plan 25).

Two unrelated-but-coresident features:

  * **Ebbinghaus decay** — exponential freshness on chunks + conferences.
    Daily cron updates ``conferences.freshness_score``; chunk freshness is
    computed on-the-fly during retrieval (cheap + always fresh, no
    bulk-update needed). Gated by ``settings.decay_enabled``.

  * **Content versioning** — every UPDATE to a versioned entity writes an
    ``audit.content_versions`` row with the field-level diff. SQLAlchemy
    event listener is the source of truth; feature code can't bypass it.
"""

from app.services.lifecycle.decay import (
    CHUNK_HALF_LIFE_DAYS,
    CONFERENCE_HALF_LIFE_DAYS,
    DECAY_ALPHA,
    apply_decay_multiplier,
    compute_freshness,
    run_decay_pass,
)
from app.services.lifecycle.versioning import (
    VERSIONED_ENTITY_TYPES,
    register_versioning_listeners,
    set_actor_label,
)

__all__ = [
    "CHUNK_HALF_LIFE_DAYS",
    "CONFERENCE_HALF_LIFE_DAYS",
    "DECAY_ALPHA",
    "apply_decay_multiplier",
    "compute_freshness",
    "run_decay_pass",
    "VERSIONED_ENTITY_TYPES",
    "register_versioning_listeners",
    "set_actor_label",
]
