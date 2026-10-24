"""BibTeX import/export (papers collection only)."""

from __future__ import annotations

import re

import bibtexparser
from bibtexparser.bibdatabase import BibDatabase

from .store import Document, Store, new_id

_ENTRYTYPES = {"article": "article", "inproceedings": "inproceedings",
               "book": "book", "preprint": "misc", "misc": "misc"}
_ITEM_TYPE_FROM_ENTRY = {"article": "article", "inproceedings": "inproceedings",
                         "conference": "inproceedings", "book": "book",
                         "unpublished": "preprint"}


def _entry_for(doc: Document) -> dict:
    """Full BibTeX entry dict for a document (shared by export and cite)."""
    entrytype = _ENTRYTYPES.get(doc.item_type or "", "article" if doc.venue else "misc")
    entry = {"ENTRYTYPE": entrytype, "ID": _cite_key(doc), "title": doc.title or "Untitled"}
    if doc.authors:
        entry["author"] = " and ".join(doc.authors)
    if doc.year:
        entry["year"] = str(doc.year)
    if doc.venue:
        # proceedings use booktitle; journals (and preprint venues) use journal
        entry["booktitle" if entrytype == "inproceedings" else "journal"] = doc.venue
    if doc.volume:
        entry["volume"] = doc.volume
    if doc.issue:
        entry["number"] = doc.issue
    if doc.pages:
        entry["pages"] = doc.pages.replace("-", "--", 1) if "--" not in doc.pages else doc.pages
    if doc.publisher:
        entry["publisher"] = doc.publisher
    if doc.doi:
        entry["doi"] = doc.doi
    if doc.url:
        entry["url"] = doc.url
    if doc.issn:
        entry["issn"] = doc.issn
    if doc.isbn:
        entry["isbn"] = doc.isbn
    if doc.item_type == "preprint":
        entry["note"] = "Preprint"
    return entry


def _cite_key(doc: Document) -> str:
    author = "anon"
    if doc.authors:
        author = re.sub(r"[^a-z]", "", doc.authors[0].split()[-1].lower()) or "anon"
    year = str(doc.year) if doc.year else "n.d."
    word = "untitled"
    if doc.title:
        for candidate in re.findall(r"[a-z]{3,}", doc.title.lower()):
            if candidate not in ("the", "and", "for", "with", "from"):
                word = candidate
                break
    return f"{author}{year}{word}"


def export_bibtex(
    store: Store,
    tag: str | None = None,
    status: str | None = None,
    project: str | None = None,
) -> str:
    docs = store.list_documents(collection="papers", status=status, tag=tag,
                                project=project)
    db = BibDatabase()
    entries = []
    seen_keys: set[str] = set()
    for doc in docs:
        entry = _entry_for(doc)
        if entry["ID"] in seen_keys:
            entry["ID"] = f"{entry['ID']}{doc.id[:4]}"
        seen_keys.add(entry["ID"])
        entries.append(entry)
    db.entries = entries
    return bibtexparser.dumps(db)


# --------------------------------------------------------- citation styles

CITATION_STYLES = ("apa", "mla", "chicago", "bibtex")


def _split_name(name: str) -> tuple[str, str]:
    """'First Middle Last' -> (first_part, last)."""
    parts = name.strip().split()
    if len(parts) == 1:
        return "", parts[0]
    return " ".join(parts[:-1]), parts[-1]


def _apa_name(name: str) -> str:
    first, last = _split_name(name)
    initials = " ".join(f"{p[0]}." for p in first.split() if p)
    return f"{last}, {initials}" if initials else last


def _apa_authors(authors: list[str]) -> str:
    names = [_apa_name(a) for a in authors]
    if not names:
        return ""
    if len(names) == 1:
        return names[0]
    return ", ".join(names[:-1]) + ", & " + names[-1]


def _mla_authors(authors: list[str]) -> str:
    if not authors:
        return ""
    first, last = _split_name(authors[0])
    lead = f"{last}, {first}" if first else last
    if len(authors) == 1:
        return lead
    if len(authors) == 2:
        return f"{lead}, and {authors[1].strip()}"
    return f"{lead}, et al."


def _chicago_authors(authors: list[str]) -> str:
    if not authors:
        return ""
    first, last = _split_name(authors[0])
    lead = f"{last}, {first}" if first else last
    if len(authors) == 1:
        return lead
    rest = [a.strip() for a in authors[1:]]
    if len(rest) == 1:
        return f"{lead}, and {rest[0]}"
    return f"{lead}, " + ", ".join(rest[:-1]) + f", and {rest[-1]}"


