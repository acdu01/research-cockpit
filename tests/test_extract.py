"""M9: structured paper extraction - schema, extraction, correction, re-run."""

from __future__ import annotations

import json

import pytest

from conftest import FakeAdapter, make_paper
from research_cockpit.extract import (
    EXTRACTION_FIELDS,
    extract_paper,
    extraction_status,
    get_extraction,
    set_extraction_field,
)
from research_cockpit.llm import LLMError
from research_cockpit.store import Chunk, new_id


def test_json_object_parser_ignores_braces_inside_strings():
    from research_cockpit.extract import _parse_obj

    assert _parse_obj('```json\n{"task": "a } brace { in a quote"}\n```') == {
        "task": "a } brace { in a quote"
    }

GOOD_RESPONSE = json.dumps({
    "task": "Measure humidity impact on parchment cockling.",
    "method": "Controlled chamber experiments at 30-80% RH.",
    "datasets": ["Bodleian 12th-century folios", "Vatopedi fragments"],
    "metrics": [
        {"name": "cockling grade", "value": "2.1", "dataset": "Bodleian"},
        {"name": "fibre tension (N)", "value": "0.43", "dataset": None},
    ],
    "findings": [
        "Humidity below 45% halts cockling for collagen-based supports.",
        "Rate depends nonlinearly on fibre moisture content.",
    ],
    "limitations": ["Only tested European parchments (no Asian mulberry)."],
})


def _seeded(store, embedder):
    doc = make_paper(store, "Humidity and the Cockling of Parchment Folios", year=2019)
    chunk = Chunk(id=new_id(), document_id=doc.id, ordinal=0, page=1,
                  text="Stable humidity halts cockling of folios.", token_count=7)
    store.add_chunks([chunk], embedder.encode([chunk.text]))
    return doc


def test_extraction_full_roundtrip(store, embedder):
    doc = _seeded(store, embedder)
    adapter = FakeAdapter(GOOD_RESPONSE)
    result = extract_paper(store, adapter, doc)
    assert result["task"] == "Measure humidity impact on parchment cockling."
    assert result["method"].startswith("Controlled chamber")
    assert result["datasets"] == ["Bodleian 12th-century folios", "Vatopedi fragments"]
    assert len(result["metrics"]) == 2
    assert result["metrics"][0] == {"name": "cockling grade", "value": "2.1", "dataset": "Bodleian"}
    assert result["findings"][0].startswith("Humidity below 45%")
    assert result["limitations"] == ["Only tested European parchments (no Asian mulberry)."]
    sources = json.loads(result["field_sources"])
    assert all(sources[f] == "llm" for f in EXTRACTION_FIELDS)


def test_extraction_validates_metrics_shape(store, embedder):
    doc = _seeded(store, embedder)
    resp = json.dumps({
        "task": "T", "method": "M", "datasets": [],
        "metrics": ["BLEU 34.2", {"name": "ROUGE", "value": "0.5"}],
        "findings": [], "limitations": [],
    })
    adapter = FakeAdapter(resp)
    result = extract_paper(store, adapter, doc)
    assert result["metrics"] == [
        {"name": "BLEU 34.2", "value": None, "dataset": None},
        {"name": "ROUGE", "value": "0.5", "dataset": None},
    ]


def test_extraction_raises_on_prose(store, embedder):
    doc = _seeded(store, embedder)
    prose = "I'd be happy to analyze this paper! The main task is..."
    with pytest.raises(LLMError, match="no parseable JSON"):
        extract_paper(store, FakeAdapter(prose), doc)


def test_extraction_raises_on_no_chunks(store):
    doc = make_paper(store, "Empty Paper")
    with pytest.raises(LLMError, match="No chunks"):
        extract_paper(store, FakeAdapter(GOOD_RESPONSE), doc)


def test_human_correction_survives_rerun(store, embedder):
    doc = _seeded(store, embedder)
    extract_paper(store, FakeAdapter(GOOD_RESPONSE), doc)
    set_extraction_field(store, doc.id, "limitations",
                         '["My hand-written limitation."]')
    ext = get_extraction(store, doc.id)
    assert ext["limitations"] == ["My hand-written limitation."]
    assert json.loads(ext["field_sources"])["limitations"] == "human"
    # re-run: the human field survives, others get updated
    new_response = json.dumps({
        "task": "Updated task.", "method": "Updated method.",
        "datasets": [], "metrics": [], "findings": ["New finding."],
        "limitations": ["LLM's version (should NOT win)."],
    })
    extract_paper(store, FakeAdapter(new_response), doc)
    ext = get_extraction(store, doc.id)
    assert ext["task"] == "Updated task."
    assert ext["limitations"] == ["My hand-written limitation."]  # survived!


def test_force_overwrites_human(store, embedder):
    doc = _seeded(store, embedder)
    extract_paper(store, FakeAdapter(GOOD_RESPONSE), doc)
    set_extraction_field(store, doc.id, "task", "My task.")
    new = json.dumps({**json.loads(GOOD_RESPONSE), "task": "LLM task."})
    extract_paper(store, FakeAdapter(new), doc, force=True)
    assert get_extraction(store, doc.id)["task"] == "LLM task."


def test_set_field_validates(store, embedder):
    doc = _seeded(store, embedder)
    extract_paper(store, FakeAdapter(GOOD_RESPONSE), doc)
    with pytest.raises(ValueError, match="field must be"):
        set_extraction_field(store, doc.id, "abstract", "x")
    with pytest.raises(ValueError, match="must be a JSON array"):
        set_extraction_field(store, doc.id, "datasets", '"not an array"')


def test_extraction_status(store, embedder):
    doc = _seeded(store, embedder)
    make_paper(store, "No chunks")
    statuses_initial = extraction_status(store)
    assert statuses_initial[0] == (doc, "missing")
    assert statuses_initial[1][1] == "missing"
    extract_paper(store, FakeAdapter(GOOD_RESPONSE), doc)
    statuses = {d.id: s for d, s in extraction_status(store)}
    assert statuses[doc.id] == "extracted"
