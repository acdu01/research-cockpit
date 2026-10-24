from __future__ import annotations

import pytest

from conftest import FakeAdapter
from research_cockpit import rag
from research_cockpit.ingest import ingest_note
from research_cockpit.store import Chunk, new_id


def _add_paper_chunk(store, embedder, title, text, page=3):
    from conftest import make_paper

    doc = make_paper(store, title)
    chunk = Chunk(id=new_id(), document_id=doc.id, ordinal=0, text=text, page=page,
                  token_count=len(text.split()))
    store.add_chunks([chunk], embedder.encode([text]))
    return doc


def test_search_invalid_scope(store, embedder):
    with pytest.raises(ValueError):
        rag.search(store, embedder, "q", scope="everything")


def test_ask_formats_citations_and_sources(store, embedder):
    doc = _add_paper_chunk(store, embedder, "Scaling Laws",
                           "loss scales as a power law with model size and data")
    adapter = FakeAdapter("Loss follows a power law [1].")
    answer = rag.ask(store, embedder, adapter, "how does loss scale?")
    assert "[1]" in answer.text
    assert len(answer.sources) == 1
    src = answer.sources[0]
    assert src.title == "Scaling Laws"
    assert src.document_id == doc.id
    rendered = answer.render_sources()
    assert "Scaling Laws" in rendered and "p.3" in rendered and doc.id[:8] in rendered


def test_ask_scope_excludes_notes_by_default(store, embedder):
    _add_paper_chunk(store, embedder, "Paper", "formal results about scaling laws")
    ingest_note(store, embedder, "my private ideas about scaling laws", "secret note")
    adapter = FakeAdapter("Answer [1][2].")
    rag.ask(store, embedder, adapter, "scaling laws", scope="papers", k=10)
    prompt = adapter.calls[0][0]
    assert "private ideas" not in prompt
    rag.ask(store, embedder, adapter, "scaling laws", scope="all", k=10)
    assert "private ideas" in adapter.calls[1][0]


def test_ask_no_hits(store, embedder, adapter):
    answer = rag.ask(store, embedder, adapter, "anything")
    assert "No matching passages" in answer.text
    assert adapter.calls == []  # no generation without context


def test_synthesize_system_prompt(store, embedder):
    _add_paper_chunk(store, embedder, "A", "method one works well on benchmark")
    adapter = FakeAdapter("Comparison [1].")
    rag.ask(store, embedder, adapter, "compare", mode="synthesize")
    system = adapter.calls[0][1]
    assert "contradiction" in system.lower()


def test_gaps_prompt_includes_graph_candidates(store, embedder):
    _add_paper_chunk(store, embedder, "A", "coverage of topic alpha")
    adapter = FakeAdapter("Missing: beta.")
    rag.ask(store, embedder, adapter, "alpha", mode="gaps",
            gap_candidates=["Famous Missing Paper (2020)"])
    prompt, system = adapter.calls[0]
    assert "Famous Missing Paper" in prompt
    assert "does" in system and "NOT" in system


def test_uncited_sources_are_pruned(store, embedder):
    _add_paper_chunk(store, embedder, "Cited", "topic alpha details specifics")
    _add_paper_chunk(store, embedder, "Uncited", "topic alpha other angle entirely")
    adapter = FakeAdapter("Only the first matters [1].")
    answer = rag.ask(store, embedder, adapter, "topic alpha", k=2)
    assert [s.n for s in answer.sources] == [1]
