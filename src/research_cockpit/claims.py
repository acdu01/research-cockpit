"""Claim-to-evidence workspace (M10): projects hold claims (outline sections/
statements); each claim holds cited passages pinned to exact sources.

This is the core "support research decisions" feature: transform retrieval
results into durable, reorderable arguments backed by verbatim evidence.
"""

from __future__ import annotations

from .store import Store, new_id, now_iso

STANCES = ("supports", "contradicts", "context")

CLAIMS_DDL = """
CREATE TABLE IF NOT EXISTS claims (
    id TEXT PRIMARY KEY,
    project_id INTEGER NOT NULL REFERENCES projects (id) ON DELETE CASCADE,
    text TEXT NOT NULL,
    ordinal INTEGER NOT NULL DEFAULT 0,
    notes TEXT,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_claims_project ON claims (project_id);

CREATE TABLE IF NOT EXISTS claim_evidence (
    id TEXT PRIMARY KEY,
    claim_id TEXT NOT NULL REFERENCES claims (id) ON DELETE CASCADE,
    document_id TEXT NOT NULL REFERENCES documents (id) ON DELETE CASCADE,
    chunk_id TEXT REFERENCES chunks (id) ON DELETE SET NULL,
    page INTEGER,
    quote TEXT NOT NULL,
    stance TEXT NOT NULL DEFAULT 'supports'
        CHECK (stance IN ('supports', 'contradicts', 'context')),
    note TEXT,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_evidence_claim ON claim_evidence (claim_id);
"""


def _ensure_tables(store: Store) -> None:
    store.conn.executescript(CLAIMS_DDL)


def _project_id(store: Store, project_name: str) -> int:
    row = store.conn.execute(
        "SELECT id FROM projects WHERE name = ?", (project_name.strip().lower(),)
    ).fetchone()
    if row is None:
        raise ValueError(f"Project '{project_name}' does not exist.")
    return row[0]


# ------------------------------------------------------------------- claims


def add_claim(store: Store, project_name: str, text: str, notes: str | None = None) -> str:
    _ensure_tables(store)
    pid = _project_id(store, project_name)
    max_ord = store.conn.execute(
        "SELECT COALESCE(MAX(ordinal), -1) FROM claims WHERE project_id = ?", (pid,)
    ).fetchone()[0]
    claim_id = new_id()
    store.conn.execute(
        "INSERT INTO claims (id, project_id, text, ordinal, notes, created_at)"
        " VALUES (?, ?, ?, ?, ?, ?)",
        (claim_id, pid, text.strip(), max_ord + 1, notes, now_iso()),
    )
    store.conn.commit()
    return claim_id


def list_claims(store: Store, project_name: str) -> list[dict]:
    _ensure_tables(store)
    pid = _project_id(store, project_name)
    rows = store.conn.execute(
        "SELECT * FROM claims WHERE project_id = ? ORDER BY ordinal", (pid,)
    ).fetchall()
    result = []
    for r in rows:
        evidence_count = store.conn.execute(
            "SELECT COUNT(*) FROM claim_evidence WHERE claim_id = ?", (r["id"],)
        ).fetchone()[0]
        result.append({
            "id": r["id"],
            "text": r["text"],
            "ordinal": r["ordinal"],
            "notes": r["notes"],
            "evidence_count": evidence_count,
            "created_at": r["created_at"],
        })
    return result


def get_claim(store: Store, claim_id: str) -> dict | None:
    _ensure_tables(store)
    row = store.conn.execute("SELECT * FROM claims WHERE id = ?", (claim_id,)).fetchone()
    if row is None:
        return None
    evidence = store.conn.execute(
        "SELECT ce.*, d.title AS document_title FROM claim_evidence ce"
        " JOIN documents d ON d.id = ce.document_id"
        " WHERE ce.claim_id = ? ORDER BY ce.created_at",
        (claim_id,),
    ).fetchall()
    return {
        "id": row["id"],
        "text": row["text"],
        "ordinal": row["ordinal"],
        "notes": row["notes"],
        "evidence": [
            {
                "id": e["id"],
                "document_id": e["document_id"],
                "document_title": e["document_title"],
                "chunk_id": e["chunk_id"],
                "page": e["page"],
                "quote": e["quote"],
                "stance": e["stance"],
                "note": e["note"],
                "created_at": e["created_at"],
            }
            for e in evidence
        ],
    }


