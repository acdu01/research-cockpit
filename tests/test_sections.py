"""M12: section-aware chunking - heading detection, boundaries, fallback."""

from __future__ import annotations

from research_cockpit.ingest import PageText
from research_cockpit.sections import (
    Section,
    chunk_sections,
    detect_headings,
    section_aware_chunk,
)

STRUCTURED_PAGES = [
    PageText(page=1, text=(
        "1. Introduction\n"
        "Parchment folios are sensitive to humidity.\n"
        "This paper studies cockling degradation.\n"
        "\n"
        "2. Methods\n"
        "We placed folios in controlled chambers.\n"
        "Humidity was varied from 30% to 80% RH.\n"
        "\n"
        "3. Results\n"
        "Cockling halted below 45% RH.\n"
        "Rate depended nonlinearly on moisture content.\n"
    )),
    PageText(page=2, text=(
        "4. Discussion\n"
        "Our findings align with prior conservation literature.\n"
        "The threshold at 45% has practical implications.\n"
        "\n"
        "5. Conclusion\n"
        "Stable humidity near 45% RH preserves parchment.\n"
    )),
]


def test_heading_detection():
    sections = detect_headings(STRUCTURED_PAGES)
    titles = [s.title for s in sections]
    assert "1. Introduction" in titles
    assert "3. Results" in titles
    assert "5. Conclusion" in titles
    assert len(sections) == 5


def test_section_chunks_respect_boundaries():
    sections = detect_headings(STRUCTURED_PAGES)
    chunks = chunk_sections(sections, target_tokens=100, overlap=10)
    for chunk in chunks:
        assert chunk.section is not None
    section_titles = [c.section for c in chunks]
    assert "1. Introduction" in section_titles
    assert "5. Conclusion" in section_titles


def test_fallback_when_no_headings():
    flat_text = "Just some plain text without any headings or numbering. " * 50
    flat_pages = [PageText(page=1, text=flat_text)]
    chunks = section_aware_chunk(flat_pages, target_tokens=20, overlap=5)
    assert all(c.section is None for c in chunks)
    assert len(chunks) >= 2


def test_section_aware_chunk_on_structured_pdf():
    chunks = section_aware_chunk(STRUCTURED_PAGES, target_tokens=100, overlap=10)
    named = [c for c in chunks if c.section]
    assert len(named) >= 3
    assert any("Introduction" in (c.section or "") for c in chunks)


def test_chunk_page_numbers_preserved():
    chunks = section_aware_chunk(STRUCTURED_PAGES, target_tokens=100, overlap=10)
    assert any(c.page == 2 for c in chunks)


def test_long_paragraph_is_split_and_zero_overlap_stays_zero():
    words = [f"word{i}" for i in range(25)]
    section = Section("Methods", 1, [" ".join(words)])
    chunks = chunk_sections([section], target_tokens=10, overlap=0)
    assert [c.token_count for c in chunks] == [10, 10, 5]
    assert " ".join(c.text for c in chunks).split() == words


def test_section_chunk_overlap_is_bounded():
    words = [f"word{i}" for i in range(25)]
    chunks = chunk_sections([Section("Results", 2, [" ".join(words)])], 10, 3)
    assert all(c.token_count <= 10 for c in chunks)
    assert chunks[0].text.split()[-3:] == chunks[1].text.split()[:3]
