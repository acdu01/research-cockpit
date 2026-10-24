"""Retrieval evaluation over a gold Q/A set with config snapshots.

Citation accuracy and faithfulness are unmeasured (None): this harness does
not generate or judge answers.
"""

from __future__ import annotations

import json

from .embed import Embedder
from .rag import search
from .store import Store, new_id, now_iso

EVALS_DDL = """
CREATE TABLE IF NOT EXISTS gold_qa (
    id TEXT PRIMARY KEY,
    question TEXT NOT NULL,
    expected_doc_ids TEXT NOT NULL DEFAULT '[]',
    expected_answer TEXT,
    notes TEXT,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS eval_runs (
    id TEXT PRIMARY KEY,
    ran_at TEXT NOT NULL,
    config_snapshot TEXT NOT NULL DEFAULT '{}',
    retrieval_recall REAL,
    citation_accuracy REAL,
    faithfulness REAL,
    per_item TEXT NOT NULL DEFAULT '[]',
    notes TEXT
);
"""


def _ensure_tables(store: Store) -> None:
    store.conn.executescript(EVALS_DDL)


def add_gold(store: Store, question: str, expected_doc_ids: list[str],
             expected_answer: str | None = None, notes: str | None = None) -> str:
    _ensure_tables(store)
    gid = new_id()
    store.conn.execute(
        "INSERT INTO gold_qa (id, question, expected_doc_ids, expected_answer, notes, created_at)"
        " VALUES (?, ?, ?, ?, ?, ?)",
        (gid, question.strip(), json.dumps(expected_doc_ids), expected_answer, notes, now_iso()),
    )
    store.conn.commit()
    return gid


def list_gold(store: Store) -> list[dict]:
    _ensure_tables(store)
    rows = store.conn.execute("SELECT * FROM gold_qa ORDER BY created_at").fetchall()
    return [{"id": r["id"], "question": r["question"],
             "expected_doc_ids": json.loads(r["expected_doc_ids"]),
             "expected_answer": r["expected_answer"]} for r in rows]


def run_eval(store: Store, embedder: Embedder, config: dict | None = None,
             retrieval: str = "dense", k: int = 8) -> dict:
    """Measure retrieval recall; leave answer-quality metrics explicitly unmeasured."""
    _ensure_tables(store)
    items = list_gold(store)
    if not items:
        return {"retrieval_recall": None, "citation_accuracy": None,
                "faithfulness": None, "per_item": []}
    per_item = []
    total_recall = 0.0
    for item in items:
        expected = set(item["expected_doc_ids"])
        hits = search(store, embedder, item["question"], k=k, retrieval=retrieval)
        retrieved_ids = {doc.id for _, doc, _ in hits}
        recall = len(expected & retrieved_ids) / len(expected) if expected else 1.0
        total_recall += recall
        per_item.append({"question": item["question"], "recall": recall})
    n = len(items)
    result = {
        "retrieval_recall": total_recall / n,
        "citation_accuracy": None,
        "faithfulness": None,
        "per_item": per_item,
    }
    # persist
    run_id = new_id()
    store.conn.execute(
        "INSERT INTO eval_runs (id, ran_at, config_snapshot, retrieval_recall,"
        " citation_accuracy, per_item) VALUES (?, ?, ?, ?, ?, ?)",
        (run_id, now_iso(), json.dumps(config or {}), result["retrieval_recall"],
         result["citation_accuracy"], json.dumps(per_item)),
    )
    store.conn.commit()
    result["run_id"] = run_id
    return result


def history(store: Store) -> list[dict]:
    _ensure_tables(store)
    rows = store.conn.execute("SELECT * FROM eval_runs ORDER BY ran_at").fetchall()
    return [{"id": r["id"], "ran_at": r["ran_at"],
             "retrieval_recall": r["retrieval_recall"],
             "citation_accuracy": r["citation_accuracy"],
             "faithfulness": r["faithfulness"]} for r in rows]
