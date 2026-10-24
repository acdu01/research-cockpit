"""M11: hybrid retrieval - FTS5, RRF fusion, config switching."""

from __future__ import annotations

import pytest

from conftest import make_paper
from research_cockpit.retrieval import (
    _dense_search,
    _ensure_fts,
    _keyword_search,
    hybrid_search,
    reciprocal_rank_fusion,
    sync_fts_insert,
)
from research_cockpit.store import Chunk, new_id


def _seed_corpus(store, embedder):
    doc = make_paper(store, "Parchment Stability Survey")
    texts = [
        "Humidity near 45% halts cockling of collagen-based parchment folios.",
        "Iron-gall ink corrosion accelerates when pH drops below 2.5.",
        "The Vatopedi monastery fragments show minimal degradation.",
    ]
    chunks = [
        Chunk(id=new_id(), document_id=doc.id, ordinal=i, page=i + 1,
              text=t, token_count=len(t.split()))
        for i, t in enumerate(texts)
    ]
    embeddings = embedder.encode(texts)
    store.add_chunks(chunks, embeddings)
    sync_fts_insert(store, chunks)
    return doc, chunks


def test_fts_backfill_on_first_use(store, embedder):
    doc, chunks = _seed_corpus(store, embedder)
    # FTS table wasn't created yet - _ensure_fts should create + backfill
    _ensure_fts(store)
    hits = _keyword_search(store, "cockling", 5, ("papers",), None, None)
    assert len(hits) >= 1
    assert chunks[0].id in [cid for cid, _ in hits]


def test_keyword_search_finds_rare_term(store, embedder):
    doc, chunks = _seed_corpus(store, embedder)
    _ensure_fts(store)
    hits = _keyword_search(store, "Vatopedi", 5, ("papers",), None, None)
    assert chunks[2].id in [cid for cid, _ in hits]


def test_dense_search_still_works(store, embedder):
    doc, chunks = _seed_corpus(store, embedder)
    query_vec = embedder.encode(["humidity cockling"])[0]
    hits = _dense_search(store, query_vec, 3, ("papers",))
    assert len(hits) >= 1


def test_rrf_fusion():
    list_a = [("c1", 0.9), ("c2", 0.7), ("c3", 0.5)]
    list_b = [("c3", 0.8), ("c2", 0.6), ("c4", 0.4)]
    fused = reciprocal_rank_fusion(list_a, list_b, k_rrf=60)
    ids = [cid for cid, _ in fused]
    assert "c2" in ids and "c3" in ids
    # c2 appears in both at rank 2 → higher score than c4 (only in b at rank 3)
    assert ids.index("c2") < ids.index("c4")


def test_hybrid_search_merges_keyword_and_dense(store, embedder):
    doc, chunks = _seed_corpus(store, embedder)
    hits = hybrid_search(store, embedder, "Vatopedi", k=3,
                         collections=("papers",), mode="hybrid")
    ids = [c.id for c, _, _ in hits]
    assert chunks[2].id in ids


def test_dense_only_mode(store, embedder):
    doc, chunks = _seed_corpus(store, embedder)
    hits = hybrid_search(store, embedder, "humidity", k=3,
                         collections=("papers",), mode="dense")
    assert len(hits) >= 1


def test_config_switching_in_rag_search(store, embedder):
    """rag.search passes retrieval mode through correctly."""
    from research_cockpit import rag

    doc, chunks = _seed_corpus(store, embedder)
    hits_dense = rag.search(store, embedder, "cockling", k=3, retrieval="dense")
    hits_hybrid = rag.search(store, embedder, "cockling", k=3, retrieval="hybrid")
    # both return results; hybrid may reorder but same doc
    assert hits_dense and hits_hybrid
    assert hits_dense[0][1].id == doc.id
    assert hits_hybrid[0][1].id == doc.id


def test_keyword_index_tracks_insert_update_and_delete(store, embedder):
    _seed_corpus(store, embedder)
    _ensure_fts(store)
    doc = make_paper(store, "New paper")
    chunk = Chunk(new_id(), doc.id, 0, "xylophone", 1, 1)
    store.add_chunks([chunk], embedder.encode([chunk.text]))
    assert _keyword_search(store, "xylophone", 5, ("papers",), None, None)
    # Older callers may still explicitly sync; this must not duplicate hits.
    sync_fts_insert(store, [chunk])
    assert len(_keyword_search(store, "xylophone", 5, ("papers",), None, None)) == 1
    store.conn.execute("UPDATE chunks SET text = 'harpsichord' WHERE id = ?", (chunk.id,))
    store.conn.commit()
    assert not _keyword_search(store, "xylophone", 5, ("papers",), None, None)
    assert _keyword_search(store, "harpsichord", 5, ("papers",), None, None)
    store.delete_document(doc.id)
    assert not store.conn.execute(
        "SELECT 1 FROM chunks_fts WHERE chunk_id = ?", (chunk.id,)
    ).fetchone()


def test_legacy_partial_keyword_index_is_rebuilt(store, embedder):
    _, chunks = _seed_corpus(store, embedder)
    store.conn.execute("CREATE VIRTUAL TABLE chunks_fts USING fts5(chunk_id, text)")
    store.conn.execute(
        "INSERT INTO chunks_fts VALUES (?, ?)", (chunks[0].id, chunks[0].text)
    )
    store.conn.commit()
    hits = _keyword_search(store, "Vatopedi", 5, ("papers",), None, None)
    assert chunks[2].id in [cid for cid, _ in hits]
    assert store.conn.execute("SELECT COUNT(*) FROM chunks_fts").fetchone()[0] == 3


def test_keyword_search_accepts_natural_language_punctuation(store, embedder):
    _, chunks = _seed_corpus(store, embedder)
    hits = _keyword_search(store, "What halts cockling?", 5, ("papers",), None, None)
    assert chunks[0].id in [cid for cid, _ in hits]


@pytest.mark.parametrize("mode", ["dense", "hybrid"])
def test_rag_search_applies_status_in_every_mode(store, embedder, mode):
    from research_cockpit import rag

    # Reuse seeded chunks, with one paper matching and one excluded.
    doc, _ = _seed_corpus(store, embedder)
    other, _ = _seed_corpus(store, embedder)
    store.update_document(doc.id, status="reading")
    hits = rag.search(store, embedder, "cockling", status="reading", retrieval=mode)
    assert hits and {d.id for _, d, _ in hits} == {doc.id}
    assert other.id not in {d.id for _, d, _ in hits}


def test_rerank_returns_the_reranker_scores(store, embedder, monkeypatch):
    _, chunks = _seed_corpus(store, embedder)
    monkeypatch.setattr(
        "research_cockpit.retrieval.rerank",
        lambda *args, **kwargs: [(chunks[1].id, 7.5), (chunks[0].id, -2.0)],
    )
    hits = hybrid_search(store, embedder, "cockling", k=2, do_rerank=True)
    assert [(c.id, score) for c, _, score in hits] == [
        (chunks[1].id, 7.5), (chunks[0].id, -2.0)
    ]
