"""Saved research questions (M15): persistent question threads per project,
each holding sources, notes, and follow-up gaps.
"""

from __future__ import annotations

from .store import Store, new_id, now_iso

QUESTION_STATUSES = ("open", "answered", "parked")

QUESTIONS_DDL = """
CREATE TABLE IF NOT EXISTS questions (
    id TEXT PRIMARY KEY,
    project_id INTEGER REFERENCES projects (id) ON DELETE SET NULL,
    text TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'open'
        CHECK (status IN ('open', 'answered', 'parked')),
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS question_items (
    id TEXT PRIMARY KEY,
    question_id TEXT NOT NULL REFERENCES questions (id) ON DELETE CASCADE,
    kind TEXT NOT NULL CHECK (kind IN ('source', 'note', 'gap')),
    document_id TEXT REFERENCES documents (id) ON DELETE SET NULL,
    text TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_qitems_question ON question_items (question_id);
"""


def _ensure_tables(store: Store) -> None:
    store.conn.executescript(QUESTIONS_DDL)


def add_question(store: Store, text: str, project_name: str | None = None) -> str:
    _ensure_tables(store)
    pid = None
    if project_name:
        row = store.conn.execute(
            "SELECT id FROM projects WHERE name = ?", (project_name.strip().lower(),)
        ).fetchone()
        pid = row[0] if row else None
    qid = new_id()
    store.conn.execute(
        "INSERT INTO questions (id, project_id, text, status, created_at)"
        " VALUES (?, ?, ?, 'open', ?)",
        (qid, pid, text.strip(), now_iso()),
    )
    store.conn.commit()
    return qid


def list_questions(store: Store, project_name: str | None = None) -> list[dict]:
    _ensure_tables(store)
    if project_name:
        rows = store.conn.execute(
            "SELECT q.* FROM questions q JOIN projects p ON p.id = q.project_id"
            " WHERE p.name = ? ORDER BY q.created_at DESC",
            (project_name.strip().lower(),),
        ).fetchall()
    else:
        rows = store.conn.execute(
            "SELECT * FROM questions ORDER BY created_at DESC"
        ).fetchall()
    return [
        {"id": r["id"], "text": r["text"], "status": r["status"],
         "created_at": r["created_at"]}
        for r in rows
    ]


def get_question(store: Store, question_id: str) -> dict | None:
    _ensure_tables(store)
    row = store.conn.execute("SELECT * FROM questions WHERE id = ?", (question_id,)).fetchone()
    if row is None:
        return None
    items = store.conn.execute(
        "SELECT * FROM question_items WHERE question_id = ? ORDER BY created_at",
        (question_id,),
    ).fetchall()
    return {
        "id": row["id"], "text": row["text"], "status": row["status"],
        "items": [
            {"id": i["id"], "kind": i["kind"], "document_id": i["document_id"],
             "text": i["text"]}
            for i in items
        ],
    }


def add_item(
    store: Store, question_id: str, kind: str, text: str,
    document_id: str | None = None,
) -> str:
    _ensure_tables(store)
    if kind not in ("source", "note", "gap"):
        raise ValueError(f"kind must be source/note/gap, got '{kind}'")
    iid = new_id()
    store.conn.execute(
        "INSERT INTO question_items (id, question_id, kind, document_id, text, created_at)"
        " VALUES (?, ?, ?, ?, ?, ?)",
        (iid, question_id, kind, document_id, text.strip(), now_iso()),
    )
    store.conn.commit()
    return iid


def close_question(store: Store, question_id: str, status: str = "answered") -> None:
    _ensure_tables(store)
    if status not in QUESTION_STATUSES:
        raise ValueError(f"status must be one of {QUESTION_STATUSES}")
    store.conn.execute("UPDATE questions SET status = ? WHERE id = ?", (status, question_id))
    store.conn.commit()
