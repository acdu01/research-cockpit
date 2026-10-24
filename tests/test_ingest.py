from __future__ import annotations

from pathlib import Path

import pytest

from research_cockpit.ingest import PageText, chunk_pages, find_doi, ingest_note


def test_find_doi():
    text = "Published as doi:10.1038/s41586-021-03819-2. See also fig 3."
    assert find_doi(text) == "10.1038/s41586-021-03819-2"
    assert find_doi("no identifiers here") is None


def test_find_doi_strips_trailing_punctuation():
    assert find_doi("(https://doi.org/10.1145/3292500.3330701).") == \
        "10.1145/3292500.3330701"


def test_chunk_pages_sizes_and_overlap():
    words = " ".join(f"w{i}" for i in range(1200))
    chunks = chunk_pages([PageText(page=1, text=words)], target_tokens=512, overlap=64)
    assert len(chunks) == 3
    assert chunks[0][2] == 512
    # overlap: last 64 words of chunk 1 == first 64 words of chunk 2
    first_words = chunks[0][0].split()
    second_words = chunks[1][0].split()
    assert first_words[-64:] == second_words[:64]


def test_chunk_pages_preserves_start_page():
    pages = [PageText(page=1, text="a " * 400), PageText(page=2, text="b " * 400)]
    chunks = chunk_pages(pages, target_tokens=512, overlap=64)
    assert chunks[0][1] == 1
    assert chunks[-1][1] == 2


def test_chunk_pages_empty():
    assert chunk_pages([]) == []
    assert chunk_pages([PageText(page=1, text="   ")]) == []


def test_ingest_note_and_dedupe(store, embedder):
    text = "Reading group thoughts on retrieval augmented generation and evaluation."
    result = ingest_note(store, embedder, text, "rag-notes", tags=["rag"])
    assert result.document.collection == "notes"
    assert result.document.status is None
    assert result.chunks >= 1
    assert store.document_tags(result.document.id) == ["rag"]

    again = ingest_note(store, embedder, text, "rag-notes")
    assert again.deduped
    assert again.document.id == result.document.id


def test_note_chunks_have_no_page(store, embedder):
    result = ingest_note(store, embedder, "hello world " * 100, "note")
    for chunk in store.document_chunks(result.document.id):
        assert chunk.page is None


def test_failed_embedding_can_be_retried(store, embedder, monkeypatch):
    with monkeypatch.context() as patch:
        patch.setattr(embedder, "encode", lambda texts: (_ for _ in ()).throw(
            RuntimeError("Model unavailable")
        ))
        with pytest.raises(RuntimeError, match="Model unavailable"):
            ingest_note(store, embedder, "A retryable note", "Retry", tags=["test"])
    assert store.list_documents() == []
    result = ingest_note(store, embedder, "A retryable note", "Retry")
    assert result.chunks > 0 and not result.deduped


def test_invalid_embeddings_roll_back_document_and_tags(store, embedder, monkeypatch):
    import numpy as np

    monkeypatch.setattr(embedder, "encode", lambda texts: np.empty((0, embedder.dim)))
    with pytest.raises(ValueError, match="one embedding"):
        ingest_note(store, embedder, "Atomic note", "Note", tags=["atomic"])
    assert store.list_documents() == []
    assert store.all_tags() == []


@pytest.mark.parametrize("target, overlap", [(0, 0), (-1, 0), (10, -1), (10, 10)])
def test_invalid_chunk_settings_raise(target, overlap):
    with pytest.raises(ValueError):
        chunk_pages([PageText(1, "some text")], target, overlap)


def test_upload_is_durable_and_preserves_original_filename(store, embedder, tmp_path):
    import fitz

    from research_cockpit.ingest import ingest_uploaded_pdf, pdf_page_count

    with fitz.open() as pdf:
        pdf.new_page().insert_text((72, 72), "A searchable uploaded paper.")
        data = pdf.tobytes()
    pdf_dir = tmp_path / "papers"
    result = ingest_uploaded_pdf(store, embedder, data, "../original_title.pdf", pdf_dir)
    stored = Path(result.document.source_path)
    assert stored.is_relative_to(pdf_dir)
    assert stored.name == "original_title.pdf"
    assert result.document.title == "original title"
    assert pdf_page_count(stored) == 1
    assert ingest_uploaded_pdf(
        store, embedder, data, "original_title.pdf", pdf_dir
    ).deduped
    # Reuploading a legacy record with a lost temporary PDF repairs its Reader path.
    store.update_document(result.document.id, source_path=str(tmp_path / "missing.pdf"))
    repaired = ingest_uploaded_pdf(store, embedder, data, "original_title.pdf", pdf_dir)
    assert repaired.deduped and Path(repaired.document.source_path).is_file()


def test_upload_rejects_invalid_pdf(store, embedder, tmp_path):
    import fitz

    from research_cockpit.ingest import ingest_uploaded_pdf

    with pytest.raises(fitz.FileDataError):
        ingest_uploaded_pdf(store, embedder, b"not a PDF", "paper.pdf", tmp_path / "papers")
    assert store.list_documents() == []
    assert not (tmp_path / "papers").exists()
