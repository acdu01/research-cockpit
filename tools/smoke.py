"""Offline installed-package smoke check: python tools/smoke.py.

Uses the current interpreter in a temporary working directory with a separate
RC_HOME. No model downloads, metadata requests, or changes to your library.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

import fitz


def main() -> None:
    with TemporaryDirectory(prefix="research-cockpit-smoke-") as directory:
        root = Path(directory)
        env = {**os.environ, "RC_HOME": str(root / "home"), "NO_COLOR": "1"}
        env.pop("PYTHONPATH", None)

        def rc(*args: str, contains: str | None = None) -> str:
            result = subprocess.run(
                [sys.executable, "-m", "research_cockpit.cli", *args],
                cwd=root, env=env, capture_output=True, text=True, timeout=60,
            )
            if result.returncode:
                raise RuntimeError(f"rc {args}:\n{result.stdout}\n{result.stderr}")
            if contains and contains not in result.stdout:
                raise AssertionError(f"Expected {contains!r} from rc {args}:\n{result.stdout}")
            return result.stdout

        rc("--help", contains="Research Cockpit")
        rc("config", "set", "embeddings.model", "hash")
        rc("config", "set", "llm.backend", "local")
        paper = root / "paper.pdf"
        with fitz.open() as pdf:
            pdf.set_metadata({"title": "Parchment preservation"})
            pdf.new_page().insert_text((72, 90), "Stable humidity preserves parchment folios.")
            pdf.new_page().insert_text((72, 90), "Cold storage protects manuscripts.")
            pdf.save(paper)
        rc("add", "--no-resolve", str(paper), contains="Added")
        rc("add", "--no-resolve", str(paper), contains="Already in library")
        note = root / "ideas.md"
        note.write_text("Compare humidity control for parchment preservation.", encoding="utf-8")
        rc("add-note", str(note), "--tag", "preservation", contains="Added note")
        rc("search", "humidity", contains="Stable humidity")
        rc("config", "set", "rag.retrieval", "hybrid")
        rc("search", "humidity?", contains="Stable humidity")
        rc("ask", "What preserves parchment?", contains="Sources")
        rc("ask", "Compare preservation methods", "--synthesize", contains="Sources")
        rc("search", "humidity", "--scope", "notes", contains="Compare humidity")
        title = "Parchment preservation"
        rc("kb", "status", title, "reading")
        rc("kb", "annotate", title, "Humidity matters.", "--page", "1")
        rc("kb", "show", title, contains="Humidity matters")
        rc("project", "add", "thesis")
        rc("project", "assign", title, "thesis")
        rc("search", "humidity", "--project", "thesis", contains="Stable humidity")
        rc("claim", "add", "thesis", "Humidity preserves parchment.")
        rc("claim", "list", "thesis", contains="Humidity preserves parchment")
        rc("bib", "export", "-o", str(root / "refs.bib"))
        assert "Parchment preservation" in (root / "refs.bib").read_text()
        for style in ("apa", "mla", "chicago", "bibtex"):
            rc("bib", "cite", "--style", style, contains="Parchment preservation")
        for extension in ("graphml", "dot", "json"):
            path = root / f"graph.{extension}"
            rc("graph", "export", "-o", str(path))
            assert path.stat().st_size > 0
        assert json.loads((root / "graph.json").read_text())["nodes"]
        rc("review", contains="Nothing due")
        print("PASS: installed CLI, PDF/note ingest, dedupe, dense/hybrid retrieval,")
        print("cited answers, lifecycle, annotations, projects, claims, citations, graph exports.")


if __name__ == "__main__":
    main()
