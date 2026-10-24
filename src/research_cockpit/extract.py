"""Structured paper extraction (M9): extract task/method/datasets/metrics/
findings/limitations from a paper's chunks via the LLM adapter, persisted in
a `paper_extractions` table with per-field llm/human provenance so re-runs
never overwrite manual corrections.
"""

from __future__ import annotations

import json

from .llm import LLMAdapter, LLMError
from .store import Document, Store, now_iso

EXTRACTION_SYSTEM = (
    "You extract structured research metadata from papers. Given the paper's"
    " title and key excerpts, respond with ONLY a JSON object with exactly these"
    " six keys: task, method, datasets, metrics, findings, limitations."
    '\n"task": one-sentence statement of the paper\'s main task/goal (string or null).'
    '\n"method": one-sentence summary of the primary approach/technique (string or null).'
    '\n"datasets": array of dataset name strings used by the paper (empty array = none stated).'
    '\n"metrics": array of objects {name, value, dataset} where name is required,'
    ' and value/dataset may be null (empty array = none reported).'
    '\n"findings": array of key findings/claims, each a short sentence (empty array = unclear).'
    '\n"limitations": array of stated limitations, each a short sentence'
    " (empty array = none stated)."
    "\nFor fields the paper genuinely doesn't cover, use null (scalars) or [] (arrays)."
    "\nNo prose, no markdown fences, no extra keys."
)

EXTRACTION_FIELDS = ("task", "method", "datasets", "metrics", "findings", "limitations")
_SCALAR_FIELDS = ("task", "method")
_ARRAY_FIELDS = ("datasets", "metrics", "findings", "limitations")

SCHEMA_DDL = """
CREATE TABLE IF NOT EXISTS paper_extractions (
    document_id TEXT PRIMARY KEY REFERENCES documents (id) ON DELETE CASCADE,
    task TEXT,
    method TEXT,
    datasets TEXT NOT NULL DEFAULT '[]',
    metrics TEXT NOT NULL DEFAULT '[]',
    findings TEXT NOT NULL DEFAULT '[]',
    limitations TEXT NOT NULL DEFAULT '[]',
    field_sources TEXT NOT NULL DEFAULT '{}',
    model TEXT,
    extracted_at TEXT,
    updated_at TEXT NOT NULL
);
"""


def _ensure_table(store: Store) -> None:
    store.conn.executescript(SCHEMA_DDL)


def _validate_extraction(obj: dict) -> dict:
    """Normalize raw LLM output into the canonical shape - raises on garbage."""
    out: dict = {}
    for f in _SCALAR_FIELDS:
        v = obj.get(f)
        out[f] = str(v).strip() if v and str(v).strip() else None
    for f in _ARRAY_FIELDS:
        v = obj.get(f)
        if not isinstance(v, list):
            out[f] = []
        else:
            out[f] = v
    # metrics: each element must be a dict with at least 'name'
    cleaned_metrics = []
    for item in out.get("metrics", []):
        if isinstance(item, dict) and item.get("name"):
            cleaned_metrics.append({
                "name": str(item["name"]).strip(),
                "value": str(item["value"]).strip() if item.get("value") else None,
                "dataset": str(item["dataset"]).strip() if item.get("dataset") else None,
            })
        elif isinstance(item, str) and item.strip():
            cleaned_metrics.append({"name": item.strip(), "value": None, "dataset": None})
    out["metrics"] = cleaned_metrics
    # datasets/findings/limitations: flatten to string arrays
    for f in ("datasets", "findings", "limitations"):
        out[f] = [str(x).strip() for x in out[f] if str(x).strip()]
    return out


def extract_paper(
    store: Store, adapter: LLMAdapter, doc: Document, force: bool = False
) -> dict:
    """Run LLM extraction for one paper. Non-fatal caller: returns the dict
    (or raises LLMError). `force` overwrites even human-sourced fields.
    """
    _ensure_table(store)
    existing = get_extraction(store, doc.id)
    field_sources = json.loads(existing["field_sources"]) if existing else {}

    chunks = store.document_chunks(doc.id)[:8]
    if not chunks:
        raise LLMError("No chunks to extract from (paper has no indexed text).")
    excerpts = "\n\n".join(
        (f"[p.{c.page}] " if c.page else "") + c.text for c in chunks
    )[:8000]
    prompt = (
        f"Paper: {doc.title or 'Untitled'}"
        + (f" ({doc.year})" if doc.year else "")
        + f"\n\nExcerpts:\n\n{excerpts}"
    )

    raw = adapter.generate(prompt, system=EXTRACTION_SYSTEM)
    # Parse JSON while tolerating surrounding prose or markdown fences.
    obj = _parse_obj(raw)
    if obj is None:
        # retry once with the validation error
        raw = adapter.generate(
            prompt + "\n\n(Your previous response was not valid JSON. Respond"
            " with ONLY a JSON object - no prose, no fences.)",
            system=EXTRACTION_SYSTEM,
        )
        obj = _parse_obj(raw)
    if obj is None:
        raise LLMError(f"Extraction returned no parseable JSON object: {raw[:200]}")

    validated = _validate_extraction(obj)

    # Determine which fields we may overwrite (respect human corrections)
    updates: dict = {}
    new_sources = dict(field_sources)
    for f in EXTRACTION_FIELDS:
        old_source = field_sources.get(f)
        if old_source == "human" and not force:
            continue
        updates[f] = validated[f]
        new_sources[f] = "llm"

    _upsert(store, doc.id, updates, new_sources, model=getattr(adapter, "model", None))
    return get_extraction(store, doc.id) or validated


