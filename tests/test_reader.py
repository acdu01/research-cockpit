from __future__ import annotations

import fitz

from research_cockpit.ingest import pdf_page_count, render_pdf_page, search_pdf


def _two_page_pdf(path):
    doc = fitz.open()
    doc.new_page().insert_text((72, 90), "page one text")
    doc.new_page().insert_text((72, 90), "page two text")
    doc.save(path)


def test_page_count_and_render(tmp_path):
    path = tmp_path / "p.pdf"
    _two_page_pdf(path)
    assert pdf_page_count(path) == 2
    png = render_pdf_page(path, 1)
    assert png[:8] == b"\x89PNG\r\n\x1a\n"
    # out-of-range pages clamp instead of crashing
    assert render_pdf_page(path, 99)[:8] == b"\x89PNG\r\n\x1a\n"
    assert render_pdf_page(path, 0)[:8] == b"\x89PNG\r\n\x1a\n"
    # pages render distinct content
    assert render_pdf_page(path, 1) != render_pdf_page(path, 2)


def test_search_pdf_finds_pages_with_snippets(tmp_path):
    path = tmp_path / "p.pdf"
    _two_page_pdf(path)
    hits = search_pdf(path, "two")
    assert [h.page for h in hits] == [2]
    assert hits[0].count == 1
    assert "page two text" in hits[0].snippet
    # case-insensitive; blank queries are a no-op
    assert [h.page for h in search_pdf(path, "PAGE")] == [1, 2]
    assert search_pdf(path, "   ") == []
    assert search_pdf(path, "absent-term") == []


def test_render_highlight_changes_pixels_not_file(tmp_path):
    path = tmp_path / "p.pdf"
    _two_page_pdf(path)
    before = path.read_bytes()
    plain = render_pdf_page(path, 1)
    marked = render_pdf_page(path, 1, highlight="one")
    assert marked[:8] == b"\x89PNG\r\n\x1a\n"
    assert marked != plain
    # a query absent from the page renders identically
    assert render_pdf_page(path, 1, highlight="zzz-absent") == plain
    assert path.read_bytes() == before  # source PDF untouched
