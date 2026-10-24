"""Citation-record completeness: inspect, backfill, and hand-fill metadata.

The document record carries the full CSL/BibTeX-grade citation fields (M8).
A NULL field means "the source APIs genuinely don't have this" - this module
surfaces those gaps and fills them, online (resolver, never overwriting) or
manually (`set_field`).
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from .apis import MetadataResolver
from .ingest import META_DOC_FIELDS
from .store import ITEM_TYPES, Document, Store

# Every citation field, in display order (title first, abstract last).
CITATION_FIELDS = (
    "title", "authors", "year", "publication_date", "item_type", "venue",
    "volume", "issue", "pages", "publisher", "doi", "url", "issn", "isbn",
    "abstract",
)

# A paper missing any of these can't be cited properly - `rc kb incomplete`
# flags them. The rest (volume/issue/pages/...) legitimately don't exist for
# many item types (preprints have no pages), so they don't count as core.
CORE_FIELDS = ("title", "authors", "year", "venue", "item_type")

_EDITABLE = tuple(f for f in CITATION_FIELDS)


def missing_fields(doc: Document, fields: tuple[str, ...] = CITATION_FIELDS) -> list[str]:
    """Citation fields that are NULL/empty on this document."""
    return [name for name in fields if not getattr(doc, name)]


@dataclass
class BackfillResult:
    document: Document
    filled: list[str]  # field names newly filled from the APIs
    resolved: bool  # False = no API match found


def backfill_document(store: Store, resolver: MetadataResolver, doc: Document) -> BackfillResult:
    """Re-resolve one paper and fill ONLY its empty fields.

    Non-null values are never overwritten, so manual fixes and previous
    resolutions always survive a re-run.
    """
    gaps = missing_fields(doc)
    if not gaps:
        return BackfillResult(doc, [], resolved=True)
    meta = resolver.resolve(doi=doc.doi, title=doc.title)
    if meta is None:
        return BackfillResult(doc, [], resolved=False)
    updates = {
        name: getattr(meta, name)
        for name in META_DOC_FIELDS
        if not getattr(doc, name) and getattr(meta, name)
    }
    if meta.doi and not doc.doi:
        updates["doi"] = meta.doi
    if updates:
        store.update_document(doc.id, **updates)
    return BackfillResult(store.get_document(doc.id), sorted(updates), resolved=True)


def incomplete_documents(store: Store) -> list[tuple[Document, list[str]]]:
    """Papers missing core citation fields, with what's missing."""
    result = []
    for doc in store.list_documents(collection="papers"):
        gaps = missing_fields(doc, CORE_FIELDS)
        if gaps:
            result.append((doc, gaps))
    return result


def set_field(store: Store, doc: Document, name: str, value: str) -> None:
    """Manually fill one citation field (validated). Empty value clears it."""
    if name not in _EDITABLE:
        raise ValueError(f"'{name}' is not a citation field (one of {', '.join(_EDITABLE)})")
    value = value.strip()
    parsed: object = value or None
    if name == "year" and value:
        if not value.isdigit():
            raise ValueError("year must be an integer")
        parsed = int(value)
    elif name == "item_type" and value:
        if value not in ITEM_TYPES:
            raise ValueError(f"item_type must be one of {', '.join(ITEM_TYPES)}")
    elif name == "authors":
        # comma- or " and "-separated, stored in the given order
        parsed = [a.strip() for a in re.split(r",|\s+and\s+", value) if a.strip()]
    store.update_document(doc.id, **{name: parsed})
