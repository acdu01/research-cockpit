"""Reproducibility tracking (M17): per-paper code/data availability,
benchmark settings, and replication status.
"""

from __future__ import annotations

from .store import Store, now_iso

CODE_AVAILABILITY = ("none", "linked", "verified")
DATA_AVAILABILITY = ("none", "linked", "verified")
REPLICATION_STATUS = ("none", "attempted", "replicated", "failed")

REPRO_DDL = """
CREATE TABLE IF NOT EXISTS reproducibility (
    document_id TEXT PRIMARY KEY REFERENCES documents (id) ON DELETE CASCADE,
    code_availability TEXT NOT NULL DEFAULT 'none'
        CHECK (code_availability IN ('none', 'linked', 'verified')),
    code_url TEXT,
    data_availability TEXT NOT NULL DEFAULT 'none'
        CHECK (data_availability IN ('none', 'linked', 'verified')),
    data_url TEXT,
    benchmark_settings TEXT,
    replicated TEXT NOT NULL DEFAULT 'none'
        CHECK (replicated IN ('none', 'attempted', 'replicated', 'failed')),
    notes TEXT,
    updated_at TEXT NOT NULL
);
"""


def _ensure_table(store: Store) -> None:
    store.conn.executescript(REPRO_DDL)


def get_repro(store: Store, doc_id: str) -> dict | None:
    _ensure_table(store)
    row = store.conn.execute(
        "SELECT * FROM reproducibility WHERE document_id = ?", (doc_id,)
    ).fetchone()
    if row is None:
        return None
    return dict(row)


def set_repro(store: Store, doc_id: str, **fields) -> None:
    """Set one or more reproducibility fields. Validates enum values."""
    _ensure_table(store)
    for key, allowed in (
        ("code_availability", CODE_AVAILABILITY),
        ("data_availability", DATA_AVAILABILITY),
        ("replicated", REPLICATION_STATUS),
    ):
        if key in fields and fields[key] not in allowed:
            raise ValueError(f"{key} must be one of {allowed}")
    existing = get_repro(store, doc_id)
    fields["updated_at"] = now_iso()
    if existing:
        sets = ", ".join(f"{k} = ?" for k in fields)
        store.conn.execute(
            f"UPDATE reproducibility SET {sets} WHERE document_id = ?",
            (*fields.values(), doc_id),
        )
    else:
        fields["document_id"] = doc_id
        cols = ", ".join(fields.keys())
        placeholders = ", ".join("?" * len(fields))
        store.conn.execute(
            f"INSERT INTO reproducibility ({cols}) VALUES ({placeholders})",
            tuple(fields.values()),
        )
    store.conn.commit()
