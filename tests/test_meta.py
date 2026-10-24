"""M8: full citation records - API parsing, merge, migration, backfill."""

from __future__ import annotations

import sqlite3

import pytest

from conftest import make_paper
from research_cockpit.apis import (
    MetadataResolver,
    OpenAlexClient,
    S2Client,
    WorkMeta,
    abstract_from_inverted_index,
)
from research_cockpit.meta import (
    CORE_FIELDS,
    backfill_document,
    incomplete_documents,
    missing_fields,
    set_field,
)
from research_cockpit.store import Store

OPENALEX_WORK = {
    "id": "https://openalex.org/W100",
    "display_name": "Humidity and the Cockling of Parchment Folios",
    "publication_year": 2019,
    "publication_date": "2019-03-14",
    "doi": "https://doi.org/10.1234/parchment.2019",
    "type": "article",
    "type_crossref": "journal-article",
    "authorships": [
        {"author": {"display_name": "Beatrice of Ravenna"}},
        {"author": {"display_name": "Odo the Scribe"}},
    ],
    "biblio": {"volume": "12", "issue": "3", "first_page": "201", "last_page": "219"},
    "primary_location": {
        "landing_page_url": "https://journal.example/parchment",
        "source": {
            "display_name": "Journal of Codicology",
            "type": "journal",
            "issn_l": "1234-5678",
            "issn": ["1234-5678", "8765-4321"],
            "host_organization_name": "Scriptorium Press",
        },
    },
    "abstract_inverted_index": {
        "Stable": [0], "humidity": [1], "halts": [2], "cockling.": [3],
    },
}

S2_PAPER = {
    "paperId": "abc123",
    "title": "Humidity and the Cockling of Parchment Folios",
    "year": 2019,
    "venue": "Journal of Codicology",
    "publicationDate": "2019-03-14",
    "publicationTypes": ["JournalArticle"],
    "journal": {"name": "Journal of Codicology", "volume": "12", "pages": "201-219"},
    "publicationVenue": {"type": "journal", "issn": "1234-5678"},
    "url": "https://www.semanticscholar.org/paper/abc123",
    "abstract": "Stable humidity halts cockling.",
    "externalIds": {"DOI": "10.1234/parchment.2019"},
    "authors": [{"name": "Beatrice of Ravenna"}, {"name": "Odo the Scribe"}],
    "openAccessPdf": {"url": "https://oa.example/parchment.pdf"},
}


def test_abstract_reconstruction_from_inverted_index():
    index = {"cockling.": [3], "Stable": [0], "humidity": [1], "halts": [2]}
    assert abstract_from_inverted_index(index) == "Stable humidity halts cockling."
    assert abstract_from_inverted_index(None) is None
    assert abstract_from_inverted_index({}) is None


def test_openalex_parses_full_record():
    meta = OpenAlexClient._parse_work(OPENALEX_WORK)
    assert meta.title == "Humidity and the Cockling of Parchment Folios"
    assert meta.authors == ["Beatrice of Ravenna", "Odo the Scribe"]  # order kept
    assert meta.year == 2019
    assert meta.publication_date == "2019-03-14"
    assert meta.item_type == "article"
    assert meta.venue == "Journal of Codicology"
    assert meta.volume == "12" and meta.issue == "3" and meta.pages == "201-219"
    assert meta.publisher == "Scriptorium Press"
    assert meta.doi == "10.1234/parchment.2019"
    assert meta.url == "https://journal.example/parchment"
    assert meta.issn == "1234-5678"
    assert meta.abstract == "Stable humidity halts cockling."


def test_openalex_item_type_mapping():
    def typed(**kw):
        return OpenAlexClient._parse_work({"display_name": "T", **kw}).item_type

    assert typed(type="article", type_crossref="proceedings-article") == "inproceedings"
    assert typed(type="preprint") == "preprint"
    assert typed(
        type="article",
        primary_location={"source": {"type": "repository"}},
    ) == "preprint"
    assert typed(type="book") == "book"
    assert typed(type="dataset") == "misc"
    assert typed() is None  # nothing known -> explicit null, not a guess


def test_s2_parses_full_record():
    meta = S2Client._parse_paper(S2_PAPER)
    assert meta.authors == ["Beatrice of Ravenna", "Odo the Scribe"]
    assert meta.item_type == "article"
    assert meta.publication_date == "2019-03-14"
    assert meta.volume == "12" and meta.pages == "201-219"
    assert meta.url == "https://www.semanticscholar.org/paper/abc123"
    assert meta.abstract == "Stable humidity halts cockling."
    assert meta.issn == "1234-5678"
    assert meta.pdf_url == "https://oa.example/parchment.pdf"


def test_s2_arxiv_only_paper_is_preprint():
    meta = S2Client._parse_paper({
        "paperId": "x", "title": "T", "venue": "",
        "publicationTypes": None,
        "externalIds": {"ArXiv": "1901.00001"},
        "authors": [],
    })
    assert meta.item_type == "preprint"


