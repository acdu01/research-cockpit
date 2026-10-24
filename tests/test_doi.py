from __future__ import annotations

import fitz
import pytest

from research_cockpit.apis import WorkMeta, normalize_doi
from research_cockpit.bib import import_bibtex
from research_cockpit.ingest import ingest_doi, ingest_pdf

DOI = "10.48550/arXiv.1706.03762"


@pytest.mark.parametrize("ref", [
    DOI,
    f"doi:{DOI}",
    f"https://doi.org/{DOI}",
    f"http://doi.org/{DOI}",
    f"See https://doi.org/{DOI}.",
])
def test_normalize_doi_variants(ref):
    assert normalize_doi(ref) == DOI


def test_normalize_doi_rejects_non_doi():
    assert normalize_doi("not-a-doi") is None
    assert normalize_doi("/some/path/paper.pdf") is None


def test_arxiv_id_from_doi():
    from research_cockpit.apis import arxiv_id_from_doi

    assert arxiv_id_from_doi("10.48550/arXiv.1706.03762") == "1706.03762"
    assert arxiv_id_from_doi("10.48550/arxiv.2404.00001v2") == "2404.00001v2"
    assert arxiv_id_from_doi("10.1038/nature") is None
    assert arxiv_id_from_doi(None) is None


class _NullClient:
    """All lookups miss - simulates indexes that don't know the DOI."""

    def work_by_doi(self, doi):
        return None

    def work_by_title(self, title):
        return None

    def work_by_arxiv(self, arxiv_id):
        return None


def test_resolver_falls_back_to_arxiv_pdf_url():
    from research_cockpit.apis import MetadataResolver

    resolver = MetadataResolver(openalex=_NullClient(), s2=_NullClient())
    meta = resolver.resolve(doi=DOI)
    assert meta is not None
    assert meta.pdf_url == "https://arxiv.org/pdf/1706.03762"
    assert meta.doi == DOI

    # non-arXiv DOI that no index knows -> genuinely unresolved
    assert resolver.resolve(doi="10.9999/unknown") is None


def test_resolver_uses_s2_arxiv_lookup():
    from research_cockpit.apis import MetadataResolver

    class ArxivOnlyS2(_NullClient):
        def work_by_arxiv(self, arxiv_id):
            return WorkMeta(title="Attention Is All You Need", year=2017,
                            s2_id="s2abc")

    meta = MetadataResolver(openalex=_NullClient(), s2=ArxivOnlyS2()).resolve(doi=DOI)
    assert meta.title == "Attention Is All You Need"
    assert meta.doi == DOI  # backfilled from the query
    assert meta.pdf_url == "https://arxiv.org/pdf/1706.03762"


def _pdf_bytes(lines: list[str], title: str | None = None) -> bytes:
    doc = fitz.open()
    page = doc.new_page()
    y = 80
    if title:
        page.insert_text((72, y), title, fontsize=20)
        y += 40
    for line in lines:
        page.insert_text((72, y), line, fontsize=10)
        y += 20
    return doc.tobytes()


def test_title_guessed_from_largest_font(tmp_path):
    from research_cockpit.ingest import extract_pdf

    path = tmp_path / "t.pdf"
    path.write_bytes(_pdf_bytes(
        ["Some attribution boilerplate first.", "Body text follows here."],
        title="Attention Is All You Need",
    ))
    _, title = extract_pdf(path)
    assert title == "Attention Is All You Need"


def test_uniform_font_pdf_yields_no_title_guess(tmp_path):
    from research_cockpit.ingest import extract_pdf

    path = tmp_path / "t.pdf"
    path.write_bytes(_pdf_bytes(["line one of text", "line two of text"]))
    _, title = extract_pdf(path)
    assert title is None


class FakeResolver:
    def __init__(self, meta: WorkMeta | None):
        self.meta = meta

    def resolve(self, doi=None, title=None):
        return self.meta


def _meta(pdf_url: str | None) -> WorkMeta:
    return WorkMeta(title="Attention Is All You Need", authors=["Ashish Vaswani"],
                    year=2017, venue="NeurIPS", doi=DOI, openalex_id="W2741809807",
                    pdf_url=pdf_url)


def test_ingest_doi_downloads_and_ingests(store, embedder, tmp_path):
    pdf = _pdf_bytes(["Attention Is All You Need", "We propose the Transformer."])
    fetched_urls = []

    def fetch(url):
        fetched_urls.append(url)
        return pdf

    result = ingest_doi(store, embedder, f"https://doi.org/{DOI}",
                        FakeResolver(_meta("https://arxiv.org/pdf/1706.03762")),
                        pdf_dir=tmp_path / "papers", fetch=fetch)
    assert fetched_urls == ["https://arxiv.org/pdf/1706.03762"]
    assert result.downloaded and result.resolved and result.chunks > 0
    doc = result.document
    assert doc.title == "Attention Is All You Need"
    assert doc.doi == DOI
    assert doc.status == "to-read"
    assert (tmp_path / "papers").glob("*.pdf")
    # saved file is re-ingestable / deduped
    again = ingest_doi(store, embedder, DOI, FakeResolver(_meta("x")),
                       pdf_dir=tmp_path / "papers", fetch=lambda url: pdf)
    assert again.deduped


