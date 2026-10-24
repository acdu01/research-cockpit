"""Exercise the advertised claim-prefix workflow through the CLI."""

from __future__ import annotations

import pytest
from typer.testing import CliRunner

from conftest import make_paper
from research_cockpit.claims import add_claim, get_claim
from research_cockpit.cli import app
from research_cockpit.store import Store


@pytest.mark.parametrize("ref", ["missing.pdf", "10.1234/example", "."])
def test_invalid_add_fails_without_loading_a_model(tmp_path, monkeypatch, ref):
    from research_cockpit import cli

    monkeypatch.setenv("RC_HOME", str(tmp_path))

    def unexpected_model_load(cfg):
        pytest.fail("Invalid inputs should not trigger model downloads")

    monkeypatch.setattr(cli, "_embedder", unexpected_model_load)
    result = CliRunner().invoke(app, ["add", "--no-resolve", ref])
    assert result.exit_code == 1
    assert "Not a file or DOI" in result.output or "Cannot ingest DOI" in result.output


def test_add_reports_local_pdf_without_text(tmp_path, monkeypatch):
    import fitz

    monkeypatch.setenv("RC_HOME", str(tmp_path))
    runner = CliRunner()
    assert runner.invoke(app, ["config", "set", "embeddings.model", "hash"]).exit_code == 0
    path = tmp_path / "scanned.pdf"
    with fitz.open() as pdf:
        pdf.new_page().draw_rect(fitz.Rect(50, 50, 100, 100))
        pdf.save(path)
    result = runner.invoke(app, ["add", "--no-resolve", str(path)])
    assert result.exit_code == 0, result.output
    assert "No searchable text found" in result.output and "OCR" in result.output
    assert "No open-access PDF" not in result.output


def test_add_keeps_valid_files_when_another_input_is_invalid(tmp_path, monkeypatch):
    import fitz

    monkeypatch.setenv("RC_HOME", str(tmp_path))
    runner = CliRunner()
    runner.invoke(app, ["config", "set", "embeddings.model", "hash"])
    path = tmp_path / "paper.pdf"
    with fitz.open() as pdf:
        pdf.new_page().insert_text((72, 72), "Evidence remains searchable.")
        pdf.save(path)
    result = runner.invoke(app, ["add", "--no-resolve", "missing.pdf", str(path)])
    assert result.exit_code == 1 and "Added" in result.output
    result = runner.invoke(app, ["search", "searchable"])
    assert result.exit_code == 0 and "Evidence remains searchable" in result.output


def test_claim_commands_resolve_prefixes(tmp_path, monkeypatch):
    monkeypatch.setenv("RC_HOME", str(tmp_path))
    store = Store(tmp_path / "rc.db")
    try:
        store.create_project("thesis")
        cid = add_claim(store, "thesis", "Claim A")
        add_claim(store, "thesis", "Claim B")
        doc = make_paper(store, "Evidence paper")
        runner = CliRunner()
        attached = runner.invoke(app, ["claim", "attach", cid[:8], doc.id[:8], "A quote"])
        assert attached.exit_code == 0, attached.output
        assert get_claim(store, cid)["evidence"][0]["quote"] == "A quote"
        moved = runner.invoke(app, ["claim", "move", cid[:8], "1"])
        assert moved.exit_code == 0, moved.output
        assert get_claim(store, cid)["ordinal"] == 1
        shown = runner.invoke(app, ["claim", "show", cid[:8]])
        assert shown.exit_code == 0 and "Claim A" in shown.output
        missing = runner.invoke(app, ["claim", "attach", "missing", doc.id[:8], "A quote"])
        assert missing.exit_code == 1 and "No unique claim" in missing.output
    finally:
        store.close()
