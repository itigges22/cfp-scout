"""Node-link JSON formatter for the viz endpoints (plan 16).

Frontend graph libraries (cytoscape, vis-network, react-force-graph) all
consume some flavor of ``{nodes: [...], edges: [...]}``. We use a small,
explicit shape so the consumer doesn't have to know about NetworkX:

    {
      "nodes": [{"id": "topic:abc", "kind": "topic", "label": "RAG", ...}, ...],
      "links": [{"source": "...", "target": "...", "relation": "ABOUT", "weight": 1.0}, ...]
    }

No PII, no chunk text — only the display metadata already attached to
node attributes in :mod:`.loader`. Edge weights/scores are surfaced for
the matcher debug view but rounded for compactness.
"""

from __future__ import annotations

from typing import Any

import networkx as nx


def to_node_link(graph: nx.Graph, *, truncated: bool = False) -> dict[str, Any]:
    """Serialize ``graph`` to a JSON-friendly node-link payload."""
    nodes: list[dict[str, Any]] = []
    for node, data in graph.nodes(data=True):
        n: dict[str, Any] = {"id": node, **{k: v for k, v in data.items() if v is not None}}
        nodes.append(n)

    links: list[dict[str, Any]] = []
    for u, v, data in graph.edges(data=True):
        edge: dict[str, Any] = {"source": u, "target": v}
        edge.update(data)
        if "weight" in edge:
            edge["weight"] = round(float(edge["weight"]), 3)
        links.append(edge)

    return {
        "nodes": nodes,
        "links": links,
        "stats": {
            "n_nodes": graph.number_of_nodes(),
            "n_edges": graph.number_of_edges(),
            "truncated": truncated,
        },
    }
