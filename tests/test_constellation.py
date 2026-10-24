"""M19: constellation notes graph - links, suggestions, provenance, export."""

from __future__ import annotations

from research_cockpit.constellation import (
    add_source,
    confirmed_links,
    dismiss_suggestion,
    export_constellation,
    get_sources,
    link_notes,
    suggest_links,
    to_networkx,
    unlink_notes,
)
from research_cockpit.ingest import ingest_note


def _make_notes(store, embedder):
    r1 = ingest_note(store, embedder, "Humidity halts cockling of parchment folios.",
                     "Note on humidity")
    r2 = ingest_note(store, embedder, "Stable humidity is key for preservation of documents.",
                     "Preservation note")
    r3 = ingest_note(store, embedder, "Iron-gall ink corrodes at low pH levels rapidly.",
                     "Ink corrosion")
    return r1.document, r2.document, r3.document


def test_link_and_unlink(store, embedder):
    n1, n2, _ = _make_notes(store, embedder)
    link_notes(store, n1.id, n2.id, label="related")
    links = confirmed_links(store)
    assert len(links) == 1
    assert links[0]["label"] == "related"
    unlink_notes(store, n2.id, n1.id)  # order reversed - canonical handles it
    assert confirmed_links(store) == []


def test_canonical_pair_uniqueness(store, embedder):
    n1, n2, _ = _make_notes(store, embedder)
    link_notes(store, n1.id, n2.id)
    link_notes(store, n2.id, n1.id, label="updated")  # replaces
    links = confirmed_links(store)
    assert len(links) == 1 and links[0]["label"] == "updated"


def test_suggest_and_dismiss(store, embedder):
    n1, n2, n3 = _make_notes(store, embedder)
    suggestions = suggest_links(store, threshold=0.0)  # low threshold to catch any pair
    assert len(suggestions) >= 1
    # the two humidity-related notes should score higher than ink corrosion
    pair_ids = {(s["a_id"], s["b_id"]) for s in suggestions}
    from research_cockpit.constellation import _canonical
    humid_pair = _canonical(n1.id, n2.id)
    assert humid_pair in pair_ids
    # dismiss it
    dismiss_suggestion(store, n1.id, n2.id)
    suggestions_after = suggest_links(store, threshold=0.0)
    pair_ids_after = {(s["a_id"], s["b_id"]) for s in suggestions_after}
    assert humid_pair not in pair_ids_after


def test_provenance_crud(store, embedder):
    from conftest import make_paper

    n1, _, _ = _make_notes(store, embedder)
    doc = make_paper(store, "Source Paper")
    add_source(store, n1.id, doc.id, page=5, quote="Key passage here.")
    sources = get_sources(store, n1.id)
    assert len(sources) == 1
    assert sources[0]["document_title"] == "Source Paper"
    assert sources[0]["page"] == 5 and sources[0]["quote"] == "Key passage here."


def test_provenance_survives_rechunk(store, embedder):
    from research_cockpit.store import Chunk, new_id

    n1, _, _ = _make_notes(store, embedder)
    from conftest import make_paper
    doc = make_paper(store, "P")
    chunk = Chunk(id=new_id(), document_id=doc.id, ordinal=0, page=1,
                  text="t", token_count=1)
    store.add_chunks([chunk], embedder.encode(["t"]))
    add_source(store, n1.id, doc.id, chunk_id=chunk.id, page=1, quote="t")
    # simulate rechunk: delete the chunk
    store.conn.execute("DELETE FROM chunks WHERE id = ?", (chunk.id,))
    store.conn.commit()
    sources = get_sources(store, n1.id)
    assert sources[0]["chunk_id"] is None  # SET NULL
    assert sources[0]["quote"] == "t" and sources[0]["page"] == 1


def test_networkx_export(store, embedder, tmp_path):
    n1, n2, _ = _make_notes(store, embedder)
    link_notes(store, n1.id, n2.id)
    g = to_networkx(store)
    assert g.number_of_nodes() == 3
    assert g.number_of_edges() == 1
    # JSON export
    out = tmp_path / "notes.json"
    export_constellation(store, out)
    import json
    data = json.loads(out.read_text())
    assert "nodes" in data and "links" in data