def test_resolver_merges_s2_gaps_into_openalex_hit():
    """OpenAlex primary hit missing abstract/pdf gets them from one S2 call,
    without S2 overwriting anything OpenAlex provided."""

    class FakeOA:
        def work_by_doi(self, doi):
            return WorkMeta(title="T", year=2019, venue="Journal of Codicology",
                            doi=doi, openalex_id="W100", publisher="Scriptorium Press")

        def work_by_title(self, title):
            return None

    class FakeS2:
        calls = 0

        def work_by_doi(self, doi):
            FakeS2.calls += 1
            return WorkMeta(title="different title (must not win)", s2_id="abc123",
                            abstract="Stable humidity halts cockling.",
                            pdf_url="https://oa.example/p.pdf", publication_date="2019-03-14")

        def work_by_title(self, title):
            return None

        def work_by_arxiv(self, arxiv_id):
            return None

    resolver = MetadataResolver.__new__(MetadataResolver)
    resolver.openalex, resolver.s2 = FakeOA(), FakeS2()
    meta = resolver.resolve(doi="10.1234/parchment.2019")
    assert meta.title == "T"  # primary hit not overwritten
    assert meta.publisher == "Scriptorium Press"
    assert meta.s2_id == "abc123"
    assert meta.abstract == "Stable humidity halts cockling."
    assert meta.pdf_url == "https://oa.example/p.pdf"
    assert meta.publication_date == "2019-03-14"
    assert FakeS2.calls == 1


def test_citation_columns_migration(tmp_path):
    """A pre-M8 database gains the citation columns without losing data."""
    db = tmp_path / "old.db"
    conn = sqlite3.connect(db)
    conn.execute(
        """CREATE TABLE documents (id TEXT PRIMARY KEY, collection TEXT NOT NULL
               CHECK (collection IN ('papers','notes')), title TEXT,
               authors TEXT NOT NULL DEFAULT '[]', year INTEGER, venue TEXT, doi TEXT,
               openalex_id TEXT, s2_id TEXT, source_path TEXT, content_hash TEXT,
               status TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL)"""
    )
    conn.execute(
        "INSERT INTO documents (id, collection, title, created_at, updated_at)"
        " VALUES ('d1', 'papers', 'Legacy Paper', 't', 't')"
    )
    conn.commit()
    conn.close()
    store = Store(db)
    doc = store.get_document("d1")
    assert doc.title == "Legacy Paper"
    assert doc.volume is None and doc.item_type is None  # explicit nulls
    store.update_document("d1", volume="7", item_type="article")
    assert store.get_document("d1").volume == "7"
    store.close()


def test_missing_fields_and_incomplete(store):
    doc = make_paper(store, "Bare Paper")
    gaps = missing_fields(doc)
    assert "authors" in gaps and "year" in gaps and "abstract" in gaps
    assert "title" not in gaps
    rows = incomplete_documents(store)
    assert [d.id for d, _ in rows] == [doc.id]
    assert set(rows[0][1]) == set(CORE_FIELDS) - {"title"}


def test_set_field_validates_and_persists(store):
    doc = make_paper(store, "P")
    set_field(store, doc, "year", "2019")
    set_field(store, doc, "item_type", "article")
    set_field(store, doc, "authors", "Beatrice of Ravenna and Odo the Scribe")
    set_field(store, doc, "pages", "201-219")
    fresh = store.get_document(doc.id)
    assert fresh.year == 2019
    assert fresh.authors == ["Beatrice of Ravenna", "Odo the Scribe"]
    assert fresh.pages == "201-219"
    with pytest.raises(ValueError, match="item_type"):
        set_field(store, doc, "item_type", "sonnet")
    with pytest.raises(ValueError, match="integer"):
        set_field(store, doc, "year", "MMXIX")
    with pytest.raises(ValueError, match="not a citation field"):
        set_field(store, doc, "status", "cited")


class OneShotResolver:
    """Resolver stub returning one canned WorkMeta."""

    def __init__(self, meta):
        self.meta = meta
        self.calls = []

    def resolve(self, doi=None, title=None):
        self.calls.append((doi, title))
        return self.meta


def test_backfill_fills_only_missing_fields(store):
    doc = make_paper(store, "Humidity and the Cockling of Parchment Folios",
                     doi="10.1234/parchment.2019", venue="MY HAND-FIXED VENUE")
    resolver = OneShotResolver(OpenAlexClient._parse_work(OPENALEX_WORK))
    result = backfill_document(store, resolver, doc)
    assert result.resolved
    fresh = store.get_document(doc.id)
    assert fresh.venue == "MY HAND-FIXED VENUE"  # manual value survives
    assert fresh.authors == ["Beatrice of Ravenna", "Odo the Scribe"]
    assert fresh.volume == "12" and fresh.pages == "201-219"
    assert fresh.publisher == "Scriptorium Press"
    assert "venue" not in result.filled and "authors" in result.filled


def test_backfill_unresolved_and_complete_paths(store):
    doc = make_paper(store, "Unknown Codex")
    result = backfill_document(store, OneShotResolver(None), doc)
    assert not result.resolved and result.filled == []
    # a fully complete record never even hits the network
    resolver = OneShotResolver(None)
    complete = make_paper(
        store, "Done", authors=["A"], year=2000, venue="V", doi="10.1/d",
        openalex_id="W1", s2_id="s", source_path="x", content_hash="h",
        item_type="article", publication_date="2000-01-01", volume="1", issue="1",
        pages="1-2", publisher="P", url="u", abstract="a", issn="i", isbn="b",
    )
    result = backfill_document(store, resolver, complete)
    assert result.resolved and result.filled == [] and resolver.calls == []
