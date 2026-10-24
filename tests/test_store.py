from __future__ import annotations

import sqlite3

import numpy as np
import pytest

from conftest import make_paper
from research_cockpit.store import Chunk, Document, new_id


def test_add_and_get_document(store):
    doc = make_paper(store, "Attention Is All You Need", year=2017,
                     authors=["Ashish Vaswani"], doi="10.1/abc")
    fetched = store.get_document(doc.id)
    assert fetched.title == "Attention Is All You Need"
    assert fetched.authors == ["Ashish Vaswani"]
    assert fetched.status == "to-read"


def test_collection_check_constraint(store):
    with pytest.raises(sqlite3.IntegrityError):
        store.add_document(Document(id=new_id(), collection="bogus"))


def test_resolve_by_prefix_doi_title(store):
    doc = make_paper(store, "Deep Residual Learning", doi="10.2/resnet")
    assert store.resolve_document(doc.id[:8]).id == doc.id
    assert store.resolve_document("10.2/resnet").id == doc.id
    assert store.resolve_document("deep residual learning").id == doc.id
    assert store.resolve_document("nonexistent") is None


def test_tags_and_filtering(store):
    a = make_paper(store, "Paper A")
    b = make_paper(store, "Paper B")
    store.tag_document(a.id, "nlp", "transformers")
    store.tag_document(b.id, "vision")
    assert store.document_tags(a.id) == ["nlp", "transformers"]
    nlp = store.list_documents(collection="papers", tag="nlp")
    assert [d.id for d in nlp] == [a.id]


def test_list_by_status(store):
    a = make_paper(store, "Read me")
    make_paper(store, "Later")
    store.update_document(a.id, status="reading")
    reading = store.list_documents(collection="papers", status="reading")
    assert [d.id for d in reading] == [a.id]


def test_vector_search_scope_separation(store, embedder):
    paper = make_paper(store, "Transformers paper")
    note = store.add_document(Document(id=new_id(), collection="notes", title="my note"))
    texts = {
        paper.id: "attention mechanisms in transformer architectures",
        note.id: "personal thoughts about attention and transformers",
    }
    for doc_id, text in texts.items():
        chunk = Chunk(id=new_id(), document_id=doc_id, ordinal=0, text=text,
                      page=None, token_count=6)
        store.add_chunks([chunk], embedder.encode([text]))

    q = embedder.encode(["transformer attention"])[0]
    papers_only = store.search_chunks(q, collections=("papers",))
    assert {d.id for _, d, _ in papers_only} == {paper.id}
    both = store.search_chunks(q, collections=("papers", "notes"))
    assert {d.id for _, d, _ in both} == {paper.id, note.id}


def test_search_ranks_by_similarity(store, embedder):
    doc = make_paper(store, "Mixed topics")
    texts = [
        "quantum error correction surface codes qubits",
        "gardening tomatoes soil compost watering",
    ]
    chunks = [
        Chunk(id=new_id(), document_id=doc.id, ordinal=i, text=t, page=i + 1,
              token_count=5)
        for i, t in enumerate(texts)
    ]
    store.add_chunks(chunks, embedder.encode(texts))
    q = embedder.encode(["qubits error correction"])[0]
    results = store.search_chunks(q, collections=("papers",), k=2)
    assert results[0][0].text.startswith("quantum")
    assert results[0][2] > results[1][2]


def test_delete_cascades(store, embedder):
    doc = make_paper(store, "Doomed")
    chunk = Chunk(id=new_id(), document_id=doc.id, ordinal=0, text="x", page=None,
                  token_count=1)
    store.add_chunks([chunk], np.zeros((1, 128), dtype=np.float32))
    store.add_annotation(doc.id, "note")
    store.delete_document(doc.id)
    assert store.chunk_count() == 0
    assert store.annotations(doc.id) == []


def test_citation_upsert_handles_nullable_endpoints(store):
    doc = make_paper(store, "Seed")
    for title in ["Old title", "Updated title"]:
        store.upsert_citation(
            "openalex", citing_id=doc.id, cited_ext="W123", cited_title=title
        )
    assert len(store.citations()) == 1
    assert store.citations()[0]["cited_title"] == "Updated title"


def test_chunk_batch_failure_rolls_back(store, embedder):
    doc = make_paper(store, "Batch")
    chunk = Chunk(new_id(), doc.id, 0, "text", 1, 1)
    with pytest.raises(sqlite3.IntegrityError):
        store.add_chunks([chunk, chunk], embedder.encode(["text", "text"]))
    # A later unrelated commit must not accidentally save the partial batch.
    make_paper(store, "Unrelated")
    assert store.chunk_count(doc.id) == 0


def test_document_prefixes_are_literal_and_dois_ignore_case(store):
    doc = make_paper(store, "Paper", doi="10.1234/Example")
    assert store.find_by_doi("10.1234/example").id == doc.id
    assert store.resolve_document("10.1234/example").id == doc.id
    assert store.resolve_document("%") is None
    assert store.resolve_document("") is None
