# Research Cockpit Build Spec

This document is the cleaned source-form specification reconstructed from the handoff and aligned to the code in `src/research_cockpit/`.

This is an architectural inventory, not a release-completeness guarantee. Some
milestones are core-library helpers without full frontend integration. Consult
[the current verification report](verification.md) for tested behavior and gaps.

## Product summary

Research Cockpit is a personal, local-first research environment with one shared core library and two frontends:

- a Typer CLI exposed as `rc`
- a Streamlit UI exposed through `rc ui`

The system unifies:

1. RAG over papers and notes
2. A literature knowledge base
3. Graph-based exploration of papers and notes

## Invariants

- Local-first by default
  Embeddings, OCR, chunking, retrieval, rerank wiring, and storage are local.
- Loopback-only UI
  The UI binds to `127.0.0.1` only.
- Generation secrets are environment-derived
  LLM API keys are not persisted in config. The legacy Semantic Scholar key setting
  is an exception and can be saved in config; treat that file as private.
- Thin frontends
  CLI and UI should stay thin wrappers around the core library.
- Additive migrations only
  Legacy SQLite databases must keep opening cleanly.
- Tests are intended to run offline
  Especially for fallback paths and storage logic.

## Architecture

### Storage

- SQLite is the system of record
- Documents are the central entity
- Chunks store page-aware extracted text plus float32 embedding blobs
- Feature-specific tables extend the document model without replacing it

### Retrieval

- Dense cosine retrieval is the baseline
- Optional hybrid retrieval adds FTS5 keyword search
- Reciprocal-rank fusion merges dense and lexical hits
- Optional reranking can refine the fused top-N

### Ingestion

- PDF ingestion extracts text with PyMuPDF
- DOI ingestion resolves metadata and may fetch an open-access PDF
- Notes are ingested separately from papers
- Dedupe is content-hash based for files and DOI-based where available

### Generation

- LLM access is pluggable via backend adapters
- Local fallback exists for degraded operation
- Structured outputs use strict JSON validation where applicable

## Shipped milestones

### M0: Store and ingest

- SQLite schema for documents, chunks, annotations, tags, projects, citations, and review schedule
- PDF extraction and sliding-window chunking
- Local embedding support
- Brute-force cosine search

### M1: Ask-My-Library

- `rc search`
- `rc ask`
- cited answers with numbered sources
- synthesize and gaps modes

### M2: Knowledge base

- paper lifecycle
- annotations
- tags
- LLM-generated study annotations

### M3: Spaced repetition

- due scheduling
- SM-2-lite review updates
- flashcard generation

### M4: BibTeX and citation styles

- BibTeX import
- BibTeX export
- APA / MLA / Chicago / BibTeX rendering

### M5: Citation graph

- edge fetch from OpenAlex with Semantic Scholar fallback
- cluster detection
- high-centrality gap suggestions
- GraphML / DOT / JSON export

### M6: DOI ingestion and projects

- DOI and `doi.org` ingestion
- OA PDF discovery and download
- project assignment and filtering

### M7: UI and LLM hardening

- multi-page Streamlit UI
- explicit degraded-mode messaging
- loopback-only launch

### M8: Full citation metadata

- extended document citation fields:
  `item_type`, `publication_date`, `volume`, `issue`, `pages`, `publisher`, `url`, `abstract`, `issn`, `isbn`
- no-overwrite backfill behavior
- metadata completeness inspection

### M9: Structured paper extraction

- extraction table for task, method, datasets, metrics, findings, limitations
- validated strict JSON parsing
- human-overrides survive reruns unless forced

### M10: Claim-to-evidence workspace

- project claims
- attached evidence passages
- persistent quote snapshots

### M11: Hybrid retrieval and rerank

- FTS5 index over chunks
- reciprocal-rank fusion
- optional reranker integration

### M12: Section-aware chunking

- heading detection from PDF layout
- section-aware chunk packing
- fallback to simple chunking when needed

### M13: OCR for scanned PDFs

- scanned PDF detection
- local OCR pipeline
- graceful missing-binary behavior

### M14: Literature review builder

- comparison tables
- markdown / LaTeX rendering
- cited draft generation

### M15: Saved research questions

- persistent question threads
- associated items and notes

### M16: New-paper watchlists

- watchlists by author, topic, or DOI
- polling workflow
- to-read record creation for new hits

### M17: Reproducibility tracking

- code availability
- data availability
- benchmark settings
- replication status and notes

### M18: Retrieval evaluation harness

- gold question set
- retrieval recall
- citation accuracy and faithfulness columns reserved, returned as unmeasured

### M19: Constellation notes graph

- note-to-note links
- suggestion workflow
- note provenance links back to documents and passages

## Cross-cutting rules

- Favor explicit degraded behavior over silent failure
- Preserve user edits over regenerated fields
- Keep feature logic in dedicated modules
- Keep all persistent state in SQLite-backed tables

## Source of truth

At this point the implementation is the most reliable source of truth:

- CLI surface: [`src/research_cockpit/cli.py`](../src/research_cockpit/cli.py)
- data model and migrations: [`src/research_cockpit/store.py`](../src/research_cockpit/store.py)
- UI entrypoint: [`src/research_cockpit/ui/app.py`](../src/research_cockpit/ui/app.py)
