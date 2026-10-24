"""Hybrid retrieval + rerank (M11): FTS5 keyword search, dense cosine search,
Reciprocal Rank Fusion, and optional local cross-encoder reranking.

Dense-only remains selectable via config (`rag.retrieval = dense`). The
reranker (`rag.rerank = true`) downloads `BAAI/bge-reranker-base` on first
use (lazy + local thereafter).
"""

from __future__ import annotations

import re
from typing import Any

import numpy as np

from .embed import Embedder
from .store import Chunk, Document, Store, blob_to_embed

FTS_TABLE = "chunks_fts"
FTS_DDL = f"""
CREATE VIRTUAL TABLE IF NOT EXISTS {FTS_TABLE}
    USING fts5(chunk_id, text);
CREATE TRIGGER IF NOT EXISTS chunks_fts_insert AFTER INSERT ON chunks BEGIN
    INSERT INTO {FTS_TABLE} (chunk_id, text) VALUES (new.id, new.text);
END;
CREATE TRIGGER IF NOT EXISTS chunks_fts_delete AFTER DELETE ON chunks BEGIN
    DELETE FROM {FTS_TABLE} WHERE chunk_id = old.id;
END;
CREATE TRIGGER IF NOT EXISTS chunks_fts_update AFTER UPDATE OF id, text ON chunks BEGIN
    DELETE FROM {FTS_TABLE} WHERE chunk_id = old.id;
    INSERT INTO {FTS_TABLE} (chunk_id, text) VALUES (new.id, new.text);
END;
"""


def _ensure_fts(store: Store) -> None:
    """Install synchronization triggers and rebuild legacy, possibly stale indexes."""
    existing = store.conn.execute(
        "SELECT name FROM sqlite_master WHERE type='trigger' AND name='chunks_fts_insert'"
    ).fetchone()
    if not existing:
        store.conn.executescript(FTS_DDL)
        _rebuild_fts(store)


def _rebuild_fts(store: Store) -> None:
    store.conn.execute(f"DELETE FROM {FTS_TABLE}")
    store.conn.execute(
        f"INSERT INTO {FTS_TABLE} (chunk_id, text) SELECT id, text FROM chunks"
    )
    store.conn.commit()


def sync_fts_insert(store: Store, chunks: list[Chunk]) -> None:
    """Call after add_chunks to keep the FTS index in sync."""
    existing = store.conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name=?", (FTS_TABLE,)
    ).fetchone()
    if not existing:
        return
    with store.conn:
        store.conn.executemany(
            f"DELETE FROM {FTS_TABLE} WHERE chunk_id = ?", [(c.id,) for c in chunks]
        )
        store.conn.executemany(
            f"INSERT INTO {FTS_TABLE} (chunk_id, text) VALUES (?, ?)",
            [(c.id, c.text) for c in chunks],
        )


def sync_fts_delete(store: Store, chunk_ids: list[str]) -> None:
    """Call when chunks are deleted."""
    existing = store.conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name=?", (FTS_TABLE,)
    ).fetchone()
    if not existing:
        return
    for cid in chunk_ids:
        store.conn.execute(
            f"DELETE FROM {FTS_TABLE} WHERE chunk_id = ?", (cid,)
        )
    store.conn.commit()


# --------------------------------------------------------------- search impls


def _keyword_search(
    store: Store,
    query: str,
    k: int,
    collections: tuple[str, ...],
    tag: str | None,
    project: str | None,
    status: str | None = None,
) -> list[tuple[str, float]]:
    """FTS5 BM25 search; returns (chunk_id, bm25_score) sorted by relevance."""
    terms = re.findall(r"\w+", query, flags=re.UNICODE)
    if not terms or k <= 0 or not collections:
        return []
    _ensure_fts(store)
    sql = (
        f"SELECT f.chunk_id, bm25({FTS_TABLE}) AS score FROM {FTS_TABLE} f"
        " JOIN chunks c ON c.id = f.chunk_id"
        " JOIN documents d ON d.id = c.document_id"
    )
    where = ["f.text MATCH ?", f"d.collection IN ({','.join('?' * len(collections))})"]
    # Treat ordinary questions as literal terms, never as FTS query syntax.
    # OR keeps a rare relevant term useful even in a longer question.
    args: list[Any] = [" OR ".join(f'"{term}"' for term in terms), *collections]
    if tag:
        sql += " JOIN document_tags dt ON dt.document_id = d.id JOIN tags t ON t.id = dt.tag_id"
        where.append("t.name = ?")
        args.append(tag)
    if project:
        sql += (" JOIN document_projects dp ON dp.document_id = d.id"
                " JOIN projects p ON p.id = dp.project_id")
        where.append("p.name = ?")
        args.append(project.strip().lower())
    if status:
        where.append("d.status = ?")
        args.append(status)
    sql += " WHERE " + " AND ".join(where) + " ORDER BY score LIMIT ?"
    args.append(k * 3)
    rows = store.conn.execute(sql, args).fetchall()
    return [(r[0], abs(r[1])) for r in rows]


