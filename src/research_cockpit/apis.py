"""OpenAlex (default, keyless) and Semantic Scholar (optional key) clients.

Both normalize works into a common `WorkMeta` shape. Failures return None /
empty lists - callers degrade gracefully rather than crash an ingest.
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, field

import httpx

OPENALEX_BASE = "https://api.openalex.org"
S2_BASE = "https://api.semanticscholar.org/graph/v1"
S2_FIELDS = (
    "title,year,venue,authors,externalIds,paperId,openAccessPdf,"
    "abstract,url,publicationDate,publicationTypes,journal,publicationVenue"
)

DOI_PATTERN = re.compile(r"(10\.\d{4,9}/\S+)", re.IGNORECASE)
# arXiv DOIs are DataCite-registered and often missing from OpenAlex/S2's DOI
# index, but the paper is always at a deterministic arxiv.org PDF URL.
ARXIV_DOI_RE = re.compile(r"^10\.48550/arxiv\.(.+)$", re.IGNORECASE)


def arxiv_id_from_doi(doi: str | None) -> str | None:
    if not doi:
        return None
    match = ARXIV_DOI_RE.match(doi)
    return match.group(1) if match else None


def arxiv_pdf_url(arxiv_id: str) -> str:
    return f"https://arxiv.org/pdf/{arxiv_id}"


@dataclass
class WorkMeta:
    title: str | None = None
    authors: list[str] = field(default_factory=list)
    year: int | None = None
    venue: str | None = None  # container title: journal / conference / book
    doi: str | None = None
    openalex_id: str | None = None
    s2_id: str | None = None
    pdf_url: str | None = None  # open-access PDF location, when one exists
    # full-citation fields (M8) - None means the source API doesn't have it
    item_type: str | None = None  # article | inproceedings | book | preprint | misc
    publication_date: str | None = None  # ISO date
    volume: str | None = None
    issue: str | None = None
    pages: str | None = None
    publisher: str | None = None
    url: str | None = None
    abstract: str | None = None
    issn: str | None = None
    isbn: str | None = None

    def merge_from(self, other: WorkMeta | None) -> WorkMeta:
        """Fill this record's empty fields from `other` (never overwrites)."""
        if other is not None:
            for name in self.__dataclass_fields__:
                if not getattr(self, name) and getattr(other, name):
                    setattr(self, name, getattr(other, name))
        return self


@dataclass
class CitationEdges:
    references: list[WorkMeta] = field(default_factory=list)  # works this paper cites
    cited_by: list[WorkMeta] = field(default_factory=list)  # works citing this paper


def _short_openalex_id(url_or_id: str | None) -> str | None:
    if not url_or_id:
        return None
    return url_or_id.rstrip("/").rsplit("/", 1)[-1]  # https://openalex.org/W123 -> W123


def _bare_doi(doi: str | None) -> str | None:
    if not doi:
        return None
    return doi.removeprefix("https://doi.org/").removeprefix("http://doi.org/").strip()


def _get_with_backoff(
    client: httpx.Client, path: str, params: dict, retries: int = 2
) -> dict | None:
    """GET with 429 backoff (keyless S2 rate-limits aggressively)."""
    for attempt in range(retries + 1):
        try:
            resp = client.get(path, params=params)
            if resp.status_code == 429 and attempt < retries:
                time.sleep(1.0 + 2.0 * attempt)
                continue
            resp.raise_for_status()
            return resp.json()
        except httpx.HTTPError:
            return None
    return None


def abstract_from_inverted_index(index: dict | None) -> str | None:
    """OpenAlex ships abstracts as {word: [positions]}; rebuild the text."""
    if not index:
        return None
    positions = [(pos, word) for word, occurrences in index.items() for pos in occurrences]
    if not positions:
        return None
    return " ".join(word for _, word in sorted(positions))


def _item_type_openalex(work: dict) -> str | None:
    """Normalize OpenAlex work types into our vocabulary (see store.ITEM_TYPES)."""
    crossref = (work.get("type_crossref") or "").lower()
    oa_type = (work.get("type") or "").lower()
    source_type = (
        ((work.get("primary_location") or {}).get("source") or {}).get("type") or ""
    ).lower()
    if crossref == "proceedings-article" or source_type == "conference":
        return "inproceedings"
    if oa_type == "preprint" or crossref == "posted-content" or source_type == "repository":
        return "preprint"
    if oa_type == "book" or crossref in ("book", "monograph", "edited-book", "reference-book"):
        return "book"
    if crossref == "journal-article" or oa_type == "article":
        return "article"
    return "misc" if (oa_type or crossref) else None


_S2_TYPE_MAP = {"journalarticle": "article", "conference": "inproceedings", "book": "book"}


