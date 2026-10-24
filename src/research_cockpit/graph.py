"""Citation graph: fetch edges (OpenAlex -> S2 fallback), build networkx graph,
detect clusters, surface gaps, export GraphML / DOT / JSON."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import networkx as nx

from .apis import CitationEdges, OpenAlexClient, S2Client, WorkMeta
from .store import Document, Store


@dataclass
class GraphBuildResult:
    seeds: int = 0
    edges: int = 0
    skipped: list[str] = None  # titles of seeds we couldn't resolve

    def __post_init__(self):
        if self.skipped is None:
            self.skipped = []


class EdgeFetcher:
    """OpenAlex default, Semantic Scholar fallback."""

    def __init__(self, openalex: OpenAlexClient | None = None, s2: S2Client | None = None):
        self.openalex = openalex or OpenAlexClient()
        self.s2 = s2 or S2Client()

    def resolve_seed(self, doc: Document) -> tuple[str, str] | None:
        """Returns (provider, provider_id) for a document, resolving via DOI if needed."""
        if doc.openalex_id:
            return ("openalex", doc.openalex_id)
        if doc.doi:
            meta = self.openalex.work_by_doi(doc.doi)
            if meta and meta.openalex_id:
                return ("openalex", meta.openalex_id)
        if doc.s2_id:
            return ("s2", doc.s2_id)
        if doc.doi:
            meta = self.s2.work_by_doi(doc.doi)
            if meta and meta.s2_id:
                return ("s2", meta.s2_id)
        return None

    def edges(self, provider: str, provider_id: str) -> CitationEdges:
        if provider == "openalex":
            return self.openalex.edges(provider_id)
        return self.s2.edges(provider_id)


def _ext_key(meta: WorkMeta) -> str | None:
    return meta.openalex_id or (f"doi:{meta.doi}" if meta.doi else None) or (
        f"s2:{meta.s2_id}" if meta.s2_id else None
    )


def _match_internal(store: Store, meta: WorkMeta) -> Document | None:
    if meta.openalex_id:
        doc = store.find_by_openalex(meta.openalex_id)
        if doc:
            return doc
    if meta.doi:
        return store.find_by_doi(meta.doi)
    return None


def build_graph(
    store: Store, fetcher: EdgeFetcher, seed: Document | None = None
) -> GraphBuildResult:
    """Fetch references + cited-by for seed paper(s); upsert edges + neighbor stubs.

    Depth is 1 from each seed (spec open item: depth>1 rarely worth the API volume).
    """
    seeds = [seed] if seed else store.list_documents(collection="papers")
    result = GraphBuildResult()
    for doc in seeds:
        resolved = fetcher.resolve_seed(doc)
        if resolved is None:
            result.skipped.append(doc.title or doc.id[:8])
            continue
        provider, provider_id = resolved
        if provider == "openalex" and not doc.openalex_id:
            store.update_document(doc.id, openalex_id=provider_id)
        edges = fetcher.edges(provider, provider_id)
        result.seeds += 1
        for meta in edges.references:
            result.edges += _upsert_edge(store, provider, citing_doc=doc, other=meta,
                                         doc_is_citing=True)
        for meta in edges.cited_by:
            result.edges += _upsert_edge(store, provider, citing_doc=doc, other=meta,
                                         doc_is_citing=False)
    return result


def _upsert_edge(
    store: Store, source: str, citing_doc: Document, other: WorkMeta, doc_is_citing: bool
) -> int:
    internal = _match_internal(store, other)
    ext = None if internal else _ext_key(other)
    if internal is None and ext is None:
        return 0
    if doc_is_citing:
        store.upsert_citation(
            source=source,
            citing_id=citing_doc.id,
            cited_id=internal.id if internal else None,
            cited_ext=ext,
            cited_title=other.title,
        )
    else:
        store.upsert_citation(
            source=source,
            citing_id=internal.id if internal else None,
            citing_ext=ext,
            citing_title=other.title,
            cited_id=citing_doc.id,
        )
    return 1


# ------------------------------------------------------------------ analysis


def to_networkx(store: Store) -> nx.DiGraph:
    g = nx.DiGraph()
    for doc in store.list_documents(collection="papers"):
        g.add_node(doc.id, title=doc.title or "Untitled", internal=True,
                   status=doc.status or "")
    for row in store.citations():
        citing = row["citing_id"] or row["citing_ext"]
        cited = row["cited_id"] or row["cited_ext"]
        if not citing or not cited:
            continue
        for node, title in ((citing, row["citing_title"]), (cited, row["cited_title"])):
            if node not in g:
                g.add_node(node, title=title or node, internal=False, status="")
        g.add_edge(citing, cited)
    return g


def clusters(g: nx.DiGraph) -> list[list[str]]:
    """Community detection (greedy modularity) on the undirected projection."""
    ug = g.to_undirected()
    ug.remove_nodes_from(list(nx.isolates(ug)))
    if ug.number_of_nodes() == 0:
        return []
    communities = nx.community.greedy_modularity_communities(ug)
    return [sorted(c, key=lambda n: -ug.degree(n)) for c in communities]


@dataclass
class GapSuggestion:
    node: str
    title: str
    centrality: float
    reason: str  # "not-in-library" | "to-read"


def gaps(store: Store, g: nx.DiGraph | None = None, limit: int = 15) -> list[GapSuggestion]:
    """High-centrality papers you don't have (or haven't read) - the reading queue."""
    g = g if g is not None else to_networkx(store)
    if g.number_of_nodes() == 0:
        return []
    centrality = nx.pagerank(g) if g.number_of_edges() else {}
    suggestions = []
    for node, data in g.nodes(data=True):
        score = centrality.get(node, 0.0)
        if not data.get("internal"):
            suggestions.append(GapSuggestion(node, data.get("title", node), score,
                                             "not-in-library"))
        elif data.get("status") == "to-read":
            suggestions.append(GapSuggestion(node, data.get("title", node), score, "to-read"))
    suggestions.sort(key=lambda s: -s.centrality)
    return suggestions[:limit]


# -------------------------------------------------------------------- export


def export_graph(g: nx.DiGraph, path: Path) -> None:
    path = Path(path)
    suffix = path.suffix.lower()
    if suffix == ".graphml":
        nx.write_graphml(g, path)
    elif suffix == ".dot":
        lines = ["digraph citations {"]
        for node, data in g.nodes(data=True):
            title = (data.get("title") or node).replace('"', "'")
            shape = "box" if data.get("internal") else "ellipse"
            lines.append(f'  "{node}" [label="{title}", shape={shape}];')
        for u, v in g.edges():
            lines.append(f'  "{u}" -> "{v}";')
        lines.append("}")
        path.write_text("\n".join(lines))
    elif suffix == ".json":
        data = nx.node_link_data(g, edges="links")
        path.write_text(json.dumps(data, indent=2))
    else:
        raise ValueError(f"Unsupported export format '{suffix}' (use .graphml/.dot/.json)")
