from __future__ import annotations

from datetime import date, timedelta

import pytest

from conftest import FakeAdapter, make_paper
from research_cockpit import kb
from research_cockpit.store import Document, new_id


def test_set_status_valid_and_invalid(store):
    doc = make_paper(store, "P")
    kb.set_status(store, doc, "reading")
    assert store.get_document(doc.id).status == "reading"
    with pytest.raises(ValueError):
        kb.set_status(store, doc, "done")


def test_set_status_rejects_notes(store):
    note = store.add_document(Document(id=new_id(), collection="notes", title="n"))
    with pytest.raises(ValueError):
        kb.set_status(store, note, "reading")


def test_sm2_progression():
    state = kb.ReviewState()
    state = kb.sm2_update(state, 5)
    assert (state.reps, state.interval_days) == (1, 1.0)
    state = kb.sm2_update(state, 5)
    assert (state.reps, state.interval_days) == (2, 6.0)
    state = kb.sm2_update(state, 4)
    assert state.reps == 3 and state.interval_days > 6


def test_sm2_failure_resets():
    state = kb.ReviewState(ease=2.5, interval_days=30, reps=5)
    state = kb.sm2_update(state, 1)
    assert (state.reps, state.interval_days) == (0, 1.0)


def test_sm2_ease_floor():
    state = kb.ReviewState(ease=1.3)
    for _ in range(5):
        state = kb.sm2_update(state, 0)
    assert state.ease == pytest.approx(1.3)


def test_schedule_and_due(store):
    doc = make_paper(store, "P", status="annotated")
    today = date(2026, 7, 10)
    kb.schedule_new(store, doc.id, on=today)
    assert [d.id for d in store.due_documents(on=today)] == [doc.id]
    next_due = kb.record_review(store, doc.id, 5, on=today)
    assert next_due == today + timedelta(days=1)
    assert store.due_documents(on=today) == []
    assert [d.id for d in store.due_documents(on=next_due)] == [doc.id]


def test_flashcards_generated_from_annotations_and_cached(store):
    doc = make_paper(store, "P", status="annotated")
    store.add_annotation(doc.id, "The key result is a 2x speedup from caching.")
    adapter = FakeAdapter(
        '[{"question": "What speedup?", "answer": "2x from caching"}]'
    )
    cards = kb.ensure_flashcards(store, adapter, doc)
    assert len(cards) == 1
    assert cards[0]["question"] == "What speedup?"
    # cached: second call does not hit the adapter
    kb.ensure_flashcards(store, adapter, doc)
    assert len(adapter.calls) == 1
    # new annotation invalidates the cache
    store.add_annotation(doc.id, "Second insight.")
    kb.ensure_flashcards(store, adapter, doc)
    assert len(adapter.calls) == 2


def test_flashcards_tolerate_malformed_llm_output(store):
    doc = make_paper(store, "P")
    store.add_annotation(doc.id, "something")
    cards = kb.ensure_flashcards(store, FakeAdapter("Sorry, I can't do JSON today."), doc)
    assert cards == []