def _parse_obj(raw: str) -> dict | None:
    """Try to extract a JSON object from the response."""
    import re

    decoder = json.JSONDecoder()
    for match in re.finditer(r"\{", raw):
        try:
            obj, _ = decoder.raw_decode(raw, match.start())
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict):
            return obj
    return None


def _upsert(
    store: Store, doc_id: str, fields: dict, sources: dict, model: str | None
) -> None:
    now = now_iso()
    row = store.conn.execute(
        "SELECT 1 FROM paper_extractions WHERE document_id = ?", (doc_id,)
    ).fetchone()
    if row:
        sets = ["updated_at = ?", "field_sources = ?"]
        vals: list = [now, json.dumps(sources)]
        if model:
            sets.append("model = ?")
            vals.append(model)
            sets.append("extracted_at = ?")
            vals.append(now)
        for f in EXTRACTION_FIELDS:
            if f in fields:
                sets.append(f"{f} = ?")
                val = fields[f]
                vals.append(json.dumps(val) if isinstance(val, (list, dict)) else val)
        vals.append(doc_id)
        store.conn.execute(
            f"UPDATE paper_extractions SET {', '.join(sets)} WHERE document_id = ?",
            vals,
        )
    else:
        store.conn.execute(
            """INSERT INTO paper_extractions
                   (document_id, task, method, datasets, metrics, findings, limitations,
                    field_sources, model, extracted_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                doc_id,
                fields.get("task"),
                fields.get("method"),
                json.dumps(fields.get("datasets", [])),
                json.dumps(fields.get("metrics", [])),
                json.dumps(fields.get("findings", [])),
                json.dumps(fields.get("limitations", [])),
                json.dumps(sources),
                model,
                now,
                now,
            ),
        )
    store.conn.commit()


def get_extraction(store: Store, doc_id: str) -> dict | None:
    """Returns the extraction row as a dict, or None."""
    _ensure_table(store)
    row = store.conn.execute(
        "SELECT * FROM paper_extractions WHERE document_id = ?", (doc_id,)
    ).fetchone()
    if row is None:
        return None
    return {
        "document_id": row["document_id"],
        "task": row["task"],
        "method": row["method"],
        "datasets": json.loads(row["datasets"]),
        "metrics": json.loads(row["metrics"]),
        "findings": json.loads(row["findings"]),
        "limitations": json.loads(row["limitations"]),
        "field_sources": row["field_sources"],
        "model": row["model"],
        "extracted_at": row["extracted_at"],
        "updated_at": row["updated_at"],
    }


def set_extraction_field(store: Store, doc_id: str, field: str, value) -> None:
    """Manually set one extraction field - marks it 'human' so re-runs don't
    overwrite it."""
    if field not in EXTRACTION_FIELDS:
        raise ValueError(f"field must be one of {', '.join(EXTRACTION_FIELDS)}")
    _ensure_table(store)
    existing = get_extraction(store, doc_id)
    sources = json.loads(existing["field_sources"]) if existing else {}
    sources[field] = "human"
    if field in _SCALAR_FIELDS:
        parsed = str(value).strip() if value else None
    else:
        parsed = json.loads(value) if isinstance(value, str) else value
        if not isinstance(parsed, list):
            raise ValueError(f"{field} must be a JSON array")
    _upsert(store, doc_id, {field: parsed}, sources, model=None)


def extraction_status(store: Store) -> list[tuple[Document, str]]:
    """For every paper: (doc, status) where status is 'extracted'/'partial'/'missing'."""
    _ensure_table(store)
    result = []
    for doc in store.list_documents(collection="papers"):
        ext = get_extraction(store, doc.id)
        if ext is None:
            result.append((doc, "missing"))
        elif any(not ext.get(f) for f in ("task", "method")):
            result.append((doc, "partial"))
        else:
            result.append((doc, "extracted"))
    return result
