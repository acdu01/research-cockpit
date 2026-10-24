from __future__ import annotations

import sqlite3

import numpy as np

from conftest import FakeAdapter, make_paper
from research_cockpit.kb import generate_annotations, suggest_tags
from research_cockpit.llm import LocalAdapter
from research_cockpit.store import Chunk, Store, new_id


def _with_chunk(store, embedder, doc, text):
    chunk = Chunk(id=new_id(), document_id=doc.id, ordinal=0, text=text,
                  page=1, token_count=len(text.split()))
    store.add_chunks([chunk], embedder.encode([text]))


def test_suggest_tags_applies_and_normalizes(store, embedder):
    other = make_paper(store, "Existing paper")
    store.tag_document(other.id, "codicology")  # pre-existing vocabulary
    doc = make_paper(store, "Parchment Stability Survey")
    _with_chunk(store, embedder, doc, "humidity cycling degrades parchment folios")
    adapter = FakeAdapter('["Conservation", "parchment", "  ", "conservation"]')
    tags = suggest_tags(store, adapter, doc)
    assert tags == ["conservation", "parchment"]
    assert store.document_tags(doc.id) == ["conservation", "parchment"]
    # existing vocabulary offered to the model
    assert "codicology" in adapter.calls[0][0]


def test_suggest_tags_no_apply(store, embedder):
    doc = make_paper(store, "P")
    _with_chunk(store, embedder, doc, "text")
    tags = suggest_tags(store, FakeAdapter('["alpha"]'), doc, apply=False)
    assert tags == ["alpha"]
    assert store.document_tags(doc.id) == []


def test_enrichment_raises_on_prose_instead_of_json(store, embedder):
    import pytest

    from research_cockpit.llm import LLMError

    doc = make_paper(store, "P")
    _with_chunk(store, embedder, doc, "humidity halts cockling of folios")
    prose = FakeAdapter("I'd be happy to help! First, let me explain what tags are...")
    with pytest.raises(LLMError, match="no parseable JSON"):
        suggest_tags(store, prose, doc)
    with pytest.raises(LLMError, match="no parseable JSON"):
        generate_annotations(store, prose, doc)
    # an explicit empty array is a valid "nothing to add", not an error
    assert suggest_tags(store, FakeAdapter("[]"), doc) == []


def test_delete_annotation(store):
    doc = make_paper(store, "P")
    ann_id = store.add_annotation(doc.id, "to be removed")
    keep_id = store.add_annotation(doc.id, "kept", source="llm")
    store.delete_annotation(ann_id)
    remaining = store.annotations(doc.id)
    assert [r["id"] for r in remaining] == [keep_id]


def test_generate_annotations_marked_llm(store, embedder):
    doc = make_paper(store, "P")
    _with_chunk(store, embedder, doc, "stable humidity halts cockling of folios")
    store.add_annotation(doc.id, "my own human note")
    adapter = FakeAdapter('[{"text": "Humidity near 45% halts cockling.", "page": 3},'
                          ' {"text": "my own human note"}]')
    created = generate_annotations(store, adapter, doc)
    assert len(created) == 1  # duplicate of the human note skipped
    rows = store.annotations(doc.id)
    by_text = {r["text"]: r for r in rows}
    assert by_text["my own human note"]["source"] == "human"
    llm_row = by_text["Humidity near 45% halts cockling."]
    assert llm_row["source"] == "llm"
    assert llm_row["page"] == 3


def test_generate_annotations_advances_lifecycle(store, embedder):
    doc = make_paper(store, "P")  # to-read
    _with_chunk(store, embedder, doc, "some content here")
    generate_annotations(store, FakeAdapter('[{"text": "A key point."}]'), doc)
    assert store.get_document(doc.id).status == "annotated"


def test_local_adapter_handles_tags_and_annotations():
    from research_cockpit.kb import ANNOTATION_SYSTEM, TAG_SYSTEM
    from research_cockpit.llm import extract_json_array

    adapter = LocalAdapter()
    prompt = ("Paper: P\n\nExisting tag vocabulary: (none yet)\n\nExcerpts:\n\n"
              "parchment parchment humidity humidity archives storage")
    tags = extract_json_array(adapter.generate(prompt, system=TAG_SYSTEM))
    assert "parchment" in tags
    ann_prompt = "Paper: P\n\nExcerpts:\n\n[p.1] Humidity halts cockling. Storage matters."
    items = extract_json_array(adapter.generate(ann_prompt, system=ANNOTATION_SYSTEM))
    assert items and items[0]["text"].startswith("Humidity")


def test_source_column_migration(tmp_path):
    """Databases created before the source column exist get migrated in place."""
    db = tmp_path / "old.db"
    conn = sqlite3.connect(db)
    conn.executescript(
        """CREATE TABLE documents (id TEXT PRIMARY KEY, collection TEXT NOT NULL
               CHECK (collection IN ('papers','notes')), title TEXT,
               authors TEXT NOT NULL DEFAULT '[]', year INTEGER, venue TEXT, doi TEXT,
               openalex_id TEXT, s2_id TEXT, source_path TEXT, content_hash TEXT,
               status TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
           CREATE TABLE annotations (id TEXT PRIMARY KEY, document_id TEXT NOT NULL,
               text TEXT NOT NULL, page INTEGER, created_at TEXT NOT NULL);
           INSERT INTO documents VALUES ('d1', 'papers', 'Old', '[]', NULL, NULL,
               NULL, NULL, NULL, NULL, NULL, 'to-read', 't', 't');
           INSERT INTO annotations VALUES ('a1', 'd1', 'legacy note', NULL, 't');"""
    )
    conn.commit()
    conn.close()
    store = Store(db)
    rows = store.annotations("d1")
    assert rows[0]["source"] == "human"  # legacy rows default to human
    store.add_annotation("d1", "new ai note", source="llm")
    assert {r["source"] for r in store.annotations("d1")} == {"human", "llm"}
    store.close()


def test_annotation_embedding_roundtrip_unaffected(store, embedder):
    # sanity: chunks table unchanged by migration path
    doc = make_paper(store, "P")
    chunk = Chunk(id=new_id(), document_id=doc.id, ordinal=0, text="x", page=None,
                  token_count=1)
    store.add_chunks([chunk], np.zeros((1, 128), dtype=np.float32))
    assert store.chunk_count(doc.id) == 1
