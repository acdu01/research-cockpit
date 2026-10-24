"""PDF and note ingestion: extract, dedupe, resolve metadata, chunk, embed."""

from __future__ import annotations

import hashlib
import re
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from .apis import MetadataResolver, WorkMeta, fetch_pdf, normalize_doi
from .embed import Embedder
from .store import Chunk, Document, Store, new_id

DOI_RE = re.compile(r"\b(10\.\d{4,9}/[^\s\"<>]+)", re.IGNORECASE)

# WorkMeta fields copied verbatim onto Document records (DOI is special-cased
# because a PDF-extracted DOI can stand in when the resolver found none).
META_DOC_FIELDS = (
    "title", "authors", "year", "venue", "openalex_id", "s2_id",
    "item_type", "publication_date", "volume", "issue", "pages",
    "publisher", "url", "abstract", "issn", "isbn",
)


def _meta_kwargs(meta: WorkMeta | None) -> dict:
    if meta is None:
        return {}
    return {name: getattr(meta, name) for name in META_DOC_FIELDS if getattr(meta, name)}


@dataclass
class PageText:
    page: int  # 1-based
    text: str


def extract_pdf(path: Path) -> tuple[list[PageText], str | None]:
    """Returns (pages, best title guess: PDF metadata, else layout heuristic)."""
    import fitz  # pymupdf; lazy so non-PDF paths don't need it loaded

    pages = []
    with fitz.open(path) as doc:
        title = (doc.metadata or {}).get("title") or None
        if not title and len(doc):
            title = _guess_title_from_layout(doc[0])
        for i, page in enumerate(doc):
            text = page.get_text("text")
            if text.strip():
                pages.append(PageText(page=i + 1, text=text))
    return pages, title


