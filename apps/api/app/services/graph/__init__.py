"""Knowledge graph package (plan 16).

NetworkX-backed in-memory graph over the Postgres junction tables. Facts
live in Postgres; the graph is derived in RAM with a 60-second TTL cache.

Public surface:
  * :func:`load_graph` — returns the cached :class:`networkx.Graph`,
    rebuilding it if the TTL has expired.
  * :func:`invalidate` — drops the cached graph so the next ``load_graph``
    re-reads Postgres. Called by every service that mutates a junction
    row (SME create/update, extraction pipeline, etc).
  * :func:`to_node_link` — JSON-serializable node-link payload for the
    frontend viz endpoints.
  * Query helpers from :mod:`.query` — see that module's docstring.
"""

from app.services.graph.loader import invalidate, load_graph
from app.services.graph.query import (
    candidate_smes_for_conference,
    full_graph_for_view,
    neighborhood,
    pillar_coverage,
    upcoming_conferences_for_sme,
)
from app.services.graph.viz import to_node_link

__all__ = [
    "candidate_smes_for_conference",
    "full_graph_for_view",
    "invalidate",
    "load_graph",
    "neighborhood",
    "pillar_coverage",
    "to_node_link",
    "upcoming_conferences_for_sme",
]