def format_citation(doc: Document, style: str) -> str:
    """One formatted citation. 'bibtex' gives the LaTeX-importable entry."""
    if style not in CITATION_STYLES:
        raise ValueError(f"style must be one of {CITATION_STYLES}")
    title = doc.title or "Untitled"
    year = str(doc.year) if doc.year else "n.d."
    venue = doc.venue or ""
    doi_url = f"https://doi.org/{doc.doi}" if doc.doi else ""

    if style == "bibtex":
        db = BibDatabase()
        db.entries = [_entry_for(doc)]
        return bibtexparser.dumps(db).strip()

    if style == "apa":
        parts = [f"{_apa_authors(doc.authors)} ({year}). {title}." if doc.authors
                 else f"{title}. ({year})."]
        if venue:
            ref = venue
            if doc.volume:
                ref += f", {doc.volume}"
                if doc.issue:
                    ref += f"({doc.issue})"
            if doc.pages:
                ref += f", {doc.pages}"
            parts.append(f"{ref}.")
        elif doc.publisher:
            parts.append(f"{doc.publisher}.")
        if doi_url:
            parts.append(doi_url)
        return " ".join(parts)

    if style == "mla":
        parts = []
        if doc.authors:
            parts.append(f"{_mla_authors(doc.authors)}.")
        parts.append(f'"{title}."')
        tail = [venue] if venue else []
        if doc.volume:
            tail.append(f"vol. {doc.volume}")
        if doc.issue:
            tail.append(f"no. {doc.issue}")
        tail.append(year)
        if doc.pages:
            tail.append(f"pp. {doc.pages}")
        if doc.doi:
            tail.append(f"doi:{doc.doi}")
        parts.append(", ".join(tail) + ".")
        return " ".join(parts)

    # chicago (author-date)
    parts = []
    if doc.authors:
        parts.append(f"{_chicago_authors(doc.authors)}.")
    parts.append(f"{year}.")
    parts.append(f'"{title}."')
    if venue:
        ref = venue
        if doc.volume:
            ref += f" {doc.volume}"
            if doc.issue:
                ref += f" ({doc.issue})"
        if doc.pages:
            ref += f": {doc.pages}"
        parts.append(f"{ref}.")
    elif doc.publisher:
        parts.append(f"{doc.publisher}.")
    if doi_url:
        parts.append(f"{doi_url}.")
    return " ".join(parts)


def format_citations(
    store: Store,
    style: str,
    tag: str | None = None,
    status: str | None = None,
    project: str | None = None,
) -> str:
    """Formatted citation list for the filtered papers, sorted by first author."""
    docs = store.list_documents(collection="papers", status=status, tag=tag,
                                project=project)
    docs.sort(key=lambda d: ((d.authors[0].split()[-1].lower() if d.authors else "~"),
                             d.year or 0))
    return "\n\n".join(format_citation(d, style) for d in docs)


def import_bibtex(store: Store, bibtex_text: str) -> list[Document]:
    """Seed metadata-only paper records (no PDF, no chunks). Dedupes on DOI."""
    db = bibtexparser.loads(bibtex_text)
    created = []
    for entry in db.entries:
        doi = entry.get("doi")
        if doi and store.find_by_doi(doi):
            continue
        authors = [
            a.strip() for a in re.split(r"\s+and\s+", entry.get("author", "")) if a.strip()
        ]
        # BibTeX "Last, First" -> "First Last"
        authors = [
            " ".join(reversed([p.strip() for p in a.split(",", 1)])) if "," in a else a
            for a in authors
        ]
        year = None
        if entry.get("year") and entry["year"].strip().isdigit():
            year = int(entry["year"].strip())
        entrytype = (entry.get("ENTRYTYPE") or "").lower()
        pages = (entry.get("pages") or "").replace("--", "-").strip() or None
        doc = Document(
            id=new_id(),
            collection="papers",
            title=entry.get("title", "").strip("{} ") or None,
            authors=authors,
            year=year,
            venue=entry.get("journal") or entry.get("booktitle"),
            doi=doi,
            status="to-read",
            item_type=_ITEM_TYPE_FROM_ENTRY.get(entrytype),
            volume=entry.get("volume") or None,
            issue=entry.get("number") or None,
            pages=pages,
            publisher=entry.get("publisher") or None,
            url=entry.get("url") or None,
            issn=entry.get("issn") or None,
            isbn=entry.get("isbn") or None,
            abstract=entry.get("abstract") or None,
        )
        store.add_document(doc)
        created.append(doc)
    return created
