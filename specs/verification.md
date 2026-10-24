# Verification report — 2026-10-23

## Verdict

The offline core and installed UI work in the tested environment. This is suitable
for a **GitHub preview**, with the limitations below clearly disclosed. It is not
a claim that every handoff milestone is fully integrated or that live services
have been validated.

Reviewed the 188-page handoff's architecture, invariants, feature descriptions,
and implementation/test inventory against the reconstructed source and the prior
[October 12 review](repo-review.md). The PDF contains historical source, so the
current implementation and this report take precedence where they differ.

## Checks performed

Local environment: Linux, Python 3.13.11. The existing `.venv` inherits system
site-packages; this was not a clean dependency-resolution test. CI is configured
for fresh installs on Python 3.11 and 3.13 but has not run remotely yet.

| Check | Result |
| --- | --- |
| Existing pytest suite before changes | 213 passed |
| Expanded suite after fixes | 219 passed, no skips |
| Ruff on `src`, `tests`, and `tools/smoke.py` | Passed |
| `pip check` | No broken requirements |
| Source/test compilation | Passed |
| Source distribution and wheel build | Passed with `python -m build --no-isolation` |
| Wheel installation | Passed; app imported from site-packages |
| Installed-package CLI smoke | Passed outside the source directory with temporary `RC_HOME` |
| Live `rc ui` server | HTTP health endpoint returned `ok` on loopback |
| Chromium browser interaction | Cited answer rendered; all nine pages opened; no JavaScript errors |
| Visual inspection | Ask page inspected; primary-button contrast repaired |

The full suite covers storage/migrations, PDF extraction and Reader rendering,
ingestion and deduplication, DOI/API adapters with mocks, dense/hybrid retrieval,
RAG and LLM fallbacks, lifecycle and review scheduling, metadata, bibliography,
projects, claims, extraction, graphs, notes provenance, saved questions,
watchlists, review tables, reproducibility records, OCR helpers, evaluation, CLI,
and Streamlit page rendering/interactions.

`tools/smoke.py` additionally drives real CLI subprocesses through PDF and note
ingestion, deduplication, dense/hybrid searches, cited answers and synthesis,
project filtering, paper status, annotations, claims, four citation styles, and
GraphML/DOT/JSON export. It uses generated PDFs, hash embeddings, and the local
heuristic answer backend; it never touches the user's library.

The browser check used a generated two-page paper and a throwaway library. It
verified a real WebSocket-backed Streamlit session, then opened Ask, Library,
Reader, Review, Graph, Citations, Constellation, Claims, and Questions. It did not
validate every button, populated graph interaction, or mobile layout.

## Changes made during this audit

- `run_eval` now returns/persists citation accuracy and faithfulness as unmeasured
  (`None`/SQL NULL). It previously copied retrieval recall into citation accuracy.
  Historical evaluation records are unchanged and may contain the old proxy score.
- `rc add` now returns a failing exit code for invalid references, directories, and
  DOI input combined with `--no-resolve`. It still processes valid files in a mixed
  batch, and invalid inputs do not trigger an embedding-model download.
- Local PDFs with no extractable text now produce an OCR-specific explanation,
  instead of incorrectly saying that no open-access PDF was found.
- Fixed the primary Ask button's dark label on a dark background. Verified the
  computed label color in Chromium after installing the rebuilt wheel.
- Rewrote the README around working workflows, an isolated offline demo, storage
  behavior, backend configuration, development commands, and known limitations.
- Added README package metadata and an explicit source-distribution file list.
- Added the installed-package smoke script and expanded CI to build/install/test
  the wheel. CI now has read-only repository permissions and a job timeout.
- Expanded ignores for local databases and configuration secrets, repaired local
  documentation links, and cleaned the garbled artwork inventory.

## Remaining issues and handoff gaps

| Area | Finding / practical implication |
| --- | --- |
| Embedding changes | Reproduced a search `ValueError` after ingesting 128-dimensional vectors and querying with 256 dimensions. Model identity is not stored, so same-dimension model changes can silently invalidate similarity too. Keep one model per library; use a separate `RC_HOME` for experiments. Reindexing remains future work. |
| Flashcard cache | Reproduced two adapter calls on two unchanged visits with two annotations. Cards reference only the first annotation, so the cache incorrectly treats the annotation set as changed. A fingerprint of all generation inputs is still needed. |
| Citation quality | Prompts request citations and returned sources map to retrieved passages, but generated text is not checked for invented markers or factual support. Retrieval recall is the only measured evaluation metric. |
| OCR and sections | Core helpers exist and have tests; normal PDF ingestion does not invoke them. Run OCR before ingestion. |
| Advanced workflows | Watchlists, reproducibility, evaluations, and review drafts lack complete CLI/UI exposure. Their core tests do not establish a finished user workflow. |
| UI configuration | DOI/note ingestion paths still use default chunk sizes; metadata clients are not configured consistently with the CLI. |
| Graph identity | External endpoints are not automatically reconciled when a cited paper is later added to the local library. |
| Assets | Referenced artwork, custom font binaries, and favicon are absent. The app falls back to system fonts/vector ornaments and omits missing plates. |
| Packaging | No dependency lockfile or lowest-supported-version matrix. Local tests use the installed dependency set. No project license has been selected. |
| Secrets invariant | Generation API keys come from the environment, but the legacy Semantic Scholar key setting can be saved in config. The handoff's universal “secrets never persisted” claim is too broad. |

## Not exercised

- Real sentence-transformer or cross-encoder downloads/inference; tests use hash
  vectors and mocked rerankers.
- Authenticated Claude/Codex/API generation, provider model availability, billing,
  or live metadata/open-access download services.
- Real OCRmyPDF/Tesseract execution (system binaries are absent); subprocess
  invocation and missing-dependency behavior are tested with mocks.
- Every interactive graph action, screen-reader behavior, or mobile viewport.
- Remote GitHub Actions, a clean Python 3.11 environment, or a public deployment.

The inherited Claude model identifier should be configured to one available to
your account before relying on remote generation. The app's fallback warning is
not evidence that the primary backend works.

## Reproduce

Use the commands in [the README](../README.md#development-and-verification) and
[GitHub preparation guide](github-release.md). No commits, remote changes, or
uploads were made during this work.
