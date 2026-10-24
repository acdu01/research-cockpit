"""M14: literature review builder - comparison table + cited draft."""

from __future__ import annotations

import json

from conftest import FakeAdapter, make_paper
from research_cockpit.extract import extract_paper
from research_cockpit.litreview import (
    comparison_table,
    generate_draft,
    render_table_latex,
    render_table_markdown,
)
from research_cockpit.store import Chunk, new_id


def _seeded_pair(store, embedder):
    d1 = make_paper(store, "Humidity and Cockling", year=2019, venue="JoC",
                    authors=["Beatrice of Ravenna"])
    d2 = make_paper(store, "Iron-Gall Ink Corrosion", year=2020, venue="JoC",
                    authors=["Odo the Scribe"])
    for doc, text in [(d1, "Humidity halts cockling."), (d2, "Ink corrodes at low pH.")]:
        c = Chunk(id=new_id(), document_id=doc.id, ordinal=0, page=1,
                  text=text, token_count=5)
        store.add_chunks([c], embedder.encode([text]))
    resp1 = json.dumps({"task": "Study cockling", "method": "Chamber experiments",
                        "datasets": ["Bodleian"], "metrics": [], "findings": ["45% halts"],
                        "limitations": []})
    resp2 = json.dumps({"task": "Study corrosion", "method": "pH exposure",
                        "datasets": [], "metrics": [{"name": "pH", "value": "2.5"}],
                        "findings": ["pH<2.5 accelerates"], "limitations": ["Only iron-gall"]})
    extract_paper(store, FakeAdapter(resp1), d1)
    extract_paper(store, FakeAdapter(resp2), d2)
    return [d1, d2]


def test_comparison_table(store, embedder):
    docs = _seeded_pair(store, embedder)
    rows = comparison_table(store, docs)
    assert len(rows) == 2
    assert rows[0]["task"] == "Study cockling"
    assert "Bodleian" in rows[0]["datasets"]
    assert rows[1]["task"] == "Study corrosion"


def test_render_markdown(store, embedder):
    docs = _seeded_pair(store, embedder)
    rows = comparison_table(store, docs)
    md = render_table_markdown(rows)
    assert "cite_key" in md and "task" in md
    assert "ravenna2019humidity" in md.lower() or "Humidity" in md


def test_render_latex(store, embedder):
    docs = _seeded_pair(store, embedder)
    rows = comparison_table(store, docs)
    tex = render_table_latex(rows)
    assert r"\begin{tabular}" in tex
    assert r"\toprule" in tex
    assert "Study cockling" in tex


def test_generate_draft(store, embedder):
    docs = _seeded_pair(store, embedder)
    adapter = FakeAdapter(r"Ravenna \cite{ravenna2019humidity} showed cockling halts.")
    draft, bib = generate_draft(store, adapter, docs)
    assert r"\cite{" in draft
    assert "ravenna" in draft.lower()
    assert "@" in bib  # valid bibtex content
