from __future__ import annotations

from conftest import make_paper
from research_cockpit.bib import export_bibtex, import_bibtex

SAMPLE_BIB = """
@article{vaswani2017attention,
  title = {Attention Is All You Need},
  author = {Vaswani, Ashish and Shazeer, Noam},
  year = {2017},
  journal = {NeurIPS},
  doi = {10.48550/arXiv.1706.03762}
}
"""

FULL_BIB = """
@inproceedings{beatrice2019humidity,
  title = {Humidity and the Cockling of Parchment Folios},
  author = {of Ravenna, Beatrice},
  year = {2019},
  booktitle = {Proc. Codicology Conf.},
  volume = {12},
  number = {3},
  pages = {201--219},
  publisher = {Scriptorium Press},
  url = {https://journal.example/parchment},
  issn = {1234-5678},
  doi = {10.1234/parchment.2019}
}
"""


def test_export_includes_fields(store):
    make_paper(store, "Attention Is All You Need", authors=["Ashish Vaswani"],
               year=2017, venue="NeurIPS", doi="10.48550/arXiv.1706.03762",
               status="cited")
    out = export_bibtex(store)
    assert "Attention Is All You Need" in out
    assert "Ashish Vaswani" in out
    assert "10.48550/arXiv.1706.03762" in out
    assert "@article" in out


def test_export_filters_status_and_excludes_notes(store, embedder):
    from research_cockpit.ingest import ingest_note

    make_paper(store, "Cited paper", status="cited", year=2020)
    make_paper(store, "Unread paper", status="to-read", year=2021)
    ingest_note(store, embedder, "note body", "A note")
    out = export_bibtex(store, status="cited")
    assert "Cited paper" in out
    assert "Unread paper" not in out
    assert "A note" not in out


def test_import_roundtrip_and_dedupe(store):
    created = import_bibtex(store, SAMPLE_BIB)
    assert len(created) == 1
    doc = created[0]
    assert doc.title == "Attention Is All You Need"
    assert doc.authors == ["Ashish Vaswani", "Noam Shazeer"]
    assert doc.year == 2017
    assert doc.status == "to-read"
    assert doc.collection == "papers"
    # re-import dedupes on DOI
    assert import_bibtex(store, SAMPLE_BIB) == []


def test_import_then_export_roundtrip(store):
    import_bibtex(store, SAMPLE_BIB)
    out = export_bibtex(store)
    assert "Attention Is All You Need" in out
    assert "Ashish Vaswani and Noam Shazeer" in out


def test_import_captures_full_citation_fields(store):
    (doc,) = import_bibtex(store, FULL_BIB)
    assert doc.item_type == "inproceedings"
    assert doc.venue == "Proc. Codicology Conf."
    assert doc.volume == "12" and doc.issue == "3"
    assert doc.pages == "201-219"  # BibTeX -- normalized for storage
    assert doc.publisher == "Scriptorium Press"
    assert doc.url == "https://journal.example/parchment"
    assert doc.issn == "1234-5678"


def test_full_export_roundtrip_preserves_entrytype_and_fields(store):
    import_bibtex(store, FULL_BIB)
    out = export_bibtex(store)
    assert "@inproceedings" in out
    assert "booktitle = {Proc. Codicology Conf.}" in out
    assert "pages = {201--219}" in out
    assert "publisher = {Scriptorium Press}" in out
    assert "number = {3}" in out
    assert "issn = {1234-5678}" in out
