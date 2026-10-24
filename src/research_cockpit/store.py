"""SQLite store: schema, queries, and brute-force cosine vector search.

The document record is the hub; every feature reads/writes it. Vector search is
NumPy brute-force cosine over float32 blobs - fine at personal scale (thousands
of chunks). Swap in sqlite-vec later if it ever gets slow.
"""

from __future__ import annotations

import json
import sqlite3
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import numpy as np

COLLECTIONS = ("papers", "notes")
STATUSES = ("to-read", "reading", "annotated", "cited")
ITEM_TYPES = ("article", "inproceedings", "book", "preprint", "misc")

# Full-citation fields added in M8. Kept as a single list so the schema, the
# migration, and the CSL/BibTeX mappers can never drift apart. All nullable:
# a NULL means "the source APIs genuinely don't have this" - stored explicitly.
CITATION_COLUMNS = (
    ("item_type", "TEXT"),
    ("publication_date", "TEXT"),  # ISO date, full date when known
    ("volume", "TEXT"),
    ("issue", "TEXT"),
    ("pages", "TEXT"),  # "first-last" or article number
    ("publisher", "TEXT"),
    ("url", "TEXT"),
    ("abstract", "TEXT"),
    ("issn", "TEXT"),
    ("isbn", "TEXT"),
)

SCHEMA = """
CREATE TABLE IF NOT EXISTS documents (
    id TEXT PRIMARY KEY,
    collection TEXT NOT NULL CHECK (collection IN ('papers', 'notes')),
    title TEXT,
    authors TEXT NOT NULL DEFAULT '[]',
    year INTEGER,
    venue TEXT,
    doi TEXT,
    openalex_id TEXT,
    s2_id TEXT,
    source_path TEXT,
    content_hash TEXT,
    status TEXT CHECK (status IS NULL OR status IN ('to-read', 'reading', 'annotated', 'cited')),
    item_type TEXT,
    publication_date TEXT,
    volume TEXT,
    issue TEXT,
    pages TEXT,
    publisher TEXT,
    url TEXT,
    abstract TEXT,
    issn TEXT,
    isbn TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_documents_collection ON documents (collection);
CREATE INDEX IF NOT EXISTS idx_documents_doi ON documents (doi);
CREATE INDEX IF NOT EXISTS idx_documents_openalex ON documents (openalex_id);
CREATE INDEX IF NOT EXISTS idx_documents_hash ON documents (content_hash);

CREATE TABLE IF NOT EXISTS chunks (
    id TEXT PRIMARY KEY,
    document_id TEXT NOT NULL REFERENCES documents (id) ON DELETE CASCADE,
    ordinal INTEGER NOT NULL,
    text TEXT NOT NULL,
    page INTEGER,
    token_count INTEGER,
    embedding BLOB
);
CREATE INDEX IF NOT EXISTS idx_chunks_document ON chunks (document_id);

CREATE TABLE IF NOT EXISTS annotations (
    id TEXT PRIMARY KEY,
    document_id TEXT NOT NULL REFERENCES documents (id) ON DELETE CASCADE,
    text TEXT NOT NULL,
    page INTEGER,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS tags (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL UNIQUE
);
CREATE TABLE IF NOT EXISTS document_tags (
    document_id TEXT NOT NULL REFERENCES documents (id) ON DELETE CASCADE,
    tag_id INTEGER NOT NULL REFERENCES tags (id) ON DELETE CASCADE,
    PRIMARY KEY (document_id, tag_id)
);

CREATE TABLE IF NOT EXISTS projects (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    description TEXT,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS document_projects (
    document_id TEXT NOT NULL REFERENCES documents (id) ON DELETE CASCADE,
    project_id INTEGER NOT NULL REFERENCES projects (id) ON DELETE CASCADE,
    PRIMARY KEY (document_id, project_id)
);

CREATE TABLE IF NOT EXISTS citations (
    id INTEGER PRIMARY KEY,
    citing_id TEXT REFERENCES documents (id) ON DELETE CASCADE,
    cited_id TEXT REFERENCES documents (id) ON DELETE CASCADE,
    citing_ext TEXT,
    cited_ext TEXT,
    citing_title TEXT,
    cited_title TEXT,
    source TEXT NOT NULL,
    UNIQUE (citing_id, cited_id, citing_ext, cited_ext)
);

CREATE TABLE IF NOT EXISTS review_schedule (
    document_id TEXT PRIMARY KEY REFERENCES documents (id) ON DELETE CASCADE,
    ease REAL NOT NULL DEFAULT 2.5,
    interval_days REAL NOT NULL DEFAULT 0,
    reps INTEGER NOT NULL DEFAULT 0,
    due_date TEXT NOT NULL,
    last_reviewed TEXT
);

CREATE TABLE IF NOT EXISTS flashcards (
    id TEXT PRIMARY KEY,
    document_id TEXT NOT NULL REFERENCES documents (id) ON DELETE CASCADE,
    question TEXT NOT NULL,
    answer TEXT NOT NULL,
    source_annotation_id TEXT REFERENCES annotations (id) ON DELETE CASCADE
);
"""


