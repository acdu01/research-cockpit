"""Constellation: notes graph (M19) - note↔note links, semantic suggestions,
and note→source provenance.

Edges are undirected (canonical a<b pair), with status confirmed|dismissed.
Suggested edges are computed at view time (never persisted); only user decisions
(confirm/dismiss) are stored. Note→source provenance uses a separate table with
a verbatim quote anchor.
"""

from __future__ import annotations

import json
from pathlib import Path

import networkx as nx
import numpy as np

from .store import Store, blob_to_embed, new_id, now_iso

CONSTELLATION_DDL = """
CREATE TABLE IF NOT EXISTS note_links (
    a_id TEXT NOT NULL REFERENCES documents (id) ON DELETE CASCADE,
    b_id TEXT NOT NULL REFERENCES documents (id) ON DELETE CASCADE,
    status TEXT NOT NULL CHECK (status IN ('confirmed', 'dismissed')),
    label TEXT,
    created_at TEXT NOT NULL,
    PRIMARY KEY (a_id, b_id),
    CHECK (a_id < b_id)
);
CREATE TABLE IF NOT EXISTS note_sources (
    id TEXT PRIMARY KEY,
    note_id TEXT NOT NULL REFERENCES documents (id) ON DELETE CASCADE,
    document_id TEXT NOT NULL REFERENCES documents (id) ON DELETE CASCADE,
    chunk_id TEXT REFERENCES chunks (id) ON DELETE SET NULL,
    page INTEGER,
    quote TEXT,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_nsources_note ON note_sources (note_id);
"""


def _ensure_tables(store: Store) -> None:
    store.conn.executescript(CONSTELLATION_DDL)


def _canonical(a: str, b: str) -> tuple[str, str]:
    return (a, b) if a < b else (b, a)


# --------------------------------------------------------------- note links


def link_notes(store: Store, a_id: str, b_id: str,
               label: str | None = None, status: str = "confirmed") -> None:
    _ensure_tables(store)
    a, b = _canonical(a_id, b_id)
    store.conn.execute(
        "INSERT OR REPLACE INTO note_links (a_id, b_id, status, label, created_at)"
        " VALUES (?, ?, ?, ?, ?)",
        (a, b, status, label, now_iso()),
    )
    store.conn.commit()


def unlink_notes(store: Store, a_id: str, b_id: str) -> None:
    _ensure_tables(store)
    a, b = _canonical(a_id, b_id)
    store.conn.execute("DELETE FROM note_links WHERE a_id = ? AND b_id = ?", (a, b))
    store.conn.commit()


def dismiss_suggestion(store: Store, a_id: str, b_id: str) -> None:
    link_notes(store, a_id, b_id, status="dismissed")


def confirmed_links(store: Store) -> list[dict]:
    _ensure_tables(store)
    rows = store.conn.execute(
        "SELECT * FROM note_links WHERE status = 'confirmed'"
    ).fetchall()
    return [{"a_id": r["a_id"], "b_id": r["b_id"], "label": r["label"]} for r in rows]


def dismissed_pairs(store: Store) -> set[tuple[str, str]]:
    _ensure_tables(store)
    rows = store.conn.execute(
        "SELECT a_id, b_id FROM note_links WHERE status = 'dismissed'"
    ).fetchall()
    return {(r["a_id"], r["b_id"]) for r in rows}


# -------------------------------------------------------- suggested edges


def suggest_links(store: Store, threshold: float = 0.60, top_k: int = 3) -> list[dict]:
    """Compute ephemeral semantic-similarity suggestions between notes.

    Returns pairs with score >= threshold, excluding confirmed/dismissed.
    """
    _ensure_tables(store)
    notes = store.list_documents(collection="notes")
    if len(notes) < 2:
        return []
    dismissed = dismissed_pairs(store)
    confirmed_set = {(r["a_id"], r["b_id"]) for r in confirmed_links(store)}
    # note-level embeddings: mean of chunk vectors
    embeddings: dict[str, np.ndarray] = {}
    for note in notes:
        rows = store.conn.execute(
            "SELECT embedding FROM chunks WHERE document_id = ?", (note.id,)
        ).fetchall()
        if rows:
            vecs = np.vstack([blob_to_embed(r["embedding"]) for r in rows])
            embeddings[note.id] = vecs.mean(axis=0)
    if len(embeddings) < 2:
        return []
    ids = list(embeddings.keys())
    matrix = np.vstack([embeddings[i] for i in ids])
    norms = np.linalg.norm(matrix, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    matrix = matrix / norms
    cosines = matrix @ matrix.T
    suggestions = []
    for i in range(len(ids)):
        scores = [(j, cosines[i, j]) for j in range(len(ids)) if j != i]
        scores.sort(key=lambda x: -x[1])
        for j, score in scores[:top_k]:
            if score < threshold:
                break
            a, b = _canonical(ids[i], ids[j])
            if (a, b) in dismissed or (a, b) in confirmed_set:
                continue
            suggestions.append({"a_id": a, "b_id": b, "score": float(score)})
    # dedupe
    seen = set()
    deduped = []
    for s in suggestions:
        key = (s["a_id"], s["b_id"])
        if key not in seen:
            deduped.append(s)
            seen.add(key)
    return sorted(deduped, key=lambda x: -x["score"])


# -------------------------------------------------------- provenance


def add_source(store: Store, note_id: str, document_id: str,
               chunk_id: str | None = None, page: int | None = None,
               quote: str | None = None) -> str:
    _ensure_tables(store)
    sid = new_id()
    store.conn.execute(
        "INSERT INTO note_sources (id, note_id, document_id, chunk_id, page, quote, created_at)"
        " VALUES (?, ?, ?, ?, ?, ?, ?)",
        (sid, note_id, document_id, chunk_id, page, quote, now_iso()),
    )
    store.conn.commit()
    return sid


def get_sources(store: Store, note_id: str) -> list[dict]:
    _ensure_tables(store)
    rows = store.conn.execute(
        "SELECT ns.*, d.title AS document_title FROM note_sources ns"
        " JOIN documents d ON d.id = ns.document_id WHERE ns.note_id = ?",
        (note_id,),
    ).fetchall()
    return [
        {"id": r["id"], "document_id": r["document_id"],
         "document_title": r["document_title"], "chunk_id": r["chunk_id"],
         "page": r["page"], "quote": r["quote"]}
        for r in rows
    ]


# -------------------------------------------------------------- graph + export


def to_networkx(store: Store) -> nx.Graph:
    _ensure_tables(store)
    g = nx.Graph()
    for doc in store.list_documents(collection="notes"):
        g.add_node(doc.id, title=doc.title or "Untitled")
    for link in confirmed_links(store):
        g.add_edge(link["a_id"], link["b_id"], label=link["label"] or "")
    return g


def export_constellation(store: Store, path: Path) -> None:
    g = to_networkx(store)
    suffix = Path(path).suffix.lower()
    if suffix == ".graphml":
        nx.write_graphml(g, path)
    elif suffix == ".json":
        data = nx.node_link_data(g, edges="links")
        # enrich with provenance
        for node_data in data["nodes"]:
            node_data["sources"] = get_sources(store, node_data["id"])
        Path(path).write_text(json.dumps(data, indent=2))
    else:
        raise ValueError(f"Unsupported format '{suffix}' (use .graphml/.json)")
