"""Retrieval + prompt assembly + citation formatting."""

from __future__ import annotations

from dataclasses import dataclass, field

from .embed import Embedder
from .llm import LLMAdapter
from .store import Chunk, Document, Store

SCOPES = {"papers": ("papers",), "notes": ("notes",), "all": ("papers", "notes")}

SYSTEM_BASE = (
    "You are a careful research assistant answering questions about the user's"
    " personal library. Answer ONLY from the numbered context passages provided."
    " Cite every claim with the passage marker(s) it comes from, e.g. [2] or"
    " [1][3]. If the context does not contain the answer, say so plainly -"
    " never invent facts or citations."
)

SYSTEM_SYNTHESIZE = SYSTEM_BASE + (
    " Synthesize across the sources: compare and contrast their positions,"
    " methods, and results. Where sources disagree, flag the contradiction"
    " explicitly in a 'Contradictions' section (or state that none were found)."
)

SYSTEM_GAPS = (
    "You are a research-coverage auditor. The numbered passages are everything"
    " the user's library retrieved on the topic. Identify what the corpus does"
    " NOT cover on this topic: missing subtopics, methods, populations, or"
    " counter-arguments. Be concrete. Where a passage partially covers"
    " something, cite it with its [n] marker. If a list of citation-graph gap"
    " candidates is provided, note which of them would fill the gaps."
)


@dataclass
class Source:
    n: int
    document_id: str
    title: str
    page: int | None
    score: float


@dataclass
class Answer:
    text: str
    sources: list[Source] = field(default_factory=list)

    def render_sources(self) -> str:
        lines = []
        for s in self.sources:
            page = f", p.{s.page}" if s.page else ""
            lines.append(f"[{s.n}] {s.title}{page} ({s.document_id[:8]})")
        return "\n".join(lines)


def search(
    store: Store,
    embedder: Embedder,
    query: str,
    scope: str = "papers",
    tag: str | None = None,
    status: str | None = None,
    project: str | None = None,
    k: int = 8,
    retrieval: str = "dense",
    do_rerank: bool = False,
) -> list[tuple[Chunk, Document, float]]:
    if scope not in SCOPES:
        raise ValueError(f"scope must be one of {sorted(SCOPES)}")
    if k <= 0 or not query.strip():
        return []
    collections = SCOPES[scope]
    if retrieval == "hybrid":
        from .retrieval import hybrid_search

        return hybrid_search(
            store, embedder, query, k=k, collections=collections,
            tag=tag, status=status, project=project, mode="hybrid", do_rerank=do_rerank,
        )
    query_vec = embedder.encode([query])[0]
    return store.search_chunks(
        query_vec, k=k, collections=collections, tag=tag, status=status, project=project
    )


def build_prompt(
    question: str,
    hits: list[tuple[Chunk, Document, float]],
    mode: str = "ask",
    gap_candidates: list[str] | None = None,
) -> tuple[str, str, list[Source]]:
    """Returns (system, prompt, sources)."""
    system = {"ask": SYSTEM_BASE, "synthesize": SYSTEM_SYNTHESIZE, "gaps": SYSTEM_GAPS}[mode]
    sources, context_parts = [], []
    for n, (chunk, doc, score) in enumerate(hits, start=1):
        title = doc.title or "Untitled"
        page = f", p.{chunk.page}" if chunk.page else ""
        context_parts.append(f"[{n}] ({title}{page})\n{chunk.text}")
        sources.append(
            Source(n=n, document_id=doc.id, title=title, page=chunk.page, score=score)
        )
    context = "\n\n".join(context_parts) if context_parts else "(no passages retrieved)"
    parts = [f"Context passages:\n\n{context}"]
    if mode == "gaps" and gap_candidates:
        candidates = "\n".join(f"- {c}" for c in gap_candidates)
        parts.append(
            "Citation-graph gap candidates (high-centrality, not in library):\n"
            + candidates
        )
    label = "Topic to audit for coverage gaps" if mode == "gaps" else "Question"
    parts.append(f"{label}: {question}")
    return system, "\n\n".join(parts), sources


def ask(
    store: Store,
    embedder: Embedder,
    adapter: LLMAdapter,
    question: str,
    scope: str = "papers",
    tag: str | None = None,
    status: str | None = None,
    project: str | None = None,
    k: int = 8,
    mode: str = "ask",
    gap_candidates: list[str] | None = None,
    retrieval: str = "dense",
    do_rerank: bool = False,
) -> Answer:
    if mode == "synthesize":
        k = max(k, 12)  # synthesis wants breadth across documents
    hits = search(store, embedder, question, scope=scope, tag=tag, status=status,
                  project=project, k=k, retrieval=retrieval, do_rerank=do_rerank)
    system, prompt, sources = build_prompt(question, hits, mode, gap_candidates)
    if not hits and mode != "gaps":
        return Answer(text="No matching passages found in the selected scope.", sources=[])
    text = adapter.generate(prompt, system=system)
    # keep only sources the model actually cited (gaps mode keeps all for context)
    if mode != "gaps":
        cited = [s for s in sources if f"[{s.n}]" in text]
        sources = cited or sources
    return Answer(text=text, sources=sources)
