"""Regression: a failing LLM backend must never paint a traceback into the UI.

Config points at the api backend with no key and NO fallback, so every
generation raises LLMError - the buttons must surface a flash message instead.
"""

from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("streamlit")
import streamlit as st  # noqa: E402
from streamlit.testing.v1 import AppTest  # noqa: E402

APP_PATH = str(Path(__file__).resolve().parents[1] / "src/research_cockpit/ui/app.py")


@pytest.fixture()
def broken_llm_home(tmp_path, monkeypatch):
    import fitz

    from research_cockpit.config import Config
    from research_cockpit.embed import get_embedder
    from research_cockpit.ingest import ingest_pdf
    from research_cockpit.store import Store

    monkeypatch.setenv("RC_HOME", str(tmp_path))
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    (tmp_path / "config.toml").write_text(
        '[llm]\nbackend = "api"\nfallback_backend = ""\n\n'
        '[embeddings]\nmodel = "hash"\n'
    )
    pdf = tmp_path / "p.pdf"
    doc = fitz.open()
    doc.new_page().insert_text((72, 90), "Stable humidity halts cockling of folios.")
    doc.save(pdf)
    cfg = Config.load(tmp_path / "config.toml")
    store = Store(cfg.store_path)
    ingest_pdf(store, get_embedder("hash"), pdf)
    store.close()
    # the app caches Config/adapter per process - drop anything cached by
    # other UI tests so this RC_HOME takes effect (and again on teardown)
    st.cache_resource.clear()
    st.cache_data.clear()
    yield tmp_path
    st.cache_resource.clear()
    st.cache_data.clear()


def test_ai_annotation_failure_shows_message_not_traceback(broken_llm_home):
    at = AppTest.from_file(APP_PATH, default_timeout=60)
    at.run()
    at.sidebar.radio[0].set_value("Library").run()
    [b for b in at.button if "AI annotations" in b.label][0].click()
    at.run()
    assert not at.exception  # the 150-line red traceback regression
    warnings = " ".join(str(w.value) for w in at.warning)
    assert "LLM_API_KEY" in warnings  # the actual cause, said plainly


def test_ask_failure_shows_error_not_traceback(broken_llm_home):
    at = AppTest.from_file(APP_PATH, default_timeout=60)
    at.run()
    at.text_area[0].set_value("what halts cockling?").run()
    [b for b in at.button if b.label == "Ask"][0].click()
    at.run()
    assert not at.exception
    errors = " ".join(str(e.value) for e in at.error)
    assert "LLM_API_KEY" in errors
