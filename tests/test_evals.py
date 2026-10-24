"""M18: RAG evaluation harness - gold set + scoring."""

from __future__ import annotations

from conftest import make_paper
from research_cockpit.evals import add_gold, history, list_gold, run_eval
from research_cockpit.store import Chunk, new_id


def test_gold_crud(store):
    add_gold(store, "What halts cockling?", ["doc1"], expected_answer="Humidity.")
    items = list_gold(store)
    assert len(items) == 1
    assert items[0]["question"] == "What halts cockling?"


def test_eval_run(store, embedder):
    doc = make_paper(store, "Parchment Paper")
    chunk = Chunk(id=new_id(), document_id=doc.id, ordinal=0, page=1,
                  text="Humidity halts cockling.", token_count=4)
    store.add_chunks([chunk], embedder.encode([chunk.text]))
    add_gold(store, "humidity cockling", [doc.id])
    result = run_eval(store, embedder, k=5)
    assert result["retrieval_recall"] == 1.0
    assert result["citation_accuracy"] is None
    assert result["faithfulness"] is None
    assert result["run_id"]
    runs = history(store)
    assert len(runs) == 1 and runs[0]["retrieval_recall"] == 1.0
    assert runs[0]["citation_accuracy"] is None
    assert runs[0]["faithfulness"] is None
    row = store.conn.execute("SELECT * FROM eval_runs").fetchone()
    assert row["citation_accuracy"] is None and row["faithfulness"] is None


def test_empty_eval_is_unmeasured(store, embedder):
    result = run_eval(store, embedder)
    assert result == {"retrieval_recall": None, "citation_accuracy": None,
                      "faithfulness": None, "per_item": []}
    assert history(store) == []


def test_eval_with_miss(store, embedder):
    doc = make_paper(store, "P")
    chunk = Chunk(id=new_id(), document_id=doc.id, ordinal=0, page=1,
                  text="Totally unrelated content.", token_count=3)
    store.add_chunks([chunk], embedder.encode([chunk.text]))
    add_gold(store, "quantum computing", ["nonexistent_id"])
    result = run_eval(store, embedder, k=5)
    assert result["retrieval_recall"] == 0.0