def _guess_title_from_layout(page) -> str | None:
    """The paper title is almost always the largest-font text on page 1.

    Only trusts the guess when that font is clearly larger than the page's
    typical text, so uniform-font documents fall back to other sources.
    """
    lines: list[tuple[float, float, str]] = []  # (font_size, y, text)
    for block in page.get_text("dict").get("blocks", []):
        for line in block.get("lines", []):
            direction = line.get("dir", (1, 0))
            if abs(direction[0] - 1) > 0.01:  # rotated text = arXiv-style watermark
                continue
            spans = line.get("spans", [])
            text = " ".join(s.get("text", "").strip() for s in spans).strip()
            if not text or text.lower().startswith("arxiv:"):
                continue
            lines.append((max(s.get("size", 0.0) for s in spans), line["bbox"][1], text))
    if len(lines) < 2:
        return None
    sizes = sorted(size for size, _, _ in lines)
    median = sizes[(len(sizes) - 1) // 2]  # lower median: title must beat body text
    max_size = sizes[-1]
    if max_size < median * 1.2:
        return None
    picked = sorted(
        (y, text) for size, y, text in lines if size >= max_size - 0.5
    )[:3]
    title = " ".join(text for _, text in picked).strip()
    return title if 2 <= len(title.split()) <= 40 else None


def pdf_page_count(path: Path) -> int:
    import fitz

    with fitz.open(path) as doc:
        return len(doc)


def render_pdf_page(
    path: Path, page_no: int, zoom: float = 2.0, highlight: str | None = None
) -> bytes:
    """Render one page (1-based) to PNG bytes - used by the UI's reader.

    With `highlight`, every occurrence on the page gets a warm-gold marker
    (drawn on the render only; the file on disk is untouched).
    """
    import fitz

    with fitz.open(path) as doc:
        index = max(0, min(page_no - 1, len(doc) - 1))
        page = doc[index]
        if highlight and highlight.strip():
            for rect in page.search_for(highlight.strip()):
                annot = page.add_highlight_annot(rect)
                annot.set_colors(stroke=(0.93, 0.80, 0.42))
                annot.update()
        matrix = fitz.Matrix(zoom, zoom)
        return page.get_pixmap(matrix=matrix).tobytes("png")


@dataclass
class PdfMatch:
    page: int  # 1-based
    count: int  # occurrences on that page
    snippet: str  # text around the first occurrence


def search_pdf(path: Path, query: str, max_pages: int = 50) -> list[PdfMatch]:
    """Find pages containing `query` (case-insensitive), with context snippets."""
    import fitz

    query = query.strip()
    if not query:
        return []
    matches: list[PdfMatch] = []
    with fitz.open(path) as doc:
        for i, page in enumerate(doc):
            rects = page.search_for(query)
            if not rects:
                continue
            text = page.get_text("text")
            pos = text.lower().find(query.lower())
            if pos == -1:  # hit spans a line break; fall back to the page head
                snippet = " ".join(text.split()[:20])
            else:
                start, end = max(0, pos - 70), pos + len(query) + 70
                snippet = " ".join(text[start:end].split())
            matches.append(PdfMatch(page=i + 1, count=len(rects), snippet=snippet))
            if len(matches) >= max_pages:
                break
    return matches


def find_doi(text: str) -> str | None:
    match = DOI_RE.search(text)
    if not match:
        return None
    return match.group(1).rstrip(".,;)")


def approx_tokens(text: str) -> int:
    return len(text.split())


def chunk_pages(
    pages: list[PageText], target_tokens: int = 512, overlap: int = 64
) -> list[tuple[str, int | None, int]]:
    """Sliding window over whitespace tokens, page-aware.

    Returns list of (text, page, token_count). `page` is the page the chunk
    starts on. Token counts approximate model tokens with whitespace words -
    close enough for sizing retrieval units.
    """
    validate_chunk_settings(target_tokens, overlap)
    words: list[tuple[str, int | None]] = []
    for page in pages:
        words.extend((w, page.page) for w in page.text.split())
    if not words:
        return []
    step = max(1, target_tokens - overlap)
    chunks = []
    for start in range(0, len(words), step):
        window = words[start : start + target_tokens]
        if not window:
            break
        text = " ".join(w for w, _ in window)
        chunks.append((text, window[0][1], len(window)))
        if start + target_tokens >= len(words):
            break
    return chunks


def validate_chunk_settings(target_tokens: int, overlap: int) -> None:
    if target_tokens <= 0 or not 0 <= overlap < target_tokens:
        raise ValueError("Chunk size must be positive and overlap between 0 and size - 1")


def _prepare_chunks(
    embedder: Embedder,
    doc_id: str,
    chunks: list[tuple[str, int | None, int]],
) -> tuple[list[Chunk], np.ndarray]:
    """Do model work before starting a database transaction."""
    if not chunks:
        return [], np.empty((0, embedder.dim), dtype=np.float32)
    records = [
        Chunk(id=new_id(), document_id=doc_id, ordinal=i, text=text, page=page,
              token_count=tokens)
        for i, (text, page, tokens) in enumerate(chunks)
    ]
    embeddings = embedder.encode([c.text for c in records])
    return records, embeddings


@dataclass
class IngestResult:
    document: Document
    chunks: int
    deduped: bool = False
    resolved: bool = False
    downloaded: bool = False


def ingest_pdf(
    store: Store,
    embedder: Embedder,
    path: Path,
    resolver: MetadataResolver | None = None,
    chunk_tokens: int = 512,
    chunk_overlap: int = 64,
    known_meta: WorkMeta | None = None,
) -> IngestResult:
    path = Path(path).expanduser().resolve()
    content_hash = hashlib.sha256(path.read_bytes()).hexdigest()
    existing = store.find_by_hash(content_hash)
    if existing:
        if not existing.source_path or not Path(existing.source_path).is_file():
            store.update_document(existing.id, source_path=str(path))
            existing = store.get_document(existing.id)
        return IngestResult(existing, store.chunk_count(existing.id), deduped=True)

    pages, meta_title = extract_pdf(path)
    first_pages_text = "\n".join(p.text for p in pages[:3])
    doi = find_doi(first_pages_text)
    title = meta_title or path.stem.replace("_", " ").replace("-", " ").strip()

    meta = known_meta
    if meta is None and resolver is not None:
        meta = resolver.resolve(doi=doi, title=meta_title)

    # A metadata-only record with this DOI (bib import, or a DOI add that
    # found no open-access PDF) gets the content attached instead of a
    # duplicate document.
    doc_doi = (meta.doi if meta and meta.doi else None) or doi
    stub = store.find_by_doi(doc_doi) if doc_doi else None
    if stub and store.chunk_count(stub.id) == 0:
        updates: dict = {"source_path": str(path), "content_hash": content_hash}
        if meta:
            for field_name in META_DOC_FIELDS:
                if not getattr(stub, field_name) and getattr(meta, field_name):
                    updates[field_name] = getattr(meta, field_name)
        # a title that is just the DOI is a placeholder - upgrade it
        if stub.title in (None, "", stub.doi) and "title" not in updates:
            better = (meta.title if meta and meta.title else None) or meta_title
            if better:
                updates["title"] = better
        records, embeddings = _prepare_chunks(
            embedder, stub.id, chunk_pages(pages, chunk_tokens, chunk_overlap)
        )
        with store.transaction():
            store.update_document(stub.id, **updates)
            store.add_chunks(records, embeddings)
        return IngestResult(
            store.get_document(stub.id), len(records), resolved=meta is not None
        )

    doc = Document(
        id=new_id(),
        collection="papers",
        doi=(meta.doi if meta and meta.doi else doi),
        source_path=str(path),
        content_hash=content_hash,
        status="to-read",
        **{"title": title, **_meta_kwargs(meta)},
    )
    records, embeddings = _prepare_chunks(
        embedder, doc.id, chunk_pages(pages, chunk_tokens, chunk_overlap)
    )
    with store.transaction():
        store.add_document(doc)
        store.add_chunks(records, embeddings)
    return IngestResult(doc, len(records), resolved=meta is not None)


def _doi_filename(doi: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "_", doi) + ".pdf"


def ingest_uploaded_pdf(
    store: Store,
    embedder: Embedder,
    data: bytes,
    filename: str,
    pdf_dir: Path,
    resolver: MetadataResolver | None = None,
    chunk_tokens: int = 512,
    chunk_overlap: int = 64,
) -> IngestResult:
    """Keep uploaded papers in managed storage so the Reader survives restarts."""
    import fitz

    # Reject invalid uploads before writing files or creating library records.
    with fitz.open(stream=data, filetype="pdf") as pdf:
        if not pdf.is_pdf or not len(pdf):
            raise ValueError("Upload a PDF containing at least one page")
    digest = hashlib.sha256(data).hexdigest()
    name = Path(filename.replace("\\", "/")).name
    if not name or name in (".", ".."):
        name = "paper.pdf"
    dest = Path(pdf_dir).expanduser().resolve() / digest / name
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(data)
    return ingest_pdf(
        store, embedder, dest, resolver=resolver,
        chunk_tokens=chunk_tokens, chunk_overlap=chunk_overlap,
    )


def ingest_doi(
    store: Store,
    embedder: Embedder,
    ref: str,
    resolver: MetadataResolver,
    pdf_dir: Path,
    chunk_tokens: int = 512,
    chunk_overlap: int = 64,
    fetch: Callable[[str], bytes | None] = fetch_pdf,
) -> IngestResult:
    """Ingest from a DOI or doi.org link: resolve metadata, search for an
    open-access PDF (OpenAlex/S2), download + ingest it. Falls back to a
    metadata-only to-read record when no OA copy is found."""
    doi = normalize_doi(ref)
    if doi is None:
        raise ValueError(f"'{ref}' does not contain a DOI")

    existing = store.find_by_doi(doi)
    if existing and store.chunk_count(existing.id) > 0:
        return IngestResult(existing, store.chunk_count(existing.id), deduped=True)

    meta = resolver.resolve(doi=doi)
    pdf_bytes = fetch(meta.pdf_url) if meta and meta.pdf_url else None
    if pdf_bytes:
        pdf_dir = Path(pdf_dir).expanduser()
        pdf_dir.mkdir(parents=True, exist_ok=True)
        dest = pdf_dir / _doi_filename(doi)
        dest.write_bytes(pdf_bytes)
        if not meta.doi:
            meta.doi = doi
        result = ingest_pdf(
            store, embedder, dest, known_meta=meta,
            chunk_tokens=chunk_tokens, chunk_overlap=chunk_overlap,
        )
        result.downloaded = not result.deduped
        result.resolved = True
        _backfill_metadata_by_title(store, resolver, result.document, doi)
        result.document = store.get_document(result.document.id)
        return result

    # no OA PDF found - record what we know so the paper still enters the KB
    if existing:
        return IngestResult(existing, 0, deduped=True, resolved=meta is not None)
    doc = Document(
        id=new_id(),
        collection="papers",
        doi=doi,
        status="to-read",
        **{"title": doi, **_meta_kwargs(meta)},
    )
    store.add_document(doc)
    return IngestResult(doc, 0, resolved=meta is not None)


def _norm_title(title: str | None) -> str:
    return re.sub(r"[^a-z0-9]", "", (title or "").lower())


def _backfill_metadata_by_title(
    store: Store, resolver: MetadataResolver, doc: Document, doi: str
) -> None:
    """When DOI-index lookups came back empty (e.g. arXiv DOIs, rate limits)
    but the PDF yielded a real title, resolve by title - accepted only on an
    exact normalized title match, so we never attach the wrong paper."""
    if doc.year or doc.authors:
        return
    if not doc.title or _norm_title(doc.title) == _norm_title(doi):
        return
    meta = resolver.resolve(title=doc.title)
    if meta is None or _norm_title(meta.title) != _norm_title(doc.title):
        return
    updates = {
        field_name: getattr(meta, field_name)
        for field_name in META_DOC_FIELDS
        if field_name != "title"  # the title is the match key - never touch it
        and not getattr(doc, field_name) and getattr(meta, field_name)
    }
    if updates:
        store.update_document(doc.id, **updates)


def ingest_note(
    store: Store,
    embedder: Embedder,
    text: str,
    title: str,
    source_path: str | None = None,
    tags: list[str] | None = None,
    chunk_tokens: int = 512,
    chunk_overlap: int = 64,
) -> IngestResult:
    """Notes: same chunk+embed path; no metadata resolution, no lifecycle."""
    content_hash = hashlib.sha256(text.encode()).hexdigest()
    existing = store.find_by_hash(content_hash)
    if existing:
        return IngestResult(existing, store.chunk_count(existing.id), deduped=True)
    doc = Document(
        id=new_id(),
        collection="notes",
        title=title,
        source_path=source_path,
        content_hash=content_hash,
        status=None,
    )
    pages = [PageText(page=0, text=text)]
    chunks = chunk_pages(pages, chunk_tokens, chunk_overlap)
    chunks = [(t, None, n) for t, _, n in chunks]  # notes have no pages
    records, embeddings = _prepare_chunks(embedder, doc.id, chunks)
    with store.transaction():
        store.add_document(doc)
        if tags:
            store.tag_document(doc.id, *tags)
        store.add_chunks(records, embeddings)
    return IngestResult(doc, len(records))
