# Design Notes

Cleaned implementation notes for the ambiguous pieces called out in the handoff.

## 1. Structured paper extraction (M9)

### Decision

Use one relational row per paper with fixed columns, not one opaque JSON blob.

### Rationale

- comparison tables need direct field access
- missingness should stay explicit
- human correction should be possible per field
- schema validation is simpler and stricter

### Storage shape

The extraction record is keyed by `document_id` and stores:

- `task`
- `method`
- `datasets` as a JSON array of strings
- `metrics` as a JSON array of objects
- `findings` as a JSON array of strings
- `limitations` as a JSON array of strings
- `field_sources` as JSON, marking each field as `llm` or `human`
- `model`
- timestamps

### Policy

- LLM extraction writes fields as `llm`
- manual edits mark fields as `human`
- reruns only overwrite empty or LLM-sourced fields
- `--force` explicitly allows overwrite of human-edited fields

This matches the behavior in [`src/research_cockpit/extract.py`](../src/research_cockpit/extract.py).

## 2. Constellation edge model (M19)

### Decision

Use two relations with different semantics:

1. `note_links` for note-to-note graph topology
2. `note_sources` for note provenance back to papers or passages

### Why not one polymorphic edge table

- topology and provenance are different concepts
- note-to-note links are undirected graph edges
- provenance links are document anchors
- lifecycle and rendering rules differ

### `note_links`

- canonical undirected pairs
- persisted statuses such as confirmed or dismissed
- optional free-text label
- suggestions are computed at view time, not stored as durable graph edges

### `note_sources`

- exact provenance rows
- note -> document
- optional chunk id
- optional page
- verbatim quote snapshot

This keeps provenance stable even if chunking changes later.

This matches the behavior in [`src/research_cockpit/constellation.py`](../src/research_cockpit/constellation.py).

## 3. Metadata backfill safety (M8)

### Decision

Backfill only fills missing fields and never overwrites populated values.

### Rationale

- user edits must survive future re-resolution
- API disagreement should not silently replace curated records
- repeated backfill should be idempotent

Implementation reference:

- [`src/research_cockpit/meta.py`](../src/research_cockpit/meta.py)

## 4. Frontend design rule

The CLI and Streamlit UI are intentionally thin. Core behavior should live in reusable modules and be shared between frontends.

Implementation references:

- CLI: [`src/research_cockpit/cli.py`](../src/research_cockpit/cli.py)
- UI: [`src/research_cockpit/ui/app.py`](../src/research_cockpit/ui/app.py)
