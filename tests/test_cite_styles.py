from __future__ import annotations

import pytest

from conftest import make_paper
from research_cockpit.bib import format_citation, format_citations
from research_cockpit.store import Document, new_id


def _doc(authors):
    return Document(
        id=new_id(), collection="papers", title="On Parchment Stability",
        authors=authors, year=2024, venue="Journal of Codicology",
        doi="10.9999/parchment.1",
    )


def test_apa():
    out = format_citation(_doc(["Ada Lovelace", "Charles Babbage"]), "apa")
    assert out == ("Lovelace, A., & Babbage, C. (2024). On Parchment Stability."
                   " Journal of Codicology. https://doi.org/10.9999/parchment.1")


def test_mla_two_and_many_authors():
    two = format_citation(_doc(["Ada Lovelace", "Charles Babbage"]), "mla")
    assert two.startswith('Lovelace, Ada, and Charles Babbage. "On Parchment Stability."')
    assert "Journal of Codicology, 2024, doi:10.9999/parchment.1." in two
    many = format_citation(_doc(["Ada Lovelace", "B Two", "C Three"]), "mla")
    assert many.startswith("Lovelace, Ada, et al.")


def test_chicago():
    out = format_citation(_doc(["Ada Lovelace", "Charles Babbage", "Grace Hopper"]),
                          "chicago")
    assert out.startswith("Lovelace, Ada, Charles Babbage, and Grace Hopper. 2024.")
    assert '"On Parchment Stability."' in out
    assert out.endswith("https://doi.org/10.9999/parchment.1.")


def test_bibtex_style_is_latex_importable():
    out = format_citation(_doc(["Ada Lovelace"]), "bibtex")
    assert out.startswith("@article{")
    assert "author = {Ada Lovelace}" in out
    assert "doi = {10.9999/parchment.1}" in out


def test_missing_fields_degrade_gracefully():
    bare = Document(id=new_id(), collection="papers", title="Untitled Draft")
    assert format_citation(bare, "apa") == "Untitled Draft. (n.d.)."
    mla = format_citation(bare, "mla")
    assert mla == '"Untitled Draft." n.d..' or mla.startswith('"Untitled Draft."')


def _full_doc():
    doc = _doc(["Ada Lovelace", "Charles Babbage"])
    doc.item_type = "article"
    doc.volume, doc.issue, doc.pages = "12", "3", "201-219"
    doc.publisher = "Scriptorium Press"
    return doc


def test_apa_with_volume_issue_pages():
    out = format_citation(_full_doc(), "apa")
    assert "Journal of Codicology, 12(3), 201-219." in out


def test_mla_with_volume_issue_pages():
    out = format_citation(_full_doc(), "mla")
    assert "Journal of Codicology, vol. 12, no. 3, 2024, pp. 201-219," in out


def test_chicago_with_volume_issue_pages():
    out = format_citation(_full_doc(), "chicago")
    assert "Journal of Codicology 12 (3): 201-219." in out


def test_bibtex_inproceedings_uses_booktitle():
    doc = _doc(["Ada Lovelace"])
    doc.item_type = "inproceedings"
    doc.venue = "Proc. Codicology Conf."
    doc.pages = "11-19"
    out = format_citation(doc, "bibtex")
    assert out.startswith("@inproceedings{")
    assert "booktitle = {Proc. Codicology Conf.}" in out
    assert "journal" not in out
    assert "pages = {11--19}" in out  # BibTeX page-range dashes


def test_bibtex_preprint_is_misc_with_note():
    doc = _doc(["Ada Lovelace"])
    doc.item_type = "preprint"
    doc.venue = None
    out = format_citation(doc, "bibtex")
    assert out.startswith("@misc{")
    assert "note = {Preprint}" in out


def test_unknown_style_rejected():
    with pytest.raises(ValueError):
        format_citation(_doc(["A B"]), "vancouver")


def test_format_citations_filters_and_sorts(store):
    a = make_paper(store, "Alpha Result", authors=["Zed Zulu"], year=2020,
                   status="cited")
    make_paper(store, "Beta Result", authors=["Ann Alpha"], year=2021,
               status="to-read")
    store.assign_project(a.id, "thesis")
    only_project = format_citations(store, "apa", project="thesis")
    assert "Alpha Result" in only_project and "Beta Result" not in only_project
    both = format_citations(store, "apa")
    # sorted by first-author surname: Alpha before Zulu
    assert both.index("Beta Result") < both.index("Alpha Result")