def test_ingest_doi_no_oa_pdf_creates_metadata_record(store, embedder, tmp_path):
    result = ingest_doi(store, embedder, DOI, FakeResolver(_meta(None)),
                        pdf_dir=tmp_path, fetch=lambda url: None)
    assert result.chunks == 0 and not result.downloaded and result.resolved
    assert result.document.title == "Attention Is All You Need"
    assert result.document.status == "to-read"
    assert store.find_by_doi(DOI) is not None


def test_ingest_doi_unresolvable_still_records(store, embedder, tmp_path):
    result = ingest_doi(store, embedder, "10.9999/unknown.123", FakeResolver(None),
                        pdf_dir=tmp_path)
    assert result.document.doi == "10.9999/unknown.123"
    assert not result.resolved and result.chunks == 0


def test_ingest_doi_rejects_non_doi(store, embedder, tmp_path):
    with pytest.raises(ValueError):
        ingest_doi(store, embedder, "garbage", FakeResolver(None), pdf_dir=tmp_path)


def test_failed_download_falls_back_to_metadata_record(store, embedder, tmp_path):
    result = ingest_doi(store, embedder, DOI, FakeResolver(_meta("https://x/paywalled")),
                        pdf_dir=tmp_path, fetch=lambda url: None)
    assert result.chunks == 0
    assert store.find_by_doi(DOI) is not None


def test_pdf_ingest_merges_into_doi_stub(store, embedder, tmp_path):
    # stub from a DOI add with no OA PDF (same shape as a bib import)
    ingest_doi(store, embedder, DOI, FakeResolver(_meta(None)), pdf_dir=tmp_path)
    stub = store.find_by_doi(DOI)
    assert store.chunk_count(stub.id) == 0

    pdf_path = tmp_path / "paper.pdf"
    pdf_path.write_bytes(_pdf_bytes([f"doi:{DOI}", "The Transformer architecture."]))
    result = ingest_pdf(store, embedder, pdf_path)
    assert result.document.id == stub.id  # merged, not duplicated
    assert result.chunks > 0
    assert len(store.list_documents(collection="papers")) == 1


def test_merge_upgrades_placeholder_title(store, embedder, tmp_path):
    # unresolvable arXiv-style DOI: first add finds no PDF -> stub titled by DOI
    doi = "10.48550/arXiv.9999.00001"
    unresolved = WorkMeta(doi=doi, pdf_url="https://arxiv.org/pdf/9999.00001")
    ingest_doi(store, embedder, doi, FakeResolver(unresolved),
               pdf_dir=tmp_path, fetch=lambda url: None)
    stub = store.find_by_doi(doi)
    assert stub.title == doi  # placeholder

    # retry succeeds: PDF downloads, merges into the stub, title upgraded
    # from the page-1 layout heuristic
    pdf = _pdf_bytes([f"doi:{doi}", "Body text of the paper."],
                     title="A Real Paper Title")
    result = ingest_doi(store, embedder, doi, FakeResolver(unresolved),
                        pdf_dir=tmp_path, fetch=lambda url: pdf)
    assert result.chunks > 0
    assert result.document.id == stub.id
    assert result.document.title == "A Real Paper Title"


def test_backfill_by_title_requires_exact_match(store, embedder, tmp_path):
    doi = "10.48550/arXiv.9999.00002"

    class TitleAwareResolver:
        """DOI lookups miss; title search hits (exact or near-miss)."""

        def __init__(self, result_title):
            self.result_title = result_title

        def resolve(self, doi=None, title=None):
            if title:
                return WorkMeta(title=self.result_title, authors=["Jane Doe"],
                                year=2024, venue="ICML")
            return WorkMeta(doi=doi, pdf_url="https://arxiv.org/pdf/9999.00002")

    pdf = _pdf_bytes(["Body."], title="A Very Specific Title")

    # exact normalized match -> metadata backfilled
    result = ingest_doi(store, embedder, doi, TitleAwareResolver("A Very Specific Title!"),
                        pdf_dir=tmp_path, fetch=lambda url: pdf)
    assert result.document.year == 2024
    assert result.document.authors == ["Jane Doe"]

    # different paper title -> rejected, nothing attached
    store.delete_document(result.document.id)
    result = ingest_doi(store, embedder, doi, TitleAwareResolver("Some Other Paper"),
                        pdf_dir=tmp_path, fetch=lambda url: pdf)
    assert result.document.year is None
    assert result.document.authors == []


def test_bib_import_stub_upgraded_by_later_doi_add(store, embedder, tmp_path):
    import_bibtex(store, f"""@article{{v, title={{Old Title}}, doi={{{DOI}}}, year={{2017}}}}""")
    stub = store.find_by_doi(DOI)
    pdf = _pdf_bytes([f"doi:{DOI}", "content"])
    result = ingest_doi(store, embedder, DOI, FakeResolver(_meta("https://x/a.pdf")),
                        pdf_dir=tmp_path, fetch=lambda url: pdf)
    assert result.document.id == stub.id
    assert result.chunks > 0
    assert len(store.list_documents(collection="papers")) == 1
