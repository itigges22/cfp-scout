"""Conference series tracking (plan 23).

Public surface:
  * :func:`suggest_series_for_unlinked` — detector run; returns ranked
    (conference, series, confidence) suggestions.
  * :func:`assign_conference_to_series`  — record the link + trigger a
    matcher recompute for the affected conference.
  * :func:`unassign_conference_from_series`
  * :func:`create_series` / :func:`update_series` / :func:`deactivate_series`

No automatic linking — series membership is too consequential for the SME
matcher's past-attendance bonus to assign without human confirmation. The
detector only suggests; the API caller commits.
"""

from app.services.series.crud import (
    assign_conference_to_series,
    create_series,
    deactivate_series,
    unassign_conference_from_series,
    update_series,
)
from app.services.series.detector import (
    SeriesSuggestion,
    suggest_series_for_unlinked,
)

__all__ = [
    "SeriesSuggestion",
    "assign_conference_to_series",
    "create_series",
    "deactivate_series",
    "suggest_series_for_unlinked",
    "unassign_conference_from_series",
    "update_series",
]
