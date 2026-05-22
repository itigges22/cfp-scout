"""In-memory graph loader with 60s TTL cache (plan 16).

The loader assembles a NetworkX undirected graph from Postgres junction
tables. Nodes are typed via a ``kind`` attribute; edges carry ``relation``
+ optional ``weight``/``score``. Every node also carries enough display
metadata (name, slug/status/etc) that downstream queries + viz don't have
to re-hit the DB.

Cache contract:
  * One graph per process, no per-user variant.
  * TTL = 60s — long enough to coalesce a burst of reads after a write,
    short enough that an admin staring at /diagnostics doesn't see badly
    stale data.
  * :func:`invalidate` drops the cache. Every service path that mutates
    a junction row calls it.

Refuses to load graphs above a hard cap (currently 50k nodes / 200k edges)
so a runaway Postgres situation can't OOM the api process.
"""

from __future__ import annotations

import asyncio
import time
from typing import Any

import networkx as nx
import structlog
from sqlalchemy import select

from app.db.models.entities import (
    AudienceProfile,
    Conference,
    ConferenceSeries,
    ConferenceSource,
    MessagingDocument,
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
from app.db.session import get_session_factory

log = structlog.get_logger("scout.graph.loader")

CACHE_TTL_SECONDS = 60.0
MAX_NODES = 50_000
MAX_EDGES = 200_000

_cache: nx.Graph | None = None
_cached_at: float = 0.0
_load_lock = asyncio.Lock()


def invalidate() -> None:
    """Drop the cached graph so the next ``load_graph`` rebuilds.

    Cheap to call from anywhere — the cache is a module-level pair of
    variables.
    """
    global _cache, _cached_at
    _cache = None
    _cached_at = 0.0


async def load_graph(*, force: bool = False) -> nx.Graph:
    """Return the cached graph or rebuild if stale.

    ``force=True`` bypasses the TTL check (used by admin endpoints when an
    operator wants a fresh look without waiting for invalidation).
    """
    global _cache, _cached_at
    now = time.monotonic()
    if not force and _cache is not None and (now - _cached_at) < CACHE_TTL_SECONDS:
        return _cache

    async with _load_lock:
        # Re-check after lock — another coroutine may have rebuilt.
        if not force and _cache is not None and (time.monotonic() - _cached_at) < CACHE_TTL_SECONDS:
            return _cache

        graph = await _build_graph()
        _cache = graph
        _cached_at = time.monotonic()
        log.info(
            "graph.loaded",
            nodes=graph.number_of_nodes(),
            edges=graph.number_of_edges(),
        )
        return graph


async def _build_graph() -> nx.Graph:
    """Read all entities + junctions and assemble the graph in one go."""
    graph: nx.Graph = nx.Graph()

    async with get_session_factory()() as session:
        # ---- Nodes ---------------------------------------------------
        # Conferences (excluding quarantined — they're inert to matching).
        confs = (
            await session.execute(
                select(Conference).where(Conference.status != "quarantined")
            )
        ).scalars().all()
        for c in confs:
            graph.add_node(
                _nid("conference", c.id),
                kind="conference",
                label=c.name,
                slug=c.slug,
                status=c.status,
                start_date=c.start_date.isoformat() if c.start_date else None,
                confidence=c.confidence_score,
            )

        # Topics — both active + pending; matcher ignores pending, but the
        # viz benefits from seeing them so admins can spot proliferating
        # LLM-discovered noise.
        topics = (await session.execute(select(Topic))).scalars().all()
        for t in topics:
            graph.add_node(
                _nid("topic", t.id),
                kind="topic",
                label=t.name,
                slug=t.slug,
                is_active=t.is_active,
                pending_review=t.pending_review,
            )

        # SMEs (active only).
        smes = (
            await session.execute(select(Sme).where(Sme.is_active.is_(True)))
        ).scalars().all()
        for s in smes:
            graph.add_node(
                _nid("sme", s.id),
                kind="sme",
                label=s.full_name,
                team=s.team,
            )

        # Audiences (active only).
        auds = (
            await session.execute(
                select(AudienceProfile).where(AudienceProfile.is_active.is_(True))
            )
        ).scalars().all()
        for a in auds:
            graph.add_node(
                _nid("audience", a.id),
                kind="audience",
                label=a.name,
                industry=a.industry,
                role_seniority=a.role_seniority,
            )

        # Pillars.
        pillars = (await session.execute(select(StrategicPillar))).scalars().all()
        for p in pillars:
            graph.add_node(
                _nid("pillar", p.id),
                kind="pillar",
                label=p.name,
                display_order=p.display_order,
            )

        # Messaging documents (active only).
        msgs = (
            await session.execute(
                select(MessagingDocument).where(MessagingDocument.is_active.is_(True))
            )
        ).scalars().all()
        for m in msgs:
            graph.add_node(
                _nid("messaging", m.id),
                kind="messaging",
                label=m.title,
            )

        # Sources.
        srcs = (
            await session.execute(select(Source).where(Source.enabled.is_(True)))
        ).scalars().all()
        for src in srcs:
            graph.add_node(
                _nid("source", src.id),
                kind="source",
                label=src.name,
                source_kind=src.kind,
            )

        # Conference series.
        series_rows = (await session.execute(select(ConferenceSeries))).scalars().all()
        for cs in series_rows:
            graph.add_node(
                _nid("series", cs.id),
                kind="series",
                label=cs.name,
            )

        # ---- Hard cap check (nodes) ----------------------------------
        if graph.number_of_nodes() > MAX_NODES:
            raise RuntimeError(
                f"Refusing to build graph: {graph.number_of_nodes()} nodes "
                f"exceeds MAX_NODES={MAX_NODES}."
            )

        # ---- Edges ---------------------------------------------------
        # Helper: only add edge if BOTH endpoints exist as typed nodes,
        # otherwise add_edge would silently materialize an unlabeled node
        # (e.g. an inactive SME referenced from sme_topics).
        def _safe_add_edge(u: str, v: str, **attrs: Any) -> None:
            if u in graph and v in graph:
                graph.add_edge(u, v, **attrs)

        # Conference <-> Topic
        for row in (await session.execute(select(ConferenceTopic))).scalars():
            _safe_add_edge(
                _nid("conference", row.conference_id),
                _nid("topic", row.topic_id),
                relation="ABOUT",
                weight=float(row.weight),
            )

        # Conference <-> Audience
        for row in (await session.execute(select(ConferenceAudience))).scalars():
            _safe_add_edge(
                _nid("conference", row.conference_id),
                _nid("audience", row.audience_id),
                relation="TARGETS",
                weight=float(row.weight),
            )

        # Conference <-> Pillar
        for row in (await session.execute(select(ConferencePillar))).scalars():
            _safe_add_edge(
                _nid("conference", row.conference_id),
                _nid("pillar", row.pillar_id),
                relation="ALIGNS_WITH",
                weight=float(row.score),
            )

        # Conference <-> SME (matcher-computed)
        for row in (await session.execute(select(ConferenceSme))).scalars():
            _safe_add_edge(
                _nid("conference", row.conference_id),
                _nid("sme", row.sme_id),
                relation="SUITS",
                weight=float(row.score),
            )

        # Conference <-> Source (via conference_sources junction)
        for row in (await session.execute(select(ConferenceSource))).scalars():
            # raw_page_id -> source_id requires a join; do it cheaply here.
            # (Could pre-join in the select, but the loop is small.)
            pass
        # The conference_sources junction maps conference -> raw_page; we
        # roll up to source via raw_page.source_id. Fetch the rollup in a
        # single query.
        from app.db.models.entities import RawPage  # local: avoid top-level cycle risk

        rollup_q = await session.execute(
            select(ConferenceSource.conference_id, RawPage.source_id)
            .join(RawPage, RawPage.id == ConferenceSource.raw_page_id)
        )
        for conf_id, src_id in rollup_q.all():
            _safe_add_edge(
                _nid("conference", conf_id),
                _nid("source", src_id),
                relation="DERIVED_FROM",
                weight=1.0,
            )

        # Conference -> Series (FK on conferences.series_id)
        for c in confs:
            if c.series_id:
                _safe_add_edge(
                    _nid("conference", c.id),
                    _nid("series", c.series_id),
                    relation="EDITION_OF",
                    weight=1.0,
                )

        # SME <-> Topic
        for row in (await session.execute(select(SmeTopic))).scalars():
            _safe_add_edge(
                _nid("sme", row.sme_id),
                _nid("topic", row.topic_id),
                relation="EXPERT_IN",
                weight=float(row.weight),
            )

        # SME <-> Audience
        for row in (await session.execute(select(SmeAudience))).scalars():
            _safe_add_edge(
                _nid("sme", row.sme_id),
                _nid("audience", row.audience_id),
                relation="SPEAKS_TO",
                weight=float(row.weight),
            )

        # Messaging <-> Pillar
        for row in (await session.execute(select(MessagingPillar))).scalars():
            _safe_add_edge(
                _nid("messaging", row.messaging_document_id),
                _nid("pillar", row.pillar_id),
                relation="SUPPORTS",
                weight=float(row.weight),
            )

        if graph.number_of_edges() > MAX_EDGES:
            raise RuntimeError(
                f"Refusing to build graph: {graph.number_of_edges()} edges "
                f"exceeds MAX_EDGES={MAX_EDGES}."
            )

    return graph


def _nid(kind: str, raw_id: Any) -> str:
    """Compose a canonical node id: ``<kind>:<uuid>``.

    Including the kind prefix means we never accidentally collide two
    nodes with the same UUID across tables (extremely unlikely with
    UUIDv4 anyway, but cheap defense).
    """
    return f"{kind}:{raw_id}"
