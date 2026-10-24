from __future__ import annotations

import pytest

from conftest import make_paper
from research_cockpit import rag
from research_cockpit.store import Chunk, new_id


def test_create_list_delete(store):
    store.create_project("Thesis Work", description="dissertation")
    store.create_project("thesis work")  # idempotent, normalized
    rows = store.list_projects()
    assert len(rows) == 1
    assert rows[0]["name"] == "thesis work"
    assert rows[0]["description"] == "dissertation"
    store.delete_project("thesis work")
    assert store.list_projects() == []


def test_empty_name_rejected(store):
    with pytest.raises(ValueError):
        store.create_project("   ")


def test_assign_creates_and_counts(store):
    doc = make_paper(store, "Paper A")
    store.assign_project(doc.id, "Side Quest")  # auto-creates
    assert store.document_projects(doc.id) == ["side quest"]
    assert store.list_projects()[0]["documents"] == 1
    store.unassign_project(doc.id, "side quest")
    assert store.document_projects(doc.id) == []


def test_list_documents_project_filter(store):
    a = make_paper(store, "In project")
    make_paper(store, "Not in project")
    store.assign_project(a.id, "alpha")
    docs = store.list_documents(collection="papers", project="alpha")
    assert [d.id for d in docs] == [a.id]
    # case-insensitive filter
    assert [d.id for d in store.list_documents(project="ALPHA")] == [a.id]


def test_search_scoped_to_project(store, embedder):
    a = make_paper(store, "Scoped paper")
    b = make_paper(store, "Other paper")
    for doc, text in ((a, "quantum error correction codes"),
                      (b, "quantum error correction codes elsewhere")):
        chunk = Chunk(id=new_id(), document_id=doc.id, ordinal=0, text=text,
                      page=None, token_count=4)
        store.add_chunks([chunk], embedder.encode([text]))
    store.assign_project(a.id, "qec")
    hits = rag.search(store, embedder, "quantum error", project="qec", k=5)
    assert {d.id for _, d, _ in hits} == {a.id}


def test_delete_project_keeps_documents(store):
    doc = make_paper(store, "Survivor")
    store.assign_project(doc.id, "doomed")
    store.delete_project("doomed")
    assert store.get_document(doc.id) is not None
    assert store.document_projects(doc.id) == []
