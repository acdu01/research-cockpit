"""Section-aware chunking (M12): detect headings from PDF layout, build a
section tree, and pack paragraphs within sections up to a token target.

Fallback: blind sliding-window chunker (same as ingest.chunk_pages) when
no headings are detected - fully backward-compatible.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from .ingest import PageText, validate_chunk_settings


@dataclass
class Section:
    title: str
    page: int
    paragraphs: list[str] = field(default_factory=list)


@dataclass
class SectionChunk:
    text: str
    page: int | None
    section: str | None
    token_count: int


def detect_headings(pages: list[PageText]) -> list[Section]:
    """Detect headings based on font-size and numbering patterns.

    Heuristic: a line is a heading if it starts with a section number pattern
    (1., 2.1, A., etc.) AND is short (<100 chars), OR is in ALL CAPS / Title
    Case and short. Falls back to paragraph segmentation if nothing matches.
    """
    heading_re = re.compile(
        r"^(?:"
        r"(?:\d{1,2}\.(?:\d{1,2}\.?)*)\s+"    # numbered: 1. or 2.1 or 3.1.2
        r"|(?:[A-Z][a-z][\w\s]{2,60}$)"       # title case
        r"|(?:[A-Z][A-Z\s]{3,60}$)"           # ALL CAPS
        r")"
    )
    sections: list[Section] = []
    current: Section | None = None

    for page in pages:
        for line in page.text.split("\n"):
            stripped = line.strip()
            if not stripped:
                continue
            if len(stripped) < 100 and heading_re.match(stripped):
                if current:
                    sections.append(current)
                current = Section(title=stripped, page=page.page)
            elif current:
                current.paragraphs.append(stripped)
            else:
                current = Section(title="", page=page.page)
                current.paragraphs.append(stripped)

    if current:
        sections.append(current)
    return sections


def chunk_sections(
    sections: list[Section],
    target_tokens: int = 512,
    overlap: int = 64,
) -> list[SectionChunk]:
    """Pack paragraphs within sections up to target_tokens. Oversized sections
    get a sliding window within themselves (same spirit as the blind chunker).
    """
    validate_chunk_settings(target_tokens, overlap)
    chunks: list[SectionChunk] = []
    for section in sections:
        words = " ".join(section.paragraphs).split()
        for start in range(0, len(words), target_tokens - overlap):
            window = words[start : start + target_tokens]
            chunks.append(SectionChunk(
                text=" ".join(window),
                page=section.page,
                section=section.title or None,
                token_count=len(window),
            ))
            if start + target_tokens >= len(words):
                break
    return chunks


def section_aware_chunk(
    pages: list[PageText],
    target_tokens: int = 512,
    overlap: int = 64,
) -> list[SectionChunk]:
    """Attempt section-aware chunking; fall back to flat chunking if no
    headings detected (returns SectionChunk with section=None in that case).
    """
    sections = detect_headings(pages)
    # If we got meaningful sections (more than just one un-titled blob), use them
    named_sections = [s for s in sections if s.title]
    if len(named_sections) >= 2:
        return chunk_sections(sections, target_tokens, overlap)
    # Fallback: flat chunking (mirrors ingest.chunk_pages behavior)
    from .ingest import chunk_pages

    flat = chunk_pages(pages, target_tokens, overlap)
    return [
        SectionChunk(text=text, page=page, section=None, token_count=tokens)
        for text, page, tokens in flat
    ]