def now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def new_id() -> str:
    return uuid.uuid4().hex


@dataclass
class Document:
    id: str
    collection: str
    title: str | None = None
    authors: list[str] = field(default_factory=list)
    year: int | None = None
    venue: str | None = None
    doi: str | None = None
    openalex_id: str | None = None
    s2_id: str | None = None
    source_path: str | None = None
    content_hash: str | None = None
    status: str | None = None
    item_type: str | None = None
    publication_date: str | None = None
    volume: str | None = None
    issue: str | None = None
    pages: str | None = None
    publisher: str | None = None
    url: str | None = None
    abstract: str | None = None
    issn: str | None = None
    isbn: str | None = None
    created_at: str = ""
    updated_at: str = ""

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> Document:
        return cls(
            id=row["id"],
            collection=row["collection"],
            title=row["title"],
            authors=json.loads(row["authors"] or "[]"),
            year=row["year"],
            venue=row["venue"],
            doi=row["doi"],
            openalex_id=row["openalex_id"],
            s2_id=row["s2_id"],
            source_path=row["source_path"],
            content_hash=row["content_hash"],
            status=row["status"],
            item_type=row["item_type"],
            publication_date=row["publication_date"],
            volume=row["volume"],
            issue=row["issue"],
            pages=row["pages"],
            publisher=row["publisher"],
            url=row["url"],
            abstract=row["abstract"],
            issn=row["issn"],
            isbn=row["isbn"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )


@dataclass
class Chunk:
    id: str
    document_id: str
    ordinal: int
    text: str
    page: int | None
    token_count: int


def embed_to_blob(vec: np.ndarray) -> bytes:
    return np.asarray(vec, dtype=np.float32).tobytes()


def blob_to_embed(blob: bytes) -> np.ndarray:
    return np.frombuffer(blob, dtype=np.float32)


class Store:
    def __init__(self, path: str | Path):
        path = Path(path).expanduser()
        if str(path) != ":memory:":
            path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(path))
        self.conn.row_factory = sqlite3.Row
        self._transaction_depth = 0
        self.conn.execute("PRAGMA foreign_keys = ON")
        self.conn.executescript(SCHEMA)
        self._migrate()
        self._commit()

    def _migrate(self) -> None:
        """Additive migrations for databases created by earlier versions."""
        cols = {r["name"] for r in self.conn.execute("PRAGMA table_info(annotations)")}
        if "source" not in cols:
            self.conn.execute(
                "ALTER TABLE annotations ADD COLUMN source TEXT NOT NULL DEFAULT 'human'"
            )
        doc_cols = {r["name"] for r in self.conn.execute("PRAGMA table_info(documents)")}
        for name, decl in CITATION_COLUMNS:
            if name not in doc_cols:
                self.conn.execute(f"ALTER TABLE documents ADD COLUMN {name} {decl}")
        chunk_cols = {r["name"] for r in self.conn.execute("PRAGMA table_info(chunks)")}
        if "section" not in chunk_cols:
            self.conn.execute("ALTER TABLE chunks ADD COLUMN section TEXT")

    def close(self) -> None:
        self.conn.close()

    @contextmanager
    def transaction(self) -> Iterator[None]:
        """Group store mutations atomically, including nested operations."""
        savepoint = f"rc_{self._transaction_depth}"
        self.conn.execute(f"SAVEPOINT {savepoint}")
        self._transaction_depth += 1
        try:
            yield
        except BaseException:
            self.conn.execute(f"ROLLBACK TO SAVEPOINT {savepoint}")
            raise
        finally:
            self._transaction_depth -= 1
            self.conn.execute(f"RELEASE SAVEPOINT {savepoint}")

    def _commit(self) -> None:
        if not self._transaction_depth:
            self.conn.commit()

    # ------------------------------------------------------------- documents

    def add_document(self, doc: Document) -> Document:
        doc.created_at = doc.created_at or now_iso()
        doc.updated_at = doc.updated_at or doc.created_at
        self.conn.execute(
            """INSERT INTO documents (id, collection, title, authors, year, venue, doi,
                   openalex_id, s2_id, source_path, content_hash, status,
                   item_type, publication_date, volume, issue, pages, publisher,
                   url, abstract, issn, isbn, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                       ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                doc.id, doc.collection, doc.title, json.dumps(doc.authors), doc.year,
                doc.venue, doc.doi, doc.openalex_id, doc.s2_id, doc.source_path,
                doc.content_hash, doc.status,
                doc.item_type, doc.publication_date, doc.volume, doc.issue, doc.pages,
                doc.publisher, doc.url, doc.abstract, doc.issn, doc.isbn,
                doc.created_at, doc.updated_at,
            ),
        )
        self._commit()
        return doc

    def update_document(self, doc_id: str, **fields: Any) -> None:
        if not fields:
            return
        if "authors" in fields:
            fields["authors"] = json.dumps(fields["authors"])
        fields["updated_at"] = now_iso()
        cols = ", ".join(f"{k} = ?" for k in fields)
        self.conn.execute(
            f"UPDATE documents SET {cols} WHERE id = ?", (*fields.values(), doc_id)
        )
        self._commit()

    def get_document(self, doc_id: str) -> Document | None:
        row = self.conn.execute("SELECT * FROM documents WHERE id = ?", (doc_id,)).fetchone()
        return Document.from_row(row) if row else None

    def resolve_document(self, ref: str) -> Document | None:
        """Resolve by full id, unique id prefix, DOI, or exact title."""
        for query, arg in (
            ("SELECT * FROM documents WHERE id = ?", ref),
            ("SELECT * FROM documents WHERE doi = ? COLLATE NOCASE", ref),
            ("SELECT * FROM documents WHERE title = ? COLLATE NOCASE", ref),
        ):
            row = self.conn.execute(query, (arg,)).fetchone()
            if row:
                return Document.from_row(row)
        if not ref:
            return None
        rows = self.conn.execute(
            "SELECT * FROM documents WHERE substr(id, 1, ?) = ? LIMIT 2", (len(ref), ref)
        ).fetchall()
        if len(rows) == 1:
            return Document.from_row(rows[0])
        return None

    def find_by_hash(self, content_hash: str) -> Document | None:
        row = self.conn.execute(
            "SELECT * FROM documents WHERE content_hash = ?", (content_hash,)
        ).fetchone()
        return Document.from_row(row) if row else None

    def find_by_openalex(self, openalex_id: str) -> Document | None:
        row = self.conn.execute(
            "SELECT * FROM documents WHERE openalex_id = ?", (openalex_id,)
        ).fetchone()
        return Document.from_row(row) if row else None

    def find_by_doi(self, doi: str) -> Document | None:
        row = self.conn.execute(
            "SELECT * FROM documents WHERE doi = ? COLLATE NOCASE", (doi,)
        ).fetchone()
        return Document.from_row(row) if row else None

    def list_documents(
        self,
        collection: str | None = None,
        status: str | None = None,
        tag: str | None = None,
        project: str | None = None,
    ) -> list[Document]:
        sql = "SELECT DISTINCT d.* FROM documents d"
        where, args = [], []
        if tag:
            sql += (
                " JOIN document_tags dt ON dt.document_id = d.id"
                " JOIN tags t ON t.id = dt.tag_id"
            )
            where.append("t.name = ?")
            args.append(tag)
        if project:
            sql += (
                " JOIN document_projects dp ON dp.document_id = d.id"
                " JOIN projects p ON p.id = dp.project_id"
            )
            where.append("p.name = ?")
            args.append(project.strip().lower())
        if collection:
            where.append("d.collection = ?")
            args.append(collection)
        if status:
            where.append("d.status = ?")
            args.append(status)
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += " ORDER BY d.created_at DESC"
        return [Document.from_row(r) for r in self.conn.execute(sql, args).fetchall()]

    def delete_document(self, doc_id: str) -> None:
        self.conn.execute("DELETE FROM documents WHERE id = ?", (doc_id,))
        self._commit()

    # ---------------------------------------------------------------- chunks

    def add_chunks(self, chunks: list[Chunk], embeddings: np.ndarray) -> None:
        embeddings = np.asarray(embeddings, dtype=np.float32)
        if embeddings.ndim != 2 or len(embeddings) != len(chunks):
            raise ValueError("Provide one embedding vector per chunk")
        if not np.isfinite(embeddings).all():
            raise ValueError("Embedding vectors must contain only finite values")
        rows = [
            (c.id, c.document_id, c.ordinal, c.text, c.page, c.token_count,
             embed_to_blob(embeddings[i]))
            for i, c in enumerate(chunks)
        ]
        with self.transaction():
            self.conn.executemany(
                "INSERT INTO chunks (id, document_id, ordinal, text, page, token_count, embedding)"
                " VALUES (?, ?, ?, ?, ?, ?, ?)",
                rows,
            )

    def chunk_count(self, document_id: str | None = None) -> int:
        if document_id:
            return self.conn.execute(
                "SELECT COUNT(*) FROM chunks WHERE document_id = ?", (document_id,)
            ).fetchone()[0]
        return self.conn.execute("SELECT COUNT(*) FROM chunks").fetchone()[0]

    def document_chunks(self, document_id: str) -> list[Chunk]:
        rows = self.conn.execute(
            "SELECT * FROM chunks WHERE document_id = ? ORDER BY ordinal", (document_id,)
        ).fetchall()
        return [
            Chunk(r["id"], r["document_id"], r["ordinal"], r["text"], r["page"],
                  r["token_count"])
            for r in rows
        ]

    def search_chunks(
        self,
        query_vec: np.ndarray,
        k: int = 8,
        collections: tuple[str, ...] = ("papers",),
        tag: str | None = None,
        status: str | None = None,
        project: str | None = None,
    ) -> list[tuple[Chunk, Document, float]]:
        """Brute-force cosine top-k. Embeddings are stored L2-normalized, so dot = cosine."""
        if k <= 0 or not collections:
            return []
        sql = (
            "SELECT c.id, c.document_id, c.ordinal, c.text, c.page, c.token_count,"
            " c.embedding FROM chunks c JOIN documents d ON d.id = c.document_id"
        )
        where = [f"d.collection IN ({','.join('?' * len(collections))})"]
        args: list[Any] = list(collections)
        if tag:
            sql += (
                " JOIN document_tags dt ON dt.document_id = d.id"
                " JOIN tags t ON t.id = dt.tag_id"
            )
            where.append("t.name = ?")
            args.append(tag)
        if project:
            sql += (
                " JOIN document_projects dp ON dp.document_id = d.id"
                " JOIN projects p ON p.id = dp.project_id"
            )
            where.append("p.name = ?")
            args.append(project.strip().lower())
        if status:
            where.append("d.status = ?")
            args.append(status)
        sql += " WHERE " + " AND ".join(where)
        rows = self.conn.execute(sql, args).fetchall()
        if not rows:
            return []
        matrix = np.vstack([blob_to_embed(r["embedding"]) for r in rows])
        q = np.asarray(query_vec, dtype=np.float32)
        norm = np.linalg.norm(q)
        if norm > 0:
            q = q / norm
        scores = matrix @ q
        order = np.argsort(-scores)[:k]
        results = []
        doc_cache: dict[str, Document] = {}
        for i in order:
            r = rows[int(i)]
            doc_id = r["document_id"]
            if doc_id not in doc_cache:
                doc_cache[doc_id] = self.get_document(doc_id)  # type: ignore[assignment]
            chunk = Chunk(r["id"], doc_id, r["ordinal"], r["text"], r["page"], r["token_count"])
            results.append((chunk, doc_cache[doc_id], float(scores[int(i)])))
        return results

    # ----------------------------------------------------------- annotations

    def add_annotation(
        self, document_id: str, text: str, page: int | None = None, source: str = "human"
    ) -> str:
        ann_id = new_id()
        self.conn.execute(
            "INSERT INTO annotations (id, document_id, text, page, created_at, source)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (ann_id, document_id, text, page, now_iso(), source),
        )
        self._commit()
        return ann_id

    def annotations(self, document_id: str) -> list[sqlite3.Row]:
        return self.conn.execute(
            "SELECT * FROM annotations WHERE document_id = ? ORDER BY created_at",
            (document_id,),
        ).fetchall()

    def delete_annotation(self, annotation_id: str) -> None:
        self.conn.execute("DELETE FROM annotations WHERE id = ?", (annotation_id,))
        self._commit()

    # ------------------------------------------------------------------ tags

    def tag_document(self, document_id: str, *names: str) -> None:
        for name in names:
            name = name.strip().lower()
            if not name:
                continue
            self.conn.execute("INSERT OR IGNORE INTO tags (name) VALUES (?)", (name,))
            tag_id = self.conn.execute(
                "SELECT id FROM tags WHERE name = ?", (name,)
            ).fetchone()[0]
            self.conn.execute(
                "INSERT OR IGNORE INTO document_tags (document_id, tag_id) VALUES (?, ?)",
                (document_id, tag_id),
            )
        self._commit()

    def untag_document(self, document_id: str, name: str) -> None:
        self.conn.execute(
            "DELETE FROM document_tags WHERE document_id = ? AND tag_id ="
            " (SELECT id FROM tags WHERE name = ?)",
            (document_id, name.strip().lower()),
        )
        self._commit()

    def all_tags(self) -> list[str]:
        return [r["name"] for r in self.conn.execute("SELECT name FROM tags ORDER BY name")]

    def document_tags(self, document_id: str) -> list[str]:
        rows = self.conn.execute(
            "SELECT t.name FROM tags t JOIN document_tags dt ON dt.tag_id = t.id"
            " WHERE dt.document_id = ? ORDER BY t.name",
            (document_id,),
        ).fetchall()
        return [r["name"] for r in rows]

    # -------------------------------------------------------------- projects

    def create_project(self, name: str, description: str | None = None) -> str:
        name = name.strip().lower()
        if not name:
            raise ValueError("Project name cannot be empty")
        self.conn.execute(
            "INSERT OR IGNORE INTO projects (name, description, created_at) VALUES (?, ?, ?)",
            (name, description, now_iso()),
        )
        self._commit()
        return name

    def list_projects(self) -> list[sqlite3.Row]:
        return self.conn.execute(
            """SELECT p.*, COUNT(dp.document_id) AS documents
               FROM projects p LEFT JOIN document_projects dp ON dp.project_id = p.id
               GROUP BY p.id ORDER BY p.name"""
        ).fetchall()

    def delete_project(self, name: str) -> None:
        self.conn.execute("DELETE FROM projects WHERE name = ?", (name.strip().lower(),))
        self._commit()

    def assign_project(self, document_id: str, name: str) -> None:
        """Assign a document to a project, creating the project if needed."""
        name = self.create_project(name)
        project_id = self.conn.execute(
            "SELECT id FROM projects WHERE name = ?", (name,)
        ).fetchone()[0]
        self.conn.execute(
            "INSERT OR IGNORE INTO document_projects (document_id, project_id) VALUES (?, ?)",
            (document_id, project_id),
        )
        self._commit()

    def unassign_project(self, document_id: str, name: str) -> None:
        self.conn.execute(
            "DELETE FROM document_projects WHERE document_id = ? AND project_id ="
            " (SELECT id FROM projects WHERE name = ?)",
            (document_id, name.strip().lower()),
        )
        self._commit()

    def document_projects(self, document_id: str) -> list[str]:
        rows = self.conn.execute(
            "SELECT p.name FROM projects p JOIN document_projects dp ON dp.project_id = p.id"
            " WHERE dp.document_id = ? ORDER BY p.name",
            (document_id,),
        ).fetchall()
        return [r["name"] for r in rows]

    # ------------------------------------------------------------- citations

    def upsert_citation(
        self,
        source: str,
        citing_id: str | None = None,
        cited_id: str | None = None,
        citing_ext: str | None = None,
        cited_ext: str | None = None,
        citing_title: str | None = None,
        cited_title: str | None = None,
    ) -> None:
        # SQLite UNIQUE constraints treat NULLs as distinct; graph endpoints
        # routinely contain NULL, so ON CONFLICT alone never deduplicated them.
        with self.transaction():
            updated = self.conn.execute(
                """UPDATE citations SET
                       citing_title = COALESCE(?, citing_title),
                       cited_title = COALESCE(?, cited_title)
                   WHERE citing_id IS ? AND cited_id IS ?
                     AND citing_ext IS ? AND cited_ext IS ?""",
                (citing_title, cited_title, citing_id, cited_id, citing_ext, cited_ext),
            )
            if updated.rowcount:
                return
            self.conn.execute(
                """INSERT INTO citations
                   (citing_id, cited_id, citing_ext, cited_ext, citing_title, cited_title, source)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (citing_id, cited_id, citing_ext, cited_ext, citing_title, cited_title, source),
            )

    def citations(self) -> list[sqlite3.Row]:
        return self.conn.execute("SELECT * FROM citations").fetchall()

    # ------------------------------------------------------- review schedule

    def get_schedule(self, document_id: str) -> sqlite3.Row | None:
        return self.conn.execute(
            "SELECT * FROM review_schedule WHERE document_id = ?", (document_id,)
        ).fetchone()

    def upsert_schedule(
        self,
        document_id: str,
        ease: float,
        interval_days: float,
        reps: int,
        due_date: str,
        last_reviewed: str | None = None,
    ) -> None:
        self.conn.execute(
            """INSERT INTO review_schedule
                   (document_id, ease, interval_days, reps, due_date, last_reviewed)
               VALUES (?, ?, ?, ?, ?, ?)
               ON CONFLICT (document_id) DO UPDATE SET
                   ease = excluded.ease, interval_days = excluded.interval_days,
                   reps = excluded.reps, due_date = excluded.due_date,
                   last_reviewed = excluded.last_reviewed""",
            (document_id, ease, interval_days, reps, due_date, last_reviewed),
        )
        self._commit()

    def due_documents(self, on: date | None = None) -> list[Document]:
        cutoff = (on or date.today()).isoformat()
        rows = self.conn.execute(
            """SELECT d.* FROM documents d JOIN review_schedule r ON r.document_id = d.id
               WHERE d.collection = 'papers' AND r.due_date <= ? ORDER BY r.due_date""",
            (cutoff,),
        ).fetchall()
        return [Document.from_row(r) for r in rows]

    # ------------------------------------------------------------ flashcards

    def replace_flashcards(
        self, document_id: str, cards: list[tuple[str, str, str | None]]
    ) -> None:
        """cards: list of (question, answer, source_annotation_id)."""
        self.conn.execute("DELETE FROM flashcards WHERE document_id = ?", (document_id,))
        self.conn.executemany(
            "INSERT INTO flashcards (id, document_id, question, answer, source_annotation_id)"
            " VALUES (?, ?, ?, ?, ?)",
            [(new_id(), document_id, q, a, src) for q, a, src in cards],
        )
        self._commit()

    def flashcards(self, document_id: str) -> list[sqlite3.Row]:
        return self.conn.execute(
            "SELECT * FROM flashcards WHERE document_id = ?", (document_id,)
        ).fetchall()
