"""Typed graph query helpers (plan 16).

Every helper takes the loaded graph + parameters, returns a typed result.
They're synchronous because once the graph is in RAM the work is pure
Python; the async work is in :func:`app.services.graph.loader.load_graph`.

Helpers ordered by likely consumer (admin/matcher/dashboard).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from uuid import UUID

import networkx as nx


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------
@dataclass(slots=True, frozen=True)
class CandidateSme:
    sme_id: str
    label: str
    team: str | None
    score: float  # 0..1 graph-overlap score; matcher (plan 18) refines this


@dataclass(slots=True, frozen=True)
class UpcomingConference:
    conference_id: str
    label: str
    slug: str
    start_date: str | None
    confidence: float | None


@dataclass(slots=True, frozen=True)
class PillarCoverage:
    pillar_id: str
    label: str
    display_order: int
    conferences: int
    messaging_documents: int


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def candidate_smes_for_conference(
    graph: nx.Graph, conference_id: str | UUID, *, k: int = 5
) -> list[CandidateSme]:
    """Rank SMEs by combined topic + audience overlap with this conference.

    Pure graph signal — no embedding similarity, no LLM. Plan 18 layers
    bio similarity on top to produce the final per-conference SME score.

    Algorithm:
      1. From the conference node, walk to topic + audience neighbors.
      2. For each neighbor, walk to its SME neighbors.
      3. Score each candidate SME = (# topic overlaps) + (# audience overlaps).
      4. Normalize by the max possible (n_topics + n_audiences on the conf).
    """
    conf_node = f"conference:{conference_id}"
    if conf_node not in graph:
        return []

    topic_nbrs: set[str] = set()
    aud_nbrs: set[str] = set()
    for n in graph.neighbors(conf_node):
        kind = graph.nodes[n].get("kind")
        if (
            kind == "topic"
            and graph.nodes[n].get("is_active")
            and not graph.nodes[n].get("pending_review")
        ):
            topic_nbrs.add(n)
        elif kind == "audience":
            aud_nbrs.add(n)

    if not topic_nbrs and not aud_nbrs:
        return []

    scores: dict[str, float] = {}
    for tn in topic_nbrs:
        for nbr in graph.neighbors(tn):
            if graph.nodes[nbr].get("kind") == "sme":
                w = graph[tn][nbr].get("weight", 1.0)
                scores[nbr] = scores.get(nbr, 0.0) + w

    for an in aud_nbrs:
        for nbr in graph.neighbors(an):
            if graph.nodes[nbr].get("kind") == "sme":
                w = graph[an][nbr].get("weight", 1.0)
                scores[nbr] = scores.get(nbr, 0.0) + w

    # Normalize: max plausible is one full-weight edge per topic + audience.
    denom = max(1.0, float(len(topic_nbrs) + len(aud_nbrs)))
    ranked = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)[:k]
    return [
        CandidateSme(
            sme_id=node.split(":", 1)[1],
            label=graph.nodes[node]["label"],
            team=graph.nodes[node].get("team"),
            score=round(raw / denom, 3),
        )
        for node, raw in ranked
    ]


def upcoming_conferences_for_sme(
    graph: nx.Graph,
    sme_id: str | UUID,
    *,
    days: int = 180,
    today: date | None = None,
) -> list[UpcomingConference]:
    """Conferences within ``days`` of today that this SME's topics or
    audiences touch.

    Used by the SME detail page (plan 20). Does not require the matcher
    junction to be populated; this is a purely structural recommendation.
    """
    today = today or date.today()
    horizon = today + timedelta(days=days)
    sme_node = f"sme:{sme_id}"
    if sme_node not in graph:
        return []

    # Sets of topic + audience nodes this SME connects to.
    topics = {n for n in graph.neighbors(sme_node) if graph.nodes[n].get("kind") == "topic"}
    auds = {n for n in graph.neighbors(sme_node) if graph.nodes[n].get("kind") == "audience"}

    candidates: set[str] = set()
    for n in topics | auds:
        for nbr in graph.neighbors(n):
            if graph.nodes[nbr].get("kind") == "conference":
                candidates.add(nbr)

    out: list[UpcomingConference] = []
    for cnode in candidates:
        data = graph.nodes[cnode]
        sd_str = data.get("start_date")
        if sd_str:
            try:
                sd = date.fromisoformat(sd_str)
            except ValueError:
                continue
            if not (today <= sd <= horizon):
                continue
        out.append(
            UpcomingConference(
                conference_id=cnode.split(":", 1)[1],
                label=data["label"],
                slug=data["slug"],
                start_date=sd_str,
                confidence=data.get("confidence"),
            )
        )
    out.sort(key=lambda c: c.start_date or "")
    return out


def pillar_coverage(graph: nx.Graph) -> list[PillarCoverage]:
    """Count conferences + messaging documents per pillar.

    Used by /diagnostics + the dashboard to surface coverage gaps.
    Ordered by ``display_order`` so the four pillars render in their
    canonical sequence.
    """
    out: list[PillarCoverage] = []
    for node, data in graph.nodes(data=True):
        if data.get("kind") != "pillar":
            continue
        confs = 0
        msgs = 0
        for nbr in graph.neighbors(node):
            kind = graph.nodes[nbr].get("kind")
            if kind == "conference":
                confs += 1
            elif kind == "messaging":
                msgs += 1
        out.append(
            PillarCoverage(
                pillar_id=node.split(":", 1)[1],
                label=data["label"],
                display_order=int(data.get("display_order") or 0),
                conferences=confs,
                messaging_documents=msgs,
            )
        )
    out.sort(key=lambda p: p.display_order)
    return out


def neighborhood(graph: nx.Graph, node_id: str, *, depth: int = 2) -> nx.Graph:
    """Return the subgraph within ``depth`` hops of ``node_id``.

    Used by the conference-detail viz (plan 20) and the explorer (plan 21).
    Returns an empty graph if ``node_id`` doesn't exist.
    """
    if node_id not in graph:
        return nx.Graph()
    nodes = nx.single_source_shortest_path_length(graph, node_id, cutoff=depth).keys()
    return graph.subgraph(nodes).copy()


def full_graph_for_view(
    graph: nx.Graph,
    *,
    kinds: set[str] | None = None,
    status_in: set[str] | None = None,
    since_iso: str | None = None,
    max_nodes: int = 500,
) -> tuple[nx.Graph, bool]:
    """Return a bounded subgraph for the dashboard's full-graph explorer.

    Filter order (apply, then cap):
      1. ``status_in`` (conference-only) — drop conference nodes whose
         ``status`` attribute isn't in the set. Edges to dropped nodes
         disappear automatically when we ``subgraph`` to the survivors.
      2. ``since_iso`` (conference-only) — drop conferences with
         ``start_date < since_iso`` (lexical compare is fine on ISO dates).
         Conferences without a start_date are kept (TBD-dated events).
      3. ``kinds`` — keep only nodes of the requested kinds.
      4. ``max_nodes`` — if still over, keep the highest-degree N.

    Returns ``(subgraph, truncated)``.
    """
    keep: set[str] = set()
    for n, d in graph.nodes(data=True):
        kind = d.get("kind")
        if kind == "conference":
            if status_in is not None and d.get("status") not in status_in:
                continue
            if since_iso is not None:
                sd = d.get("start_date")
                if sd is not None and sd < since_iso:
                    continue
        if kinds is not None and kind not in kinds:
            continue
        keep.add(n)

    filtered = graph.subgraph(keep).copy()

    if filtered.number_of_nodes() <= max_nodes:
        return filtered, False

    by_degree = sorted(
        filtered.nodes(),
        key=lambda n: filtered.degree(n),
        reverse=True,
    )[:max_nodes]
    return filtered.subgraph(by_degree).copy(), True