def _item_type_s2(paper: dict) -> str | None:
    types = [str(t).lower() for t in paper.get("publicationTypes") or []]
    for t in types:
        if t in _S2_TYPE_MAP:
            return _S2_TYPE_MAP[t]
    venue_type = ((paper.get("publicationVenue") or {}).get("type") or "").lower()
    if venue_type == "conference":
        return "inproceedings"
    if venue_type == "journal":
        return "article"
    if (paper.get("externalIds") or {}).get("ArXiv") and not paper.get("venue"):
        return "preprint"
    return "misc" if types else None


def _page_range(first: str | None, last: str | None) -> str | None:
    if first and last and first != last:
        return f"{first}-{last}"
    return first or last or None


def normalize_doi(ref: str) -> str | None:
    """Extract a bare DOI from a doi.org link, 'doi:' prefix, or bare DOI.

    Returns None if `ref` doesn't contain a DOI.
    """
    ref = ref.strip().removeprefix("doi:").removeprefix("DOI:")
    match = DOI_PATTERN.search(ref)
    if not match:
        return None
    return match.group(1).rstrip(".,;)\"'")


class OpenAlexClient:
    def __init__(self, mailto: str = "", timeout: float = 20.0):
        self.params = {"mailto": mailto} if mailto else {}
        self.client = httpx.Client(base_url=OPENALEX_BASE, timeout=timeout)

    def _get(self, path: str, **params) -> dict | None:
        return _get_with_backoff(self.client, path, {**self.params, **params})

    @staticmethod
    def _parse_work(work: dict) -> WorkMeta:
        primary = work.get("primary_location") or {}
        source = primary.get("source") or {}
        best_oa = work.get("best_oa_location") or {}
        open_access = work.get("open_access") or {}
        biblio = work.get("biblio") or {}
        pdf_url = (
            best_oa.get("pdf_url")
            or primary.get("pdf_url")
            or open_access.get("oa_url")
        )
        issns = source.get("issn") or []
        return WorkMeta(
            title=work.get("display_name"),
            authors=[
                a.get("author", {}).get("display_name")
                for a in work.get("authorships", [])
                if a.get("author", {}).get("display_name")
            ],
            year=work.get("publication_year"),
            venue=source.get("display_name"),
            doi=_bare_doi(work.get("doi")),
            openalex_id=_short_openalex_id(work.get("id")),
            pdf_url=pdf_url,
            item_type=_item_type_openalex(work),
            publication_date=work.get("publication_date"),
            volume=biblio.get("volume"),
            issue=biblio.get("issue"),
            pages=_page_range(biblio.get("first_page"), biblio.get("last_page")),
            publisher=source.get("host_organization_name"),
            url=primary.get("landing_page_url") or work.get("doi"),
            abstract=abstract_from_inverted_index(work.get("abstract_inverted_index")),
            issn=source.get("issn_l") or (issns[0] if issns else None),
        )

    def work_by_doi(self, doi: str) -> WorkMeta | None:
        data = self._get(f"/works/doi:{_bare_doi(doi)}")
        return self._parse_work(data) if data else None

    def work_by_title(self, title: str) -> WorkMeta | None:
        data = self._get("/works", search=title, per_page=1)
        results = (data or {}).get("results") or []
        return self._parse_work(results[0]) if results else None

    def work_raw(self, openalex_id: str) -> dict | None:
        return self._get(f"/works/{openalex_id}")

    def edges(self, openalex_id: str, max_neighbors: int = 50) -> CitationEdges:
        edges = CitationEdges()
        raw = self.work_raw(openalex_id)
        if raw:
            ref_ids = [_short_openalex_id(r) for r in raw.get("referenced_works", [])]
            ref_ids = [r for r in ref_ids if r][:max_neighbors]
            # referenced_works are bare IDs; batch-fetch titles (50 per filter call)
            for batch_start in range(0, len(ref_ids), 50):
                batch = ref_ids[batch_start : batch_start + 50]
                data = self._get(
                    "/works", filter=f"openalex_id:{'|'.join(batch)}", per_page=50
                )
                for work in (data or {}).get("results", []):
                    edges.references.append(self._parse_work(work))
        data = self._get(
            "/works", filter=f"cites:{openalex_id}", per_page=min(max_neighbors, 50)
        )
        for work in (data or {}).get("results", []):
            edges.cited_by.append(self._parse_work(work))
        return edges


