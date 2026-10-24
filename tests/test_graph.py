from __future__ import annotations

import json

from conftest import make_paper
from research_cockpit.apis import CitationEdges, WorkMeta
from research_cockpit.graph import (
    build_graph,
    clusters,
    export_graph,
    gaps,
    to_networkx,
)


class FakeFetcher:
    """Stands in for EdgeFetcher; no network."""

    def __init__(self, edge_map: dict[str, CitationEdges]):
        self.edge_map = edge_map

    def resolve_seed(self, doc):
        return ("openalex", doc.openalex_id) if doc.openalex_id else None

    def edges(self, provider, provider_id):
        return self.edge_map.get(provider_id, CitationEdges())


def _library(store):
    a = make_paper(store, "Paper A", openalex_id="W1", doi="10.1/a")
    b = make_paper(store, "Paper B", openalex_id="W2", doi="10.1/b")
    edge_map = {
        "W1": CitationEdges(
            references=[
                WorkMeta(title="Paper B", openalex_id="W2", doi="10.1/b"),
                WorkMeta(title="External Classic", openalex_id="W99"),
            ],
            cited_by=[WorkMeta(title="Newer Followup", openalex_id="W50")],
        ),
        "W2": CitationEdges(
            references=[WorkMeta(title="External Classic", openalex_id="W99")],
        ),
    }
    return a, b, FakeFetcher(edge_map)


def test_build_resolves_internal_and_external(store):
    a, b, fetcher = _library(store)
    result = build_graph(store, fetcher)
    assert result.seeds == 2
    assert result.edges == 4
    g = to_networkx(store)
    assert g.has_edge(a.id, b.id)  # resolved internal edge
    assert g.has_edge(a.id, "W99") and g.has_edge(b.id, "W99")  # external stub shared
    assert g.has_edge("W50", a.id)  # cited-by direction
    assert g.nodes["W99"]["internal"] is False
    assert g.nodes[a.id]["internal"] is True


def test_build_skips_unresolvable_seed(store):
    make_paper(store, "No identifiers")
    result = build_graph(store, FakeFetcher({}))
    assert result.seeds == 0
    assert result.skipped == ["No identifiers"]


def test_build_is_idempotent(store):
    _, _, fetcher = _library(store)
    build_graph(store, fetcher)
    build_graph(store, fetcher)
    g = to_networkx(store)
    assert g.number_of_edges() == 4  # upsert, no duplicate edges


def test_clusters_and_gaps(store):
    a, _, fetcher = _library(store)
    build_graph(store, fetcher)
    g = to_networkx(store)
    communities = clusters(g)
    assert communities and sum(len(c) for c in communities) == g.number_of_nodes()

    suggestions = gaps(store, g=g)
    reasons = {s.node: s.reason for s in suggestions}
    assert reasons["W99"] == "not-in-library"
    assert reasons[a.id] == "to-read"  # in library but unread
    # W99 is cited by both library papers -> highest-centrality external node
    externals = [s for s in suggestions if s.reason == "not-in-library"]
    assert externals[0].node == "W99"


def test_export_formats(store, tmp_path):
    _, _, fetcher = _library(store)
    build_graph(store, fetcher)
    g = to_networkx(store)

    graphml = tmp_path / "g.graphml"
    export_graph(g, graphml)
    assert graphml.stat().st_size > 0

    dot = tmp_path / "g.dot"
    export_graph(g, dot)
    assert "digraph" in dot.read_text()

    jsonf = tmp_path / "g.json"
    export_graph(g, jsonf)
    data = json.loads(jsonf.read_text())
    assert len(data["nodes"]) == g.number_of_nodes()
