"""M10: claim-to-evidence workspace - CRUD, ordering, cascades."""

from __future__ import annotations

import pytest

from conftest import make_paper
from research_cockpit.claims import (
    add_claim,
    attach_evidence,
    delete_claim,
    detach_evidence,
    evidence_for_document,
    get_claim,
    list_claims,
    move_claim,
    update_claim,
)
from research_cockpit.store import Chunk, new_id


@pytest.fixture
def project(store):
    store.create_project("thesis", "Chapter 2")
    return "thesis"


def test_claim_crud(store, project):
    c1 = add_claim(store, project, "First claim")
    c2 = add_claim(store, project, "Second claim", notes="draft")
    claims = list_claims(store, project)
    assert len(claims) == 2
    assert claims[0]["text"] == "First claim" and claims[0]["ordinal"] == 0
    assert claims[1]["text"] == "Second claim" and claims[1]["ordinal"] == 1
    assert claims[1]["notes"] == "draft"
    update_claim(store, c1, text="Revised claim")
    assert get_claim(store, c1)["text"] == "Revised claim"
    delete_claim(store, c2)
    remaining = list_claims(store, project)
    assert len(remaining) == 1 and remaining[0]["id"] == c1


def test_claim_move_reorders(store, project):
    c1 = add_claim(store, project, "A")
    c2 = add_claim(store, project, "B")
    c3 = add_claim(store, project, "C")
    move_claim(store, c3, 0)
    claims = list_claims(store, project)
    assert [c["id"] for c in claims] == [c3, c1, c2]


def test_evidence_attach_detach(store, project, embedder):
    doc = make_paper(store, "Humidity Paper", doi="10.1/h")
    chunk = Chunk(id=new_id(), document_id=doc.id, ordinal=0, page=3,
                  text="45% RH halts cockling.", token_count=5)
    store.add_chunks([chunk], embedder.encode([chunk.text]))
    claim_id = add_claim(store, project, "Low humidity preserves parchment.")
    eid = attach_evidence(
        store, claim_id, document_id=doc.id, quote="45% RH halts cockling.",
        chunk_id=chunk.id, page=3, stance="supports", note="key result"
    )
    claim = get_claim(store, claim_id)
    assert len(claim["evidence"]) == 1
    ev = claim["evidence"][0]
    assert ev["quote"] == "45% RH halts cockling."
    assert ev["document_title"] == "Humidity Paper"
    assert ev["stance"] == "supports"
    assert ev["page"] == 3 and ev["chunk_id"] == chunk.id
    # reverse lookup
    from_doc = evidence_for_document(store, doc.id)
    assert len(from_doc) == 1 and from_doc[0]["claim_text"] == "Low humidity preserves parchment."
    detach_evidence(store, eid)
    assert get_claim(store, claim_id)["evidence"] == []


def test_evidence_survives_chunk_deletion(store, project, embedder):
    """Quote+page survive even when the chunk is deleted (re-chunking scenario)."""
    doc = make_paper(store, "P")
    chunk = Chunk(id=new_id(), document_id=doc.id, ordinal=0, page=5,
                  text="Critical passage here.", token_count=3)
    store.add_chunks([chunk], embedder.encode([chunk.text]))
    claim_id = add_claim(store, project, "Test claim.")
    attach_evidence(store, claim_id, doc.id, "Critical passage here.",
                    chunk_id=chunk.id, page=5)
    # delete the chunk (simulating rechunk)
    store.conn.execute("DELETE FROM chunks WHERE id = ?", (chunk.id,))
    store.conn.commit()
    claim = get_claim(store, claim_id)
    ev = claim["evidence"][0]
    assert ev["chunk_id"] is None  # ON DELETE SET NULL
    assert ev["quote"] == "Critical passage here." and ev["page"] == 5


def test_project_cascade_deletes_claims(store, project):
    add_claim(store, project, "Goes away with project.")
    store.delete_project(project)
    # tables still exist; claim is gone
    from research_cockpit.claims import _ensure_tables
    _ensure_tables(store)
    rows = store.conn.execute("SELECT * FROM claims").fetchall()
    assert rows == []


def test_stance_validation(store, project, embedder):
    doc = make_paper(store, "P")
    cid = add_claim(store, project, "C")
    with pytest.raises(ValueError, match="stance"):
        attach_evidence(store, cid, doc.id, "quote", stance="agrees")


def test_nonexistent_project_raises(store):
    with pytest.raises(ValueError, match="does not exist"):
        add_claim(store, "ghost", "text")