def _dense_search(
    store: Store,
    query_vec: np.ndarray,
    k: int,
    collections: tuple[str, ...],
    tag: str | None = None,
    project: str | None = None,
    status: str | None = None,
) -> list[tuple[str, float]]:
    """Brute-force cosine; returns (chunk_id, score)."""
    if k <= 0 or not collections:
        return []
    sql = (
        "SELECT c.id, c.embedding FROM chunks c"
        " JOIN documents d ON d.id = c.document_id"
    )
    where = [f"d.collection IN ({','.join('?' * len(collections))})"]
    args: list[Any] = list(collections)
    if tag:
        sql += " JOIN document_tags dt ON dt.document_id = d.id JOIN tags t ON t.id = dt.tag_id"
        where.append("t.name = ?")
        args.append(tag)
    if project:
        sql += (" JOIN document_projects dp ON dp.document_id = d.id"
                " JOIN projects p ON p.id = dp.project_id")
        where.append("p.name = ?")
        args.append(project.strip().lower())
    if status:
        where.append("d.status = ?")
        args.append(status)
    sql += " WHERE " + " AND ".join(where)
    rows = store.conn.execute(sql, args).fetchall()
    if not rows:
        return []
    ids = [r[0] for r in rows]
    matrix = np.vstack([blob_to_embed(r[1]) for r in rows])
    q = np.asarray(query_vec, dtype=np.float32)
    norm = np.linalg.norm(q)
    if norm > 0:
        q = q / norm
    scores = matrix @ q
    order = np.argsort(-scores)[: k * 3]
    return [(ids[int(i)], float(scores[int(i)])) for i in order]


# ---------------------------------------------------------------- RRF fusion


def reciprocal_rank_fusion(
    *rankings: list[tuple[str, float]],
    k_rrf: int = 60,
) -> list[tuple[str, float]]:
    """Fuse multiple ranked lists via RRF: score = sum(1 / (k + rank))."""
    scores: dict[str, float] = {}
    for ranking in rankings:
        for rank, (item_id, _original_score) in enumerate(ranking, start=1):
            scores[item_id] = scores.get(item_id, 0.0) + 1.0 / (k_rrf + rank)
    return sorted(scores.items(), key=lambda x: -x[1])


# --------------------------------------------------------------- reranking


_reranker_cache: dict[str, Any] = {}


def _get_reranker(model_name: str = "BAAI/bge-reranker-base"):
    if model_name not in _reranker_cache:
        from sentence_transformers import CrossEncoder

        _reranker_cache[model_name] = CrossEncoder(model_name)
    return _reranker_cache[model_name]


def rerank(
    query: str,
    chunk_ids: list[str],
    store: Store,
    model_name: str = "BAAI/bge-reranker-base",
) -> list[tuple[str, float]]:
    """Score (query, chunk_text) pairs with a cross-encoder; return sorted."""
    texts = []
    for cid in chunk_ids:
        row = store.conn.execute("SELECT text FROM chunks WHERE id = ?", (cid,)).fetchone()
        texts.append(row["text"] if row else "")
    model = _get_reranker(model_name)
    pairs = [(query, t) for t in texts]
    scores = model.predict(pairs)
    scored = sorted(zip(chunk_ids, scores, strict=True), key=lambda x: -x[1])
    return [(cid, float(s)) for cid, s in scored]


# ---------------------------------------------------------------- top-level


def hybrid_search(
    store: Store,
    embedder: Embedder,
    query: str,
    k: int = 8,
    collections: tuple[str, ...] = ("papers",),
    tag: str | None = None,
    project: str | None = None,
    mode: str = "hybrid",
    do_rerank: bool = False,
    rerank_model: str = "BAAI/bge-reranker-base",
    status: str | None = None,
) -> list[tuple[Chunk, Document, float]]:
    """Unified retrieval: dense, hybrid (dense+BM25+RRF), optional rerank."""
    if k <= 0 or not query.strip() or not collections:
        return []
    query_vec = embedder.encode([query])[0]
    dense_hits = _dense_search(
        store, query_vec, k, collections, tag=tag, project=project, status=status
    )

    if mode == "hybrid":
        keyword_hits = _keyword_search(
            store, query, k, collections, tag=tag, project=project, status=status
        )
        fused = reciprocal_rank_fusion(dense_hits, keyword_hits)
    else:
        fused = dense_hits

    # top-N for potential reranking
    top_ids = [cid for cid, _ in fused[: k * 3]]

    if do_rerank and top_ids:
        top_ids_scores = rerank(query, top_ids, store, model_name=rerank_model)
        top_ids = [cid for cid, _ in top_ids_scores[:k]]
        scores = dict(top_ids_scores)
    else:
        top_ids = top_ids[:k]
        scores = dict(fused)

    # Build result tuples
    results = []
    doc_cache: dict[str, Document] = {}
    for cid in top_ids:
        row = store.conn.execute(
            "SELECT * FROM chunks WHERE id = ?", (cid,)
        ).fetchone()
        if not row:
            continue
        doc_id = row["document_id"]
        if doc_id not in doc_cache:
            doc_cache[doc_id] = store.get_document(doc_id)
        chunk = Chunk(row["id"], doc_id, row["ordinal"], row["text"],
                      row["page"], row["token_count"])
        score = scores.get(cid, 0.0)
        results.append((chunk, doc_cache[doc_id], score))
    return results
