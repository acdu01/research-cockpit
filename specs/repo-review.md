# Repository review — 2026-10-12

Historical review. See [the October 23 verification report](verification.md) for
current results and subsequent fixes, including the evaluation-metric correction.

The shared core library is a good foundation: SQLite owns the corpus, models are
loaded lazily, and the CLI and Streamlit app reuse the same research operations.
The existing suite covers most feature modules. The biggest weaknesses were
state consistency and integration between otherwise working features.

## Bugs fixed

| Area | Before | Change |
| --- | --- | --- |
| Keyword search | Once initialized, FTS missed newly ingested chunks and retained deleted ones. | SQLite triggers synchronize insert, update, and delete; first use rebuilds legacy indexes. Explicit sync remains idempotent. |
| Search queries | Punctuation in natural-language questions could cause an FTS error that was silently swallowed. | Search treats words as literal terms joined with OR. Unexpected database errors surface. |
| Retrieval filters | Hybrid search ignored lifecycle status. | Both dense and keyword candidates apply the same status filter. |
| Retrieval configuration | `rc search` read retrieval settings, but Ask did not. | CLI and UI Ask pass through retrieval and reranking settings. |
| Reranking | Ordering reflected the reranker, but returned scores still reflected the original ranking. | Results expose reranker scores; model caching is keyed by model name. |
| Ingestion | Embedding failure could leave a document with no chunks; deduplication then blocked a retry. | Embeddings are prepared before persistence; document, chunks, and note tags are stored atomically. Existing DOI stub upgrades are atomic too. |
| Chunk batches | A failed batch insert could be saved partially by a later unrelated commit. | Batch inserts use rollback-capable transactions and validate embedding shape and finite values. |
| Citation graph | SQL NULL semantics defeated the citation uniqueness constraint during repeated refreshes. | Upserts match nullable endpoints explicitly and update existing rows. Historical duplicate rows are retained; future refreshes do not add more identical rows. |
| DOI matching | Different letter casing could create duplicate DOI records. | Lookup and document resolution compare DOIs without case sensitivity. |
| ID prefixes | SQL wildcard characters could resolve an unrelated document; claim attach/move did not resolve the prefixes advertised in help. | Prefix matching is literal and unique; claim show/attach/move share a resolver. |
| Uploaded papers | PDF paths pointed to temporary files; cleanup could make papers unreadable. | Valid uploads are stored in content-addressed directories under `RC_HOME/papers`, with their original filename retained. Readding identical PDFs repairs missing source paths. |
| Chunking | Long section paragraphs exceeded the configured limit; zero overlap could retain the entire prior buffer. | Bounded windows remain within sections; invalid size/overlap settings raise clear errors. |
| LLM JSON parsing | Brackets and braces inside quoted text broke manual delimiter counting. | JSONDecoder handles string escapes and nested data while tolerating surrounding prose/fences. |
| Config persistence | Newlines and tabs could produce invalid TOML. | String serialization escapes control characters. Retrieval defaults also preserve the boolean type of reranking. |
| Watchlists | Overlapping watches created duplicate papers without DOIs. | Existing OpenAlex IDs participate in library deduplication. |
| UI feedback | LLM failures and degraded notices could appear in green success boxes. | Notice messages render as warnings. |
| UI interaction | Answers vanished on Streamlit reruns; changing review counts changed the navigation option itself; duplicate paper titles hid source choices. | Answers retain their original question/scope/filter context; review options have stable values; source choices include IDs. |
| UI styling | Corrupted CSS broke paper texture and navigation group labels. | Repaired the SVG texture and selectors, replaced several corrupted glyphs, respected reduced-motion transitions, and escaped corpus text embedded in HTML. |
| Constellation | The suggestion's label field was ignored by Confirm. | Confirmation saves the entered label. |

## Development improvements

- Tests resolve the `src` tree without an editable installation or manual
  `PYTHONPATH`.
- Added regression coverage for the failures above and a CLI integration test.
- GitHub Actions runs lint and tests on Python 3.11 and 3.13.
- Added standard ignores for virtual environments, bytecode, caches, and build
  artifacts. Existing source files were already untracked at review time; no
  commits or staging changes were made.
- README links are portable, installation creates an isolated environment, and
  offline smoke-run instructions and PDF storage behavior are documented.
- Declared the previously advertised OCR extra.
- Dependency bounds now match APIs used by the code: Streamlit's flexible image
  width landed in 1.49 ([release notes](https://docs.streamlit.io/develop/quick-reference/release-notes/2025));
  NetworkX's `edges` export keyword landed in 3.4
  ([release history](https://github.com/networkx/networkx/releases)).

## Prioritized follow-up work

1. **Persist an embedding model identity and provide a reindex command.**
   Changing `embeddings.model` on an existing library can mix incompatible
   dimensions or semantically incompatible vectors. Both search implementations
   currently assume compatible stored vectors. Record the model and dimensions
   per corpus or embedding generation, and rebuild atomically when changing them.

2. **Make flashcard cache invalidation represent the entire annotation set.**
   `kb.ensure_flashcards` checks every annotation ID but assigns every generated
   card to only the first annotation. With multiple annotations, later visits can
   regenerate unnecessarily. A persisted fingerprint of all source inputs would
   support reliable invalidation, including changes to text and chunks.

3. **Make evaluation metrics honest and distinct.**
   `evals.run_eval` currently reports citation accuracy as a copy of retrieval
   recall and does not compute faithfulness. Treat unmeasured values as absent;
   separately validate generated citation IDs and factual support. Existing
   scores should not be interpreted as measured answer quality.

4. **Unify graph identity when an external paper enters the library.**
   Citation rows retain external endpoint IDs after the corresponding paper is
   added. Relink those endpoints to the internal document so the graph does not
   show the same work twice. Include historical citation-row deduplication in an
   explicit, backup-backed migration.

5. **Finish frontend coverage for advanced modules.**
   OCR and section-aware chunking exist as core helpers but are not integrated
   into normal ingestion. Watchlists, reproducibility, evaluation, and review
   drafts also have limited frontend exposure. Add explicit controls and tests
   as these workflows are made part of the product.

6. **Tighten lifecycle and resource boundaries.**
   The Streamlit file is about 1,400 lines and repeats configuration/resolver and
   input-handling logic. Split page rendering into modules, consistently honor
   ingestion settings, and explicitly close database and HTTP clients. Add
   lockfile-based reproducible installs and test the lowest supported dependency
   versions as well as current releases.

## Verification and limits

The original suite ran **184 passing tests and one failure** after installing the
missing dependencies. The failure was the LLM warning rendered as success.
Running the expanded core regression suite against the original source produced
**21 failures**, confirming that the new cases detect previous behavior.

Final checks: **213 tests passed**, `ruff check src tests` passed, and source/test
compilation passed. Built and installed the wheel in the local virtual
environment, then successfully ran an offline CLI smoke flow: configure hash
embeddings and the local backend, ingest a note, and ask a question with a cited
answer. Temporary smoke data was isolated from the user's library.

Validation uses local/fake adapters and hash embeddings. It covers Streamlit
AppTest page rendering and interactions, PDF extraction/rendering, SQLite
persistence, and core feature tests. Real model downloads, paid LLM requests,
live metadata APIs, OCR system binaries, interactive browser graph rendering,
and the remote GitHub Actions workflow were not exercised. The Python 3.11
matrix is configured in CI; local tests ran on Python 3.13.
