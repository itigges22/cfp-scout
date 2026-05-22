"""/api/v1/graph — knowledge-graph viz + queries (plan 16).

Read-only routes. The graph is built from already-validated data and the
viz strips text content (chunks, full descriptions) — only display labels +
edge weights leave the api.

Endpoints:
  * ``GET /graph/full``                    — bounded full-graph payload
  * ``GET /graph/neighborhood``            — subgraph around a node
  * ``GET /graph/candidate-smes/{cid}``    — top-K SME picks for a conference
  * ``GET /graph/upcoming/{sme_id}``       — upcoming conferences for an SME
  * ``GET /graph/pillar-coverage``         — per-pillar counts
  * ``POST /graph/invalidate``             — admin: drop the cache
"""

from __future__ import annotations

from dataclasses import asdict
from uuid import UUID

import structlog
from fastapi import APIRouter, HTTPException, Query, status

from app.services.graph import (
    candidate_smes_for_conference,
    invalidate,
    load_graph,
    neighborhood,
    pillar_coverage,
    to_node_link,
    upcoming_conferences_for_sme,
)
from app.services.graph.query import full_graph_for_view

log = structlog.get_logger("scout.api.graph")
router = APIRouter(prefix="/api/v1/graph", tags=["graph"])


@router.get("/full")
async def full(
    kinds: list[str] | None = Query(default=None, description="Filter by node kind(s)."),
    max_nodes: int = Query(default=500, ge=10, le=2000),
) -> dict:
    """Bounded full-graph payload for the dashboard explorer (plan 21).

    If the filtered graph exceeds ``max_nodes``, we trim to the highest-degree
    subset and set ``stats.truncated=true`` in the response.
    """
    graph = await load_graph()
    sub, truncated = full_graph_for_view(
        graph,
        kinds=set(kinds) if kinds else None,
        max_nodes=max_nodes,
    )
    return to_node_link(sub, truncated=truncated)


@router.get("/neighborhood")
async def neighborhood_route(
    node_id: str = Query(..., description="e.g. 'conference:<uuid>', 'sme:<uuid>'"),
    depth: int = Query(default=2, ge=1, le=4),
) -> dict:
    """Subgraph within ``depth`` hops of ``node_id``. 404 if the node isn't
    present (possibly invalidated, possibly never loaded)."""
    graph = await load_graph()
    if node_id not in graph:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Node {node_id!r} not in the graph. "
            "Was it created since the last graph build? Try POST /graph/invalidate.",
        )
    sub = neighborhood(graph, node_id, depth=depth)
    return to_node_link(sub)


@router.get("/candidate-smes/{conference_id}")
async def candidate_smes(
    conference_id: UUID,
    k: int = Query(default=5, ge=1, le=50),
) -> dict:
    """Top-K SMEs by graph-overlap score for this conference. Pure graph
    signal — plan 18 adds bio similarity on top."""
    graph = await load_graph()
    results = candidate_smes_for_conference(graph, str(conference_id), k=k)
    return {
        "conference_id": str(conference_id),
        "k": k,
        "candidates": [asdict(r) for r in results],
    }


@router.get("/upcoming/{sme_id}")
async def upcoming_for_sme(
    sme_id: UUID,
    days: int = Query(default=180, ge=1, le=730),
) -> dict:
    """Upcoming conferences in the next ``days`` for this SME, via their
    topic + audience connections."""
    graph = await load_graph()
    results = upcoming_conferences_for_sme(graph, str(sme_id), days=days)
    return {
        "sme_id": str(sme_id),
        "days": days,
        "conferences": [asdict(r) for r in results],
    }


@router.get("/pillar-coverage")
async def pillar_coverage_route() -> dict:
    """Per-pillar count of attached conferences + messaging documents."""
    graph = await load_graph()
    results = pillar_coverage(graph)
    return {"coverage": [asdict(r) for r in results]}


@router.post("/invalidate", status_code=status.HTTP_204_NO_CONTENT)
async def invalidate_route() -> None:
    """Admin: drop the in-memory graph so the next read rebuilds. Useful
    after bulk loads (XLSX import, batch scrape) when the 60s TTL would
    otherwise force a stale read."""
    invalidate()
    log.info("graph.invalidate.manual")
    return None
