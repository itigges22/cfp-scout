"""Fit matcher (plan 17).

Three-stage gate that turns extracted conferences into ranked, justified
recommendations:

  Stage A — messaging fit  (cosine sim of conference chunks vs messaging chunks)
  Stage B — pillar alignment (cosine sim vs strategic pillar descriptions)
  Stage C — SME match       (graph overlap; plan 18 layers bio similarity)

Overall score = weighted sum of the three; rationale produced by one LLM
call. Persisted in ``app.matches`` keyed by (conference_id, algorithm_version).

Public surface:
  * :func:`run_fit_match`     — full pipeline for one conference
  * :class:`MatchResult`      — typed return
  * :data:`ALGORITHM_VERSION` — bump when scoring code changes
"""

from app.services.matcher.pipeline import (
    ALGORITHM_VERSION,
    MatchResult,
    run_fit_match,
)

__all__ = ["ALGORITHM_VERSION", "MatchResult", "run_fit_match"]