class S2Client:
    def __init__(self, api_key: str = "", timeout: float = 20.0):
        headers = {"x-api-key": api_key} if api_key else {}
        self.client = httpx.Client(base_url=S2_BASE, timeout=timeout, headers=headers)

    def _get(self, path: str, **params) -> dict | None:
        return _get_with_backoff(self.client, path, params)

    @staticmethod
    def _parse_paper(paper: dict) -> WorkMeta:
        ext = paper.get("externalIds") or {}
        journal = paper.get("journal") or {}
        venue_info = paper.get("publicationVenue") or {}
        issns = venue_info.get("issn")
        return WorkMeta(
            title=paper.get("title"),
            authors=[a.get("name") for a in paper.get("authors", []) if a.get("name")],
            year=paper.get("year"),
            venue=paper.get("venue") or journal.get("name") or None,
            doi=_bare_doi(ext.get("DOI")),
            s2_id=paper.get("paperId"),
            pdf_url=(paper.get("openAccessPdf") or {}).get("url"),
            item_type=_item_type_s2(paper),
            publication_date=paper.get("publicationDate"),
            volume=journal.get("volume") or None,
            pages=journal.get("pages") or None,
            url=paper.get("url"),
            abstract=paper.get("abstract"),
            issn=issns if isinstance(issns, str) else (issns[0] if issns else None),
        )

    def work_by_doi(self, doi: str) -> WorkMeta | None:
        data = self._get(f"/paper/DOI:{_bare_doi(doi)}", fields=S2_FIELDS)
        return self._parse_paper(data) if data else None

    def work_by_title(self, title: str) -> WorkMeta | None:
        data = self._get("/paper/search", query=title, fields=S2_FIELDS, limit=1)
        papers = (data or {}).get("data") or []
        return self._parse_paper(papers[0]) if papers else None

    def work_by_arxiv(self, arxiv_id: str) -> WorkMeta | None:
        data = self._get(f"/paper/ARXIV:{arxiv_id}", fields=S2_FIELDS)
        return self._parse_paper(data) if data else None

    def edges(self, s2_id: str, max_neighbors: int = 50) -> CitationEdges:
        edges = CitationEdges()
        data = self._get(
            f"/paper/{s2_id}/references", fields=S2_FIELDS, limit=max_neighbors
        )
        for item in (data or {}).get("data", []):
            paper = item.get("citedPaper") or {}
            if paper.get("paperId"):
                edges.references.append(self._parse_paper(paper))
        data = self._get(
            f"/paper/{s2_id}/citations", fields=S2_FIELDS, limit=max_neighbors
        )
        for item in (data or {}).get("data", []):
            paper = item.get("citingPaper") or {}
            if paper.get("paperId"):
                edges.cited_by.append(self._parse_paper(paper))
        return edges


class MetadataResolver:
    """OpenAlex first, Semantic Scholar fallback (per config)."""

    def __init__(self, openalex: OpenAlexClient | None = None, s2: S2Client | None = None):
        self.openalex = openalex or OpenAlexClient()
        self.s2 = s2 or S2Client()

    def resolve(self, doi: str | None = None, title: str | None = None) -> WorkMeta | None:
        meta = None
        arxiv_id = arxiv_id_from_doi(doi)
        if doi:
            meta = self.openalex.work_by_doi(doi) or self.s2.work_by_doi(doi)
        if meta is None and arxiv_id:
            # arXiv DOIs are often absent from both DOI indexes; S2 knows the
            # paper by its arXiv id
            meta = self.s2.work_by_arxiv(arxiv_id)
        if meta is None and title:
            meta = self.openalex.work_by_title(title) or self.s2.work_by_title(title)
        if meta and not meta.doi and doi:
            meta.doi = doi
        # One provider rarely has everything (S2 knows OA PDFs and abstracts
        # OpenAlex misses, and vice versa): one extra S2 call fills the gaps
        # field-by-field, never overwriting what the primary hit provided.
        _gap_fields = ("pdf_url", "s2_id", "abstract", "publication_date",
                       "item_type", "volume", "pages", "url")
        if meta and meta.doi and not meta.s2_id and any(
            not getattr(meta, f) for f in _gap_fields
        ):
            meta.merge_from(self.s2.work_by_doi(meta.doi))
        # arXiv papers always have a deterministic open-access PDF URL - use it
        # even when every metadata index failed us
        if arxiv_id:
            if meta is None:
                meta = WorkMeta(doi=doi, pdf_url=arxiv_pdf_url(arxiv_id))
            elif not meta.pdf_url:
                meta.pdf_url = arxiv_pdf_url(arxiv_id)
        return meta


def fetch_pdf(url: str, timeout: float = 60.0) -> bytes | None:
    """Download a PDF, following redirects. Returns None unless the payload
    is actually a PDF (magic-byte check) - OA links sometimes land on HTML."""
    try:
        resp = httpx.get(
            url,
            follow_redirects=True,
            timeout=timeout,
            headers={"User-Agent": "research-cockpit/0.1 (personal library tool)"},
        )
        resp.raise_for_status()
    except httpx.HTTPError:
        return None
    data = resp.content
    return data if data[:5] == b"%PDF-" else None
