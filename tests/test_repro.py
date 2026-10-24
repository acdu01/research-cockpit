"""M17: reproducibility tracking."""

from __future__ import annotations

import pytest

from conftest import make_paper
from research_cockpit.repro import get_repro, set_repro


def test_repro_crud(store):
    doc = make_paper(store, "P")
    assert get_repro(store, doc.id) is None
    set_repro(store, doc.id, code_availability="linked", code_url="https://gh.example/repo")
    r = get_repro(store, doc.id)
    assert r["code_availability"] == "linked"
    assert r["code_url"] == "https://gh.example/repo"
    assert r["replicated"] == "none"
    set_repro(store, doc.id, replicated="replicated", notes="Results matched.")
    r = get_repro(store, doc.id)
    assert r["replicated"] == "replicated" and r["notes"] == "Results matched."


def test_repro_validation(store):
    doc = make_paper(store, "P")
    with pytest.raises(ValueError, match="code_availability"):
        set_repro(store, doc.id, code_availability="maybe")
    with pytest.raises(ValueError, match="replicated"):
        set_repro(store, doc.id, replicated="sort-of")
