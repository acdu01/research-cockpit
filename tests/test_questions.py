"""M15: saved research questions - CRUD + item filing."""

from __future__ import annotations

import pytest

from conftest import make_paper
from research_cockpit.questions import (
    add_item,
    add_question,
    close_question,
    get_question,
    list_questions,
)


def test_question_lifecycle(store):
    store.create_project("thesis")
    qid = add_question(store, "What halts cockling?", project_name="thesis")
    questions = list_questions(store, project_name="thesis")
    assert len(questions) == 1 and questions[0]["status"] == "open"
    add_item(store, qid, "source", "p.3: humidity below 45%")
    add_item(store, qid, "note", "Check Bodleian folios for confirmation.")
    add_item(store, qid, "gap", "No studies on Asian mulberry papers.")
    q = get_question(store, qid)
    assert len(q["items"]) == 3
    assert q["items"][0]["kind"] == "source"
    assert q["items"][2]["kind"] == "gap"
    close_question(store, qid, "answered")
    assert list_questions(store)[0]["status"] == "answered"


def test_question_without_project(store):
    qid = add_question(store, "General question")
    assert list_questions(store)[0]["text"] == "General question"
    assert get_question(store, qid)["text"] == "General question"


def test_item_kind_validated(store):
    qid = add_question(store, "Q")
    with pytest.raises(ValueError, match="kind"):
        add_item(store, qid, "answer", "text")


def test_item_with_document(store):
    doc = make_paper(store, "P", doi="10.1/p")
    qid = add_question(store, "Q")
    add_item(store, qid, "source", "Passage from P", document_id=doc.id)
    items = get_question(store, qid)["items"]
    assert items[0]["document_id"] == doc.id
