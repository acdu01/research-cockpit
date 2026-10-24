"""New-paper watchlists (M16): author/topic/DOI alerts from OpenAlex/arXiv;
matches flow into the to-read queue. Polling is cron-safe.
"""

from __future__ import annotations

from .apis import OpenAlexClient, _get_with_backoff
from .store import Document, Store, new_id, now_iso

WATCH_DDL = """
CREATE TABLE IF NOT EXISTS watchlists (
    id TEXT PRIMARY KEY,
    kind TEXT NOT NULL CHECK (kind IN ('author', 'topic', 'doi')),
    query TEXT NOT NULL,
    name TEXT,
    created_at TEXT NOT NULL,
    last_polled TEXT
);
CREATE TABLE IF NOT EXISTS watch_hits (
    id TEXT PRIMARY KEY,
    watchlist_id TEXT NOT NULL REFERENCES watchlists (id) ON DELETE CASCADE,
    openalex_id TEXT,
    doi TEXT,
    title TEXT,
    found_at TEXT NOT NULL,
    UNIQUE (watchlist_id, doi),
    UNIQUE (watchlist_id, openalex_id)
);
"""


def _ensure_tables(store: Store) -> None:
    store.conn.executescript(WATCH_DDL)


def add_watchlist(store: Store, kind: str, query: str, name: str | None = None) -> str:
    _ensure_tables(store)
    if kind not in ("author", "topic", "doi"):
        raise ValueError("kind must be author/topic/doi")
    wid = new_id()
    store.conn.execute(
        "INSERT INTO watchlists (id, kind, query, name, created_at) VALUES (?, ?, ?, ?, ?)",
        (wid, kind, query.strip(), name or query.strip(), now_iso()),
    )
    store.conn.commit()
    return wid


def list_watchlists(store: Store) -> list[dict]:
    _ensure_tables(store)
    rows = store.conn.execute("SELECT * FROM watchlists ORDER BY created_at").fetchall()
    return [{"id": r["id"], "kind": r["kind"], "query": r["query"],
             "name": r["name"], "last_polled": r["last_polled"]} for r in rows]


def remove_watchlist(store: Store, wid: str) -> None:
    _ensure_tables(store)
    store.conn.execute("DELETE FROM watchlists WHERE id = ?", (wid,))
    store.conn.commit()


def poll(store: Store, client: OpenAlexClient | None = None) -> list[Document]:
    """Poll all watchlists, create to-read records for new matches.

    Cron-safe: quiet, idempotent, rate-limited by OpenAlex defaults.
    """
    _ensure_tables(store)
    if client is None:
        client = OpenAlexClient()
    created: list[Document] = []
    rows = store.conn.execute("SELECT * FROM watchlists").fetchall()
    for row in rows:
        hits = _poll_one(store, client, dict(row))
        created.extend(hits)
        store.conn.execute(
            "UPDATE watchlists SET last_polled = ? WHERE id = ?",
            (now_iso(), row["id"]),
        )
    store.conn.commit()
    return created


def _poll_one(store: Store, client: OpenAlexClient, watch: dict) -> list[Document]:
    """Query OpenAlex for one watchlist, dedupe, create new records."""
    kind, query = watch["kind"], watch["query"]
    params: dict = {"per_page": 10}
    if kind == "author":
        params["filter"] = f"author.search:{query}"
    elif kind == "topic":
        params["search"] = query
    elif kind == "doi":
        params["filter"] = f"doi:{query}"

    data = _get_with_backoff(client.client, "/works", {**client.params, **params})
    if not data:
        return []
    created = []
    for work in data.get("results", []):
        meta = client._parse_work(work)
        if not meta.doi and not meta.openalex_id:
            continue
        # dedupe against watch_hits
        existing = store.conn.execute(
            "SELECT 1 FROM watch_hits WHERE watchlist_id = ? AND"
            " (doi = ? OR openalex_id = ?)",
            (watch["id"], meta.doi, meta.openalex_id),
        ).fetchone()
        if existing:
            continue
        # record hit
        store.conn.execute(
            "INSERT OR IGNORE INTO watch_hits"
            " (id, watchlist_id, openalex_id, doi, title, found_at)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (new_id(), watch["id"], meta.openalex_id, meta.doi, meta.title, now_iso()),
        )
        # create to-read record if not already in library
        if meta.doi and store.find_by_doi(meta.doi):
            continue
        if meta.openalex_id and store.find_by_openalex(meta.openalex_id):
            continue
        doc = Document(
            id=new_id(), collection="papers", title=meta.title,
            authors=meta.authors, year=meta.year, venue=meta.venue,
            doi=meta.doi, openalex_id=meta.openalex_id, status="to-read",
        )
        store.add_document(doc)
        tag_name = f"watch:{watch['name'] or watch['query']}"
        store.tag_document(doc.id, tag_name)
        created.append(doc)
    return created
