"""Streamlit AppTest smoke tests: every page renders; core flows work.

Uses RC_HOME to point the app at a seeded throwaway library with the hash
embedder and the local LLM backend - no downloads, no subprocesses.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

pytest.importorskip("streamlit")
from streamlit.testing.v1 import AppTest  # noqa: E402

APP_PATH = str(Path(__file__).resolve().parents[1] / "src/research_cockpit/ui/app.py")
PAGES = ["Ask", "Library", "Reader", "Review", "Graph", "Citations",
         "Constellation", "Claims", "Questions"]


@pytest.fixture(scope="module")
def rc_home(tmp_path_factory):
    import fitz

    from research_cockpit.config import Config
    from research_cockpit.embed import get_embedder
    from research_cockpit.ingest import ingest_pdf
    from research_cockpit.store import Store

    home = tmp_path_factory.mktemp("rc-home")
    previous = os.environ.get("RC_HOME")
    os.environ["RC_HOME"] = str(home)
    (home / "config.toml").write_text(
        '[llm]\nbackend = "local"\n\n[embeddings]\nmodel = "hash"\n'
    )
    pdf_dir = home / "papers"
    pdf_dir.mkdir()
    pdf_path = pdf_dir / "sample.pdf"
    doc = fitz.open()
    doc.new_page().insert_text((72, 90), "Stable humidity preserves parchment folios.")
    doc.new_page().insert_text((72, 90), "Cold storage protects manuscripts.")
    doc.save(pdf_path)
    cfg = Config.load(home / "config.toml")
    store = Store(cfg.store_path)
    ingest_pdf(store, get_embedder("hash"), pdf_path)
    store.close()
    yield home
    if previous is None:
        os.environ.pop("RC_HOME", None)
    else:
        os.environ["RC_HOME"] = previous


def _open(page: str) -> AppTest:
    at = AppTest.from_file(APP_PATH, default_timeout=60)
    at.run()
    if page != "Ask":
        at.sidebar.radio[0].set_value(page).run()
    return at


@pytest.mark.parametrize("page", PAGES)
def test_page_renders_without_exception(rc_home, page):
    at = _open(page)
    assert not at.exception


def test_ask_answers_with_local_backend(rc_home):
    at = _open("Ask")
    at.text_area[0].set_value("what preserves parchment?").run()
    ask = [b for b in at.button if b.label == "Ask"][0]
    ask.click().run()
    assert not at.exception
    body = " ".join(md.value for md in at.markdown)
    assert "Based on the retrieved passages" in body
    # Editing a question reruns Streamlit; the previous answer stays readable.
    at.text_area[0].set_value("a follow-up question").run()
    assert not at.exception
    assert "Based on the retrieved passages" in " ".join(md.value for md in at.markdown)
    assert "what preserves parchment?" in " ".join(c.value for c in at.caption)


def test_reader_search_lists_matching_pages(rc_home):
    at = _open("Reader")
    search = [t for t in at.text_input if (t.key or "").startswith("reader-q-")][0]
    search.set_value("manuscripts").run()
    assert not at.exception
    jump_labels = [b.label for b in at.button if b.label.startswith("p. ")]
    assert "p. 2" in jump_labels  # the term is on page 2 only
    assert "p. 1" not in jump_labels


def test_sidebar_shows_library_stats(rc_home):
    at = _open("Ask")
    sidebar_text = " ".join(md.value for md in at.sidebar.markdown)
    assert "1 paper ·" in sidebar_text