def resolve_claim(store: Store, ref: str) -> dict | None:
    """Resolve a full ID or a unique literal ID prefix."""
    exact = get_claim(store, ref)
    if exact:
        return exact
    if not ref:
        return None
    rows = store.conn.execute(
        "SELECT id FROM claims WHERE substr(id, 1, ?) = ? LIMIT 2", (len(ref), ref)
    ).fetchall()
    return get_claim(store, rows[0]["id"]) if len(rows) == 1 else None


def update_claim(store: Store, claim_id: str, text: str | None = None,
                 notes: str | None = ..., ordinal: int | None = None) -> None:
    _ensure_tables(store)
    sets, vals = [], []
    if text is not None:
        sets.append("text = ?")
        vals.append(text.strip())
    if notes is not ...:
        sets.append("notes = ?")
        vals.append(notes)
    if ordinal is not None:
        sets.append("ordinal = ?")
        vals.append(ordinal)
    if not sets:
        return
    vals.append(claim_id)
    store.conn.execute(f"UPDATE claims SET {', '.join(sets)} WHERE id = ?", vals)
    store.conn.commit()


def delete_claim(store: Store, claim_id: str) -> None:
    _ensure_tables(store)
    store.conn.execute("DELETE FROM claims WHERE id = ?", (claim_id,))
    store.conn.commit()


def move_claim(store: Store, claim_id: str, new_ordinal: int) -> None:
    _ensure_tables(store)
    if new_ordinal < 0:
        raise ValueError("Claim position must be zero or greater.")
    row = store.conn.execute("SELECT project_id FROM claims WHERE id = ?", (claim_id,)).fetchone()
    if row is None:
        raise ValueError("Claim not found.")
    pid = row[0]
    claims = store.conn.execute(
        "SELECT id FROM claims WHERE project_id = ? ORDER BY ordinal", (pid,)
    ).fetchall()
    ids = [r["id"] for r in claims]
    if claim_id in ids:
        ids.remove(claim_id)
    ids.insert(min(new_ordinal, len(ids)), claim_id)
    for i, cid in enumerate(ids):
        store.conn.execute("UPDATE claims SET ordinal = ? WHERE id = ?", (i, cid))
    store.conn.commit()


# ----------------------------------------------------------------- evidence


def attach_evidence(
    store: Store,
    claim_id: str,
    document_id: str,
    quote: str,
    chunk_id: str | None = None,
    page: int | None = None,
    stance: str = "supports",
    note: str | None = None,
) -> str:
    _ensure_tables(store)
    if stance not in STANCES:
        raise ValueError(f"stance must be one of {STANCES}")
    eid = new_id()
    store.conn.execute(
        "INSERT INTO claim_evidence"
        " (id, claim_id, document_id, chunk_id, page, quote, stance, note, created_at)"
        " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (eid, claim_id, document_id, chunk_id, page, quote.strip(), stance, note, now_iso()),
    )
    store.conn.commit()
    return eid


def detach_evidence(store: Store, evidence_id: str) -> None:
    _ensure_tables(store)
    store.conn.execute("DELETE FROM claim_evidence WHERE id = ?", (evidence_id,))
    store.conn.commit()


def evidence_for_document(store: Store, document_id: str) -> list[dict]:
    """All evidence attached to any claim from a given document (reverse lookup)."""
    _ensure_tables(store)
    rows = store.conn.execute(
        "SELECT ce.*, c.text AS claim_text FROM claim_evidence ce"
        " JOIN claims c ON c.id = ce.claim_id WHERE ce.document_id = ?",
        (document_id,),
    ).fetchall()
    return [
        {
            "id": r["id"],
            "claim_id": r["claim_id"],
            "claim_text": r["claim_text"],
            "page": r["page"],
            "quote": r["quote"],
            "stance": r["stance"],
        }
        for r in rows
    ]
