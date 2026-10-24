"""Research Cockpit - localhost Streamlit UI ("light academia").

Thin frontend over the core library: no direct SQL, no model calls here.
Launched via `rc ui`, which binds 127.0.0.1 only.

Layout follows the NN/g usability heuristics: status is always visible
(sidebar stats, review-due badge, fallback-LLM warnings), options are
recognized rather than recalled (tag/project pickers built from what exists),
advanced filters are progressively disclosed, and every empty state says
what belongs there and how to fill it.
"""

from __future__ import annotations

import base64
from datetime import date
from functools import lru_cache
from html import escape
from pathlib import Path

import streamlit as st

from research_cockpit import bib, kb, rag
from research_cockpit.config import Config
from research_cockpit.store import STATUSES, Store
from research_cockpit.ui import ornaments

ASSETS = Path(__file__).parent / "assets"
_FAVICON = ASSETS / "favicon.png"

st.set_page_config(
    page_title="Research Cockpit",
    page_icon=str(_FAVICON) if _FAVICON.exists() else "📚",
    layout="wide",
)


@lru_cache(maxsize=1)
def _font_css() -> str:
    """@font-face rules for the bundled OFL-licensed woff2 files (latin
    subsets), base64-inlined: self-hosted, so rendering the UI never phones
    fonts.googleapis.com - and no flash of Georgia before the serif loads."""
    faces = [
        ("EB Garamond", "normal", "400", "eb-garamond-400.woff2"),
        ("EB Garamond", "italic", "400", "eb-garamond-400-italic.woff2"),
        # single variable file covers both heading weights
        ("Cormorant Garamond", "normal", "500 600",
         "cormorant-garamond-500-600.woff2"),
        ("JetBrains Mono", "normal", "400", "jetbrains-mono-400.woff2"),
    ]
    rules = []
    for family, style, weight, filename in faces:
        path = ASSETS / "fonts" / filename
        if not path.exists():  # fall back to the stacks' Georgia/monospace
            continue
        encoded = base64.b64encode(path.read_bytes()).decode()
        rules.append(
            f"@font-face {{ font-family: '{family}'; font-style: {style};"
            f" font-weight: {weight}; font-display: swap;"
            f" src: url(data:font/woff2;base64,{encoded}) format('woff2'); }}"
        )
    return "\n".join(rules)


# ------------------------------------------------------- light academia CSS
# Palette per spec §10.1 - accents verified ≥4.5:1 on cream (#4A5D45 ≈ 6.4:1,
# #7B3F3A ≈ 6.8:1, ink #2E2A24 ≈ 12:1).
CSS = """
<style>
html, body, [class*="css"], .stMarkdown, p, li {
  font-family: 'EB Garamond', Georgia, serif;
  color: #2E2A24;
  font-size: 1.05rem;
}
h1, h2, h3 {
  font-family: 'Cormorant Garamond', Georgia, serif !important;
  color: #2E2A24;
  letter-spacing: 0.01em;
}
.stApp { background-color: #F5F1E8; }
section[data-testid="stSidebar"] {
  background-color: #FBF8F1;
  border-right: 1px solid #D8CFBE;
}
div[data-testid="stVerticalBlockBorderWrapper"] > div {
  border-radius: 6px;
}
.stButton > button, .stDownloadButton > button,
div[data-testid="stFormSubmitButton"] button {
  background: #FBF8F1;
  color: #4A5D45;
  border: 1px solid #D8CFBE;
  border-radius: 6px;
  font-family: 'EB Garamond', Georgia, serif;
}
.stButton > button:hover, div[data-testid="stFormSubmitButton"] button:hover {
  border-color: #4A5D45; color: #3A4A36;
}
.stButton button[kind="primary"] {
  background: #4A5D45;
  border-color: #4A5D45;
  color: #FBF8F1;
}
.stButton button[kind="primary"] p { color: #FBF8F1; }
.stButton button[kind="primary"]:hover { background: #3A4A36; }
a, .stMarkdown a { color: #4A5D45; }
code, pre, .stCode {
  font-family: 'JetBrains Mono', monospace !important;
  font-size: 0.85rem;
}
div[data-testid="stExpander"] {
  background: #FBF8F1;
  border: 1px solid #D8CFBE;
  border-radius: 6px;
}
.rc-source {
  background: #E8DCC4;
  border-radius: 4px;
  padding: 0.15rem 0.45rem;
  margin: 0.1rem 0;
  display: inline-block;
  font-family: 'JetBrains Mono', monospace;
  font-size: 0.8rem;
  color: #2E2A24;
}
.rc-muted { color: #5C5346; font-style: italic; }

/* --- paper grain (SVG fractal noise, barely-there) ------------------- */
.stApp {
  background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='240' height='240'%3E%3Cfilter id='n'%3E%3CfeTurbulence type='fractalNoise' baseFrequency='0.8' numOctaves='2' stitchTiles='stitch'/%3E%3CfeColorMatrix values='0 0 0 0 0.36 0 0 0 0 0.32 0 0 0 0 0.27 0 0 0 0.04 0'/%3E%3C/filter%3E%3Crect width='240' height='240' filter='url(%23n)'/%3E%3C/svg%3E");
}

/* --- entrance motion (gentle rise-and-fade) -------------------------- */
@keyframes rc-rise {
  from { opacity: 0; transform: translateY(10px); }
  to   { opacity: 1; transform: none; }
}
.block-container { animation: rc-rise .7s cubic-bezier(.2,.7,.3,1) both; }
section[data-testid="stSidebar"] > div { animation: rc-rise .7s ease both; }

/* --- sidebar hero ----------------------------------------------------- */
.rc-hero { text-align: center; padding: .6rem 0 .9rem; }
.rc-hero-temple svg { width: 82%; height: auto; opacity: .92; }
.rc-hero-title {
  font-family: 'Cormorant Garamond', Georgia, serif;
  font-size: 1.55rem; font-weight: 600; letter-spacing: .06em;
  color: #2E2A24; margin-top: .4rem;
}
.rc-hero-tagline {
  font-family: 'EB Garamond', Georgia, serif; font-style: italic;
  color: #5C5346; font-size: .95rem;
}
.rc-stats {
  text-align: center; font-variant: small-caps; letter-spacing: .12em;
  color: #5C5346; font-size: .9rem; margin-top: .4rem;
}

/* --- page headers: emblem, kicker, laurel rule ------------------------ */
.rc-page-head { display: flex; align-items: center; gap: 1.2rem; margin-top: .3rem; }
.rc-emblem svg { width: 78px; height: auto; opacity: .85; }
.rc-kicker {
  font-variant: small-caps; letter-spacing: .32em;
  color: #5C5346; font-size: .95rem;
}
.rc-h1 {
  font-family: 'Cormorant Garamond', Georgia, serif !important;
  font-size: 2.7rem; font-weight: 600; margin: 0; line-height: 1.08;
  color: #2E2A24;
}
.rc-laurel { text-align: center; margin: .7rem 0 1.3rem; }
.rc-laurel svg { width: 250px; height: 30px; opacity: .9; }

/* --- corner watermark (fixed, faint, decorative only) ----------------- */
.rc-watermark {
  position: fixed; right: 2.2rem; bottom: 1.6rem; width: 190px;
  opacity: .07; pointer-events: none; z-index: 0;
}
.rc-watermark svg { width: 100%; height: auto; }

/* --- hover: quiet shadow only (no lift - stillness suits the theme) --- */
div[data-testid="stVerticalBlockBorderWrapper"] {
  transition: box-shadow .25s ease;
}
div[data-testid="stVerticalBlockBorderWrapper"]:hover {
  box-shadow: 0 6px 18px rgba(46, 42, 36, .09);
}
div[data-testid="stExpander"] { transition: box-shadow .25s ease; }
div[data-testid="stExpander"]:hover { box-shadow: 0 6px 18px rgba(46, 42, 36, .08); }
.stButton > button, .stDownloadButton > button { transition: all .22s ease; }
.stButton > button:hover, .stDownloadButton > button:hover {
  box-shadow: 0 3px 10px rgba(74, 93, 69, .18);
}

/* --- alerts in parchment, tinted by kind (status must stay legible) ---- */
div[data-testid="stAlert"],
div[data-testid="stAlertContainer"] {
  background: #EDE6D6;
  border: 1px solid #D8CFBE;
  border-left: 3px solid #D8CFBE;
  border-radius: 6px;
  color: #2E2A24;
}
div[data-testid="stAlertContainer"]:has([data-testid="stAlertContentSuccess"]) {
  background: #E7EDE0; border-left-color: #4A5D45;
}
div[data-testid="stAlertContainer"]:has([data-testid="stAlertContentWarning"]),
div[data-testid="stAlertContainer"]:has([data-testid="stAlertContentError"]) {
  background: #F0E2D9; border-left-color: #7B3F3A;
}
div[data-testid="stAlert"] p,
div[data-testid="stAlertContainer"] p { color: #2E2A24; }

/* --- sidebar nav as small-caps entries, in titled groups --------------- */
section[data-testid="stSidebar"] label[data-testid="stRadioOption"] p {
  font-variant: small-caps; letter-spacing: .14em; font-size: 1.05rem !important;
  transition: color .2s ease, letter-spacing .25s ease;
}
section[data-testid="stSidebar"] label[data-testid="stRadioOption"]:hover p {
  color: #4A5D45; letter-spacing: .2em;
}
section[data-testid="stSidebar"] div[role="radiogroup"] > label {
  position: relative;
}
section[data-testid="stSidebar"] div[role="radiogroup"] > label:nth-of-type(1),
section[data-testid="stSidebar"] div[role="radiogroup"] > label:nth-of-type(4),
section[data-testid="stSidebar"] div[role="radiogroup"] > label:nth-of-type(6),
section[data-testid="stSidebar"] div[role="radiogroup"] > label:nth-of-type(8) {
  margin-top: 1.15rem;
}
section[data-testid="stSidebar"] div[role="radiogroup"] > label::before {
  position: absolute; top: -1.05rem; left: 0;
  font-variant: small-caps; letter-spacing: .24em;
  font-size: .72rem; color: #8A7F6D;
}
section[data-testid="stSidebar"] div[role="radiogroup"] > label:nth-of-type(1)::before { content: "study"; }
section[data-testid="stSidebar"] div[role="radiogroup"] > label:nth-of-type(4)::before { content: "collection"; }
section[data-testid="stSidebar"] div[role="radiogroup"] > label:nth-of-type(6)::before { content: "charts"; }
section[data-testid="stSidebar"] div[role="radiogroup"] > label:nth-of-type(8)::before { content: "projects"; }

/* --- lowercase display titles; small caps for widget chrome ------------ */
/* lowercase only our own display copy (titles never contain acronyms); */
.rc-h1, .rc-hero-title,
section[data-testid="stSidebar"] label[data-testid="stRadioOption"] p {
  text-transform: lowercase;
}
/* chrome that can contain acronyms (DOI, PDF, BibTeX) gets true small
   caps instead - "by doi" reads as a typo, small caps read as typesetting */
.stButton > button p, .stDownloadButton > button p,
div[data-testid="stFormSubmitButton"] button p,
label[data-testid="stWidgetLabel"] p,
button[data-baseweb="tab"] p {
  font-variant-caps: all-small-caps; letter-spacing: .05em;
}

/* --- empty states: a large, still, faint emblem ------------------------ */
.rc-empty { text-align: center; margin: 1.4rem 0 .3rem; opacity: .5; }
.rc-empty svg { width: 170px; height: auto; }

/* --- engraving plates (Review rest state) ------------------------------ */
div[data-testid="stImageContainer"] img { border-radius: 4px; }

/* --- respect reduced-motion for the emblem animations ------------------ */
@media (prefers-reduced-motion: reduce) {
  svg *, .block-container, section[data-testid="stSidebar"] > div {
    animation: none !important;
  }
  *, *::before, *::after { transition: none !important; }
}
</style>
"""
st.markdown(f"<style>{_font_css()}</style>", unsafe_allow_html=True)
st.markdown(CSS, unsafe_allow_html=True)


@st.cache_resource
def get_config() -> Config:
    return Config.load()


def get_store() -> Store:
    # Streamlit reruns the script in fresh threads; a cached sqlite3 connection
    # will then trip check_same_thread. Keep Store per-run, not shared.
    return Store(get_config().store_path)


@st.cache_resource
def get_embedder():
    from research_cockpit.embed import get_embedder as make

    return make(get_config().get("embeddings.model"))


@st.cache_resource
def get_adapter():
    from research_cockpit.llm import get_adapter as make

    return make(get_config())


# ------------------------------------------------------------------- helpers


def doc_label(doc) -> str:
    year = f" ({doc.year})" if doc.year else ""
    return f"{doc.title or 'Untitled'}{year}"


def plural(n: int, word: str, plural_form: str | None = None) -> str:
    return f"{n} {word if n == 1 else (plural_form or word + 's')}"


def flash(message: str) -> None:
    """Queue a message that survives st.rerun(); shown at the next render."""
    st.session_state["rc-flash"] = message


def show_flash() -> None:
    message = st.session_state.pop("rc-flash", None)
    if not message:
        return
    # NB: keep these as plain statements - a ternary expression-statement here
    # gets auto-written by Streamlit "magic" and dumps a DeltaGenerator help
    # blob into the page right under the flash message.
    if message.startswith(("? ", "Notice:")):
        st.warning(message)
    else:
        st.success(message)


def llm_notice() -> str | None:
    from research_cockpit.llm import degraded_notice

    return degraded_notice(get_adapter())


def pick_filter(container, label: str, options: list[str], key: str) -> str | None:
    choice = container.selectbox(label, ["(any)", *options], key=key)
    return None if choice == "(any)" else choice


def tag_filter(store, container, key: str) -> str | None:
    return pick_filter(container, "Tag", store.all_tags(), key)


def project_filter(store, container, key: str) -> str | None:
    return pick_filter(container, "Project", project_names(store), key)


def project_names(store) -> list[str]:
    return [row["name"] for row in store.list_projects()]


def sync_terms(chosen: list[str], current: list[str], add, remove) -> bool:
    """Apply a multiselect diff (normalized like the store does) and report
    whether anything changed - comparison must normalize, or a widget holding
    'Foo' vs the stored 'foo' would rerun forever."""
    chosen_set = {t.strip().lower() for t in chosen if t.strip()}
    current_set = {t.strip().lower() for t in current}
    for term in chosen_set - current_set:
        add(term)
    for term in current_set - chosen_set:
        remove(term)
    return chosen_set != current_set


def annotation_rows(store, doc, jump_key: str | None = None) -> None:
    """Annotations with (ai)/page badges, a delete button each, and - when
    jump_key names the Reader's page-state key - a jump-to-folio button."""
    rows = store.annotations(doc.id)
    for row in rows:
        cols = st.columns([5, 1, 1] if jump_key else [6, 1])
        badge = " *(ai)*" if row["source"] == "llm" else ""
        page_badge = f" - p.{row['page']}" if row["page"] else ""
        cols[0].markdown(f"> {escape(row['text'])}{badge}"
                         f'<span class="rc-muted">{page_badge}</span>',
                         unsafe_allow_html=True)
        if (jump_key and row["page"]
                and cols[1].button("→", key=f"annjump-{row['id']}",
                                   help=f"Open folio {row['page']}")):
            st.session_state[jump_key] = row["page"]
        if cols[-1].button("Х", key=f"anndel-{row['id']}",
                           help="Delete this annotation"):
            store.delete_annotation(row["id"])
            flash("Annotation deleted.")
            st.rerun()


def run_enrichment(spinner_text: str, action, describe) -> None:
    """Run an LLM enrichment behind a spinner; a failure becomes a flash
    message instead of a traceback painted into the page."""
    from research_cockpit.llm import LLMError

    try:
        with st.spinner(spinner_text):
            result = action()
    except LLMError as exc:
        flash(f"Notice: {exc}")
    else:
        notice = llm_notice()
        flash(f"Notice: {notice}" if notice else describe(result))
    st.rerun()


@st.cache_data(show_spinner=False)
def _pdf_page_png(path: str, page_no: int, mtime: float, highlight: str | None) -> bytes:
    from research_cockpit.ingest import render_pdf_page

    return render_pdf_page(Path(path), page_no, highlight=highlight)


# -------------------------------------------------------------------- sidebar

store = get_store()
n_papers = len(store.list_documents(collection="papers"))
n_notes = len(store.list_documents(collection="notes"))
n_due = len(store.due_documents())

st.sidebar.markdown(ornaments.sidebar_hero(), unsafe_allow_html=True)
# order matches the CSS nav groups: study / collection / charts / projects
picked_page = st.sidebar.radio(
    "Pages", ["Ask", "Reader", "Review", "Library", "Citations",
              "Graph", "Constellation", "Claims", "Questions"],
    format_func=lambda name: f"Review · {n_due} due" if name == "Review" and n_due else name,
    label_visibility="collapsed",
)
page = "Review" if picked_page.startswith("Review") else picked_page
st.sidebar.markdown(f'<div class="rc-laurel">{ornaments.LAUREL}</div>',
                    unsafe_allow_html=True)
st.sidebar.markdown(
    f'<div class="rc-stats">{plural(n_papers, "paper")} · {plural(n_notes, "note")}'
    f" · {n_due} due for review</div>",
    unsafe_allow_html=True,
)

# ----------------------------------------------------------------------- Ask

if page == "Ask":
    st.markdown(ornaments.page_header("Ask", "Ask your library"), unsafe_allow_html=True)
    st.markdown(ornaments.watermark("Ask"), unsafe_allow_html=True)
    show_flash()
    if n_papers + n_notes == 0:
        st.markdown(ornaments.empty_state("Ask"), unsafe_allow_html=True)
        st.info(
            "The library is empty, so there is nothing to ask yet. Head to the"
            " **Library** page to add a paper (upload a PDF or paste a DOI) or"
            " jot a note - then come back and ask away."
        )
        st.stop()
    question = st.text_area(
        "Question",
        placeholder="e.g. What storage conditions do my papers recommend?",
    )
    mode_label = st.radio(
        "Mode", ["ask", "synthesize", "gaps"], horizontal=True,
        captions=["direct answer, cited [n]",
                  "compare sources, flag contradictions",
                  "what the corpus does NOT cover"],
    )
    with st.expander("filters - scope, tag, status, project"):
        col1, col2, col3, col4 = st.columns(4)
        scope = col1.selectbox("Scope", ["papers", "notes", "all"])
        tag = tag_filter(store, col2, "ask-tag")
        status = pick_filter(col3, "Status", list(STATUSES), "ask-status")
        project = project_filter(store, col4, "ask-project")
    active = [f"{name}: {value}" for name, value in
              (("tag", tag), ("status", status), ("project", project)) if value]
    if active:
        st.caption("Search filters - " + " · ".join(active))
    if st.button("Ask", type="primary", disabled=not question.strip()):
        st.session_state.pop("rc-last-answer", None)
        gap_candidates = None
        if mode_label == "gaps":
            from research_cockpit.graph import gaps as graph_gaps

            gap_candidates = [s.title for s in graph_gaps(store, limit=10)] or None
        with st.spinner(f"Searching {n_papers} papers and generating..."):
            try:
                answer = rag.ask(
                    store, get_embedder(), get_adapter(), question.strip(),
                    scope=scope, tag=tag, status=status, project=project,
                    k=int(get_config().get("rag.top_k", 8)),
                    mode=mode_label, gap_candidates=gap_candidates,
                    retrieval=get_config().get("rag.retrieval", "dense"),
                    do_rerank=get_config().get_bool("rag.rerank"),
                )
            except Exception as exc:  # surface LLM/config errors readably
                st.error(str(exc))
                st.stop()
        st.session_state["rc-last-answer"] = {
            "answer": answer, "question": question.strip(), "notice": llm_notice(),
            "scope": scope, "filters": active,
        }
    previous = st.session_state.get("rc-last-answer")
    if previous:
        answer = previous["answer"]
        notice = previous["notice"]
        st.caption(f"Answer to: {previous['question']} · scope: {previous['scope']}"
                   + (" · " + " · ".join(previous["filters"]) if previous["filters"] else ""))
        if notice:
            st.warning(f"Notice: {notice}")
        st.markdown(answer.text)
        if answer.sources:
            st.subheader("sources")
            for s in answer.sources:
                page_str = f", p.{s.page}" if s.page else ""
                st.markdown(
                    f'<span class="rc-source">[{s.n}]</span> {escape(s.title)}{page_str}'
                    f' <span class="rc-muted">({s.document_id[:8]})</span>',
                    unsafe_allow_html=True,
                )
        elif previous["filters"]:
            st.caption("No sources matched - try clearing the filters above"
                       " to search everything.")

# ------------------------------------------------------------------- Library

elif page == "Library":
    st.markdown(ornaments.page_header("Library", "The library"), unsafe_allow_html=True)
    st.markdown(ornaments.watermark("Library"), unsafe_allow_html=True)
    show_flash()

    with st.expander("Add to the library"):
        tab_doi, tab_pdf, tab_note = st.tabs(["By DOI", "Upload a PDF", "New note"])
        with tab_doi:
            doi_ref = st.text_input(
                "DOI or doi.org link",
                placeholder="10.48550/arXiv.1706.03762 or https://doi.org/...",
                help="Resolves metadata and downloads the open-access PDF when one exists.",
            )
            if st.button("Fetch by DOI") and doi_ref.strip():
                from research_cockpit.apis import MetadataResolver
                from research_cockpit.config import rc_home
                from research_cockpit.ingest import ingest_doi

                try:
                    with st.spinner("Resolving DOI and searching for an open-access PDF..."):
                        result = ingest_doi(store, get_embedder(), doi_ref.strip(),
                                            MetadataResolver(), pdf_dir=rc_home() / "papers")
                except ValueError as exc:
                    st.error(str(exc))
                else:
                    if result.deduped:
                        st.info(f"Already in library: {result.document.title}")
                    elif result.chunks == 0:
                        st.warning(f"No open-access PDF found for {result.document.title};"
                                   " added a metadata-only to-read record.")
                    else:
                        st.success(f"Downloaded and ingested {result.document.title}"
                                   f" - {result.chunks} chunks")
        with tab_pdf:
            uploaded = st.file_uploader("Paper PDF", type=["pdf"])
            if uploaded and st.button("Ingest PDF"):
                from research_cockpit.apis import MetadataResolver
                from research_cockpit.config import rc_home
                from research_cockpit.ingest import ingest_uploaded_pdf

                try:
                    with st.spinner("Extracting, resolving, embedding..."):
                        cfg = get_config()
                        result = ingest_uploaded_pdf(
                            store, get_embedder(), uploaded.getvalue(), uploaded.name,
                            pdf_dir=rc_home() / "papers", resolver=MetadataResolver(),
                            chunk_tokens=cfg.get("rag.chunk_tokens", 512),
                            chunk_overlap=cfg.get("rag.chunk_overlap", 64),
                        )
                except Exception as exc:
                    st.error(f"Could not ingest this PDF: {exc}")
                else:
                    verb = "Already in library" if result.deduped else "Added"
                    flash(f"{verb}: {result.document.title} - {result.chunks} chunks")
                    st.rerun()
        with tab_note:
            note_title = st.text_input("Note title")
            note_text = st.text_area("Note text")
            if st.button("Add note") and note_text.strip():
                from research_cockpit.ingest import ingest_note

                result = ingest_note(store, get_embedder(), note_text,
                                     note_title or "Untitled note")
                st.success(f"Added note: {result.document.title}")

    with st.expander("projects"):
        new_project = st.text_input("New project name")
        if st.button("Create project") and new_project.strip():
            store.create_project(new_project)
            st.rerun()
        rows = store.list_projects()
        if not rows:
            st.caption("No projects yet - create one to group papers"
                       " (e.g. a thesis chapter or a survey).")
        for row in rows:
            st.markdown(f"**{row['name']}** - {plural(row['documents'], 'document')}")

    find_col, tag_col, project_col = st.columns([2, 1, 1])
    lib_query = find_col.text_input(
        "Find a paper", placeholder="search by title or author...",
        help="Filters the board below as you type.",
    )
    lib_tag = tag_filter(store, tag_col, "library-tag")
    lib_project = project_filter(store, project_col, "library-project")

    def _matches(doc) -> bool:
        needle = lib_query.strip().lower()
        if not needle:
            return True
        hay = f"{doc.title or ''} {' '.join(doc.authors)}".lower()
        return needle in hay

    tab_papers, tab_notes = st.tabs(["Papers", "Notes"])
    with tab_papers:
        by_status = {
            status_name: [
                doc for doc in store.list_documents(
                    collection="papers", status=status_name,
                    tag=lib_tag, project=lib_project)
                if _matches(doc)
            ]
            for status_name in STATUSES
        }
        shown = sum(len(docs) for docs in by_status.values())
        if n_papers == 0:
            st.markdown(ornaments.empty_state("Library"), unsafe_allow_html=True)
            st.info("No papers yet - open **Add to the library** above to"
                    " upload a PDF or fetch one by DOI.")
        elif lib_query.strip() or lib_tag or lib_project:
            st.caption(f"{shown} of {n_papers} papers shown")
        columns = st.columns(len(STATUSES))
        for col, status_name in zip(columns, STATUSES, strict=True):
            with col:
                docs = by_status[status_name]
                st.subheader(f"{status_name} ({len(docs)})")
                if not docs:
                    st.markdown('<span class="rc-muted">- nothing here -</span>',
                                unsafe_allow_html=True)
                for doc in docs:
                    with st.container(border=True):
                        st.markdown(f"**{doc_label(doc)}**")
                        tags = store.document_tags(doc.id)
                        if tags:
                            st.markdown(
                                f'<span class="rc-muted">{escape(", ".join(tags))}</span>',
                                unsafe_allow_html=True,
                            )
                        new_status = st.selectbox(
                            "Status", STATUSES, index=STATUSES.index(status_name),
                            key=f"status-{doc.id}", label_visibility="collapsed",
                        )
                        if new_status != status_name:
                            kb.set_status(store, doc, new_status)
                            flash(f"Moved “{doc.title}” to {new_status}.")
                            st.rerun()
                        with st.expander("details"):
                            author_line = ", ".join(doc.authors) or "-"
                            meta_parts = [f"`{doc.id[:8]}`", author_line]
                            if doc.publication_date:
                                meta_parts.append(doc.publication_date)
                            elif doc.year:
                                meta_parts.append(str(doc.year))
                            if doc.venue:
                                ref = doc.venue
                                if doc.volume:
                                    ref += f" {doc.volume}"
                                    if doc.issue:
                                        ref += f"({doc.issue})"
                                if doc.pages:
                                    ref += f": {doc.pages}"
                                meta_parts.append(ref)
                            if doc.publisher:
                                meta_parts.append(doc.publisher)
                            if doc.item_type:
                                meta_parts.append(f"[{doc.item_type}]")
                            st.markdown(" · ".join(meta_parts))
                            if doc.abstract:
                                trunc = doc.abstract[:200] + (
                                    "..." if len(doc.abstract) > 200 else ""
                                )
                                st.caption(trunc)
                            chosen_tags = st.multiselect(
                                "Tags", sorted({*store.all_tags(), *tags}),
                                default=tags, key=f"tags-{doc.id}",
                                accept_new_options=True,
                                help="Pick existing tags or type a new one;"
                                     " deselect to remove.",
                            )
                            if sync_terms(chosen_tags, tags,
                                          lambda t, d=doc.id: store.tag_document(d, t),
                                          lambda t, d=doc.id: store.untag_document(d, t)):
                                st.rerun()
                            assigned = store.document_projects(doc.id)
                            chosen_projects = st.multiselect(
                                "Projects", sorted({*project_names(store), *assigned}),
                                default=assigned, key=f"projects-{doc.id}",
                                accept_new_options=True,
                                help="Pick existing projects or type a new one to"
                                     " create it.",
                            )
                            if sync_terms(chosen_projects, assigned,
                                          lambda p, d=doc.id: store.assign_project(d, p),
                                          lambda p, d=doc.id: store.unassign_project(d, p)):
                                st.rerun()
                            annotation_rows(store, doc)
                            with st.form(key=f"annform-{doc.id}", clear_on_submit=True,
                                         border=False):
                                annotation = st.text_area("New annotation",
                                                          key=f"ann-{doc.id}")
                                if (st.form_submit_button("Annotate")
                                        and annotation.strip()):
                                    store.add_annotation(doc.id, annotation.strip())
                                    flash("Annotation saved.")
                                    st.rerun()
                            ai_col1, ai_col2 = st.columns(2)
                            if ai_col1.button("Т  AI tags", key=f"aitag-{doc.id}",
                                              help="Suggest topical tags from the paper's"
                                                   " text (marked as AI-made)."):
                                run_enrichment(
                                    "Suggesting tags...",
                                    lambda d=doc: kb.suggest_tags(store, get_adapter(), d),
                                    lambda tags: f"Added tags: {', '.join(tags) or '(none)'}",
                                )
                            if ai_col2.button("Т  AI annotations", key=f"aiann-{doc.id}",
                                              help="Draft study annotations from the"
                                                   " paper's text (marked (ai))."):
                                run_enrichment(
                                    "Writing annotations...",
                                    lambda d=doc: kb.generate_annotations(
                                        store, get_adapter(), d),
                                    lambda created: f"Added {plural(len(created), 'AI annotation')}.",
                                )
                            source = Path(doc.source_path) if doc.source_path else None
                            if source and source.exists():
                                st.download_button(
                                    "Download PDF", data=source.read_bytes(),
                                    file_name=source.name, mime="application/pdf",
                                    key=f"dl-{doc.id}",
                                )
    with tab_notes:
        notes = [doc for doc in store.list_documents(collection="notes") if _matches(doc)]
        if not notes:
            st.info("No notes yet - add one under **Add to the library**."
                    " Notes are searched separately from papers, never mixed"
                    " into paper answers unless you widen the Ask scope.")
        for doc in notes:
            with st.container(border=True):
                st.markdown(f"**{doc.title}** `{doc.id[:8]}`")
                tags = store.document_tags(doc.id)
                if tags:
                    st.markdown(f'<span class="rc-muted">{escape(", ".join(tags))}</span>',
                                unsafe_allow_html=True)

# -------------------------------------------------------------------- Reader

elif page == "Reader":
    st.markdown(ornaments.page_header("Reader", "The reading room"),
                unsafe_allow_html=True)
    st.markdown(ornaments.watermark("Reader"), unsafe_allow_html=True)
    show_flash()
    readable = [
        doc for doc in store.list_documents(collection="papers")
        if doc.source_path and Path(doc.source_path).exists()
    ]
    if not readable:
        st.markdown(ornaments.empty_state("Reader"), unsafe_allow_html=True)
        st.info(
            "No papers with a stored PDF yet. On the **Library** page, upload"
            " a PDF or fetch a DOI that has an open-access copy - it will"
            " appear here, ready to read."
        )
    else:
        from research_cockpit.ingest import pdf_page_count, search_pdf

        main_col, side_col = st.columns([5, 2], gap="large")

        # side column first: its jump buttons must set the page *before* the
        # slider widget in the main column is instantiated.
        with side_col:
            labels = {f"{doc_label(doc)}  ·  {doc.id[:8]}": doc for doc in readable}
            picked = st.selectbox("Paper", list(labels),
                                  help="Type here to search the list by title.")
            doc = labels[picked]
            source = Path(doc.source_path)
            total = pdf_page_count(source)
            slider_key = f"reader-page-{doc.id}"
            st.session_state.setdefault(slider_key, 1)

            search_q = st.text_input(
                "Search inside this paper", key=f"reader-q-{doc.id}",
                placeholder="e.g. humidity",
                help="Matching pages are listed below; occurrences are"
                     " highlighted on the page.",
            )
            if search_q.strip():
                hits = search_pdf(source, search_q)
                if not hits:
                    st.caption(f"No matches for “{search_q}” in this paper.")
                else:
                    total_hits = sum(h.count for h in hits)
                    st.caption(f"{plural(total_hits, 'match', 'matches')}"
                               f" on {plural(len(hits), 'page')}")
                    for h in hits[:12]:
                        hit_col, snip_col = st.columns([1, 3])
                        if hit_col.button(f"p. {h.page}",
                                          key=f"hit-{doc.id}-{h.page}"):
                            st.session_state[slider_key] = h.page
                        snip_col.caption(f"...{h.snippet}...")
                    if len(hits) > 12:
                        st.caption(f"+ {len(hits) - 12} more matching pages")
            st.divider()
            st.markdown("**notes**")
            if not store.annotations(doc.id):
                st.caption("No notes on this paper yet - add one below.")
            annotation_rows(store, doc, jump_key=slider_key)
            with st.form(key=f"reader-note-{doc.id}", clear_on_submit=True,
                         border=False):
                note_text = st.text_area(
                    "Add a note on this folio", key=f"reader-ann-{doc.id}",
                    help="Saved as an annotation pinned to the folio you are"
                         " viewing; it feeds review flashcards like any other.",
                )
                if st.form_submit_button("Save note") and note_text.strip():
                    store.add_annotation(doc.id, note_text.strip(),
                                         page=st.session_state[slider_key])
                    flash(f"Note saved on folio {st.session_state[slider_key]}.")
                    st.rerun()
            st.divider()
            meta_bits = [", ".join(doc.authors) or None,
                         str(doc.year) if doc.year else None, doc.venue]
            st.caption(" · ".join(b for b in meta_bits if b) or "no metadata")
            st.download_button("Download PDF", data=source.read_bytes(),
                               file_name=source.name, mime="application/pdf")

        with main_col:
            nav1, nav2, nav3 = st.columns([1, 3, 1])
            if nav1.button("← Previous", disabled=st.session_state[slider_key] <= 1):
                st.session_state[slider_key] -= 1
            if nav3.button("Next →", disabled=st.session_state[slider_key] >= total):
                st.session_state[slider_key] += 1
            st.session_state[slider_key] = min(st.session_state[slider_key], total)
            if total > 1:
                nav2.slider("Page", 1, total, key=slider_key,
                            label_visibility="collapsed")
            current = st.session_state[slider_key]

            highlight = search_q.strip() or None
            st.image(_pdf_page_png(str(source), current, source.stat().st_mtime,
                                   highlight),
                     width="stretch")
            st.markdown(
                f'<p class="rc-muted" style="text-align:center">folio {current} of'
                f" {total} - {escape(doc_label(doc))}</p>",
                unsafe_allow_html=True,
            )

# -------------------------------------------------------------------- Review

elif page == "Review":
    st.markdown(ornaments.page_header("Review", "The review desk"),
                unsafe_allow_html=True)
    st.markdown(ornaments.watermark("Review"), unsafe_allow_html=True)
    show_flash()
    for doc in store.list_documents(collection="papers"):
        if doc.status in ("annotated", "cited") and store.get_schedule(doc.id) is None:
            kb.schedule_new(store, doc.id)
    due = store.due_documents()
    if not due:
        st.success(
            "Nothing due today - the hourglass rests. Annotating a paper (or"
            " using **Т  AI annotations** in the Library) adds it to the"
            " review queue."
        )
    else:
        doc = due[0]
        st.markdown(f'<p class="rc-muted">Reviewing 1 of {len(due)} due on '
                    f"{date.today().isoformat()}.</p>", unsafe_allow_html=True)
        st.subheader(doc_label(doc))
        try:
            with st.spinner("Preparing flashcards..."):
                cards = kb.ensure_flashcards(store, get_adapter(), doc)
        except Exception as exc:
            st.warning(f"Flashcard generation failed: {exc}")
            cards = []
        notice = llm_notice()
        if notice:
            st.warning(f"Notice: {notice}")
        for i, card in enumerate(cards):
            with st.expander(f"Q{i + 1}: {card['question']}"):
                st.markdown(f"**A:** {card['answer']}")
        st.markdown("**grade your recall:**")
        st.caption("0-2 = forgot (schedule resets) · 3-5 = recalled"
                   " (interval grows)")
        grade_cols = st.columns(6)
        labels = ["0 blank", "1", "2", "3 hard", "4 good", "5 easy"]
        for grade, (col, label) in enumerate(zip(grade_cols, labels, strict=True)):
            if col.button(label, key=f"grade-{doc.id}-{grade}"):
                next_due = kb.record_review(store, doc.id, grade)
                flash(f"Recorded - next review {next_due.isoformat()}.")
                st.rerun()

# --------------------------------------------------------------------- Graph

elif page == "Graph":
    st.markdown(ornaments.page_header("Graph", "The chart of influence"),
                unsafe_allow_html=True)
    st.markdown(ornaments.watermark("Graph"), unsafe_allow_html=True)
    show_flash()
    from research_cockpit.graph import clusters as find_clusters
    from research_cockpit.graph import gaps as graph_gaps
    from research_cockpit.graph import to_networkx

    if st.button("Fetch / refresh edges (OpenAlex)"):
        from research_cockpit.apis import OpenAlexClient, S2Client
        from research_cockpit.graph import EdgeFetcher, build_graph

        cfg = get_config()
        with st.spinner("Fetching references and citations..."):
            result = build_graph(
                store,
                EdgeFetcher(OpenAlexClient(mailto=cfg.get("citations.mailto", "")),
                            S2Client(api_key=cfg.get("citations.s2_api_key", ""))),
            )
        st.success(f"{plural(result.seeds, 'seed')}, {plural(result.edges, 'edge')}."
                   + (f" Skipped: {', '.join(result.skipped)}" if result.skipped else ""))

    g = to_networkx(store)
    if g.number_of_edges() == 0:
        st.markdown(ornaments.empty_state("Graph"), unsafe_allow_html=True)
        st.info("No edges yet - add papers with DOIs on the Library page,"
                " then press **Fetch / refresh edges** above.")
    else:
        communities = find_clusters(g)
        cluster_of = {n: i for i, community in enumerate(communities) for n in community}
        palette = ["#4A5D45", "#7B3F3A", "#8A6D3B", "#3B5B6D", "#6D3B5B", "#5C5346"]
        try:
            import networkx as nx
            from streamlit_agraph import Config as AgraphConfig
            from streamlit_agraph import Edge, Node, agraph

            centrality = nx.pagerank(g)
            nodes = [
                Node(
                    id=n,
                    label=(data.get("title") or n)[:40],
                    size=10 + 60 * centrality.get(n, 0),
                    color=palette[cluster_of.get(n, 0) % len(palette)],
                    shape="dot" if data.get("internal") else "diamond",
                )
                for n, data in g.nodes(data=True)
            ]
            edges = [Edge(source=u, target=v) for u, v in g.edges()]
            st.caption("● in your library · ◇ external - size = influence"
                       " (PageRank) · colour = cluster · click a node for details")
            clicked = agraph(nodes, edges,
                             AgraphConfig(width=900, height=560, directed=True,
                                          physics=True, hierarchical=False))
            if clicked:
                doc = store.get_document(clicked)
                if doc:
                    st.markdown(f"**{doc_label(doc)}** - status `{doc.status}`,"
                                f" id `{doc.id[:8]}` (see Library page)")
                else:
                    st.markdown(f"External work: `{clicked}` - not in your library yet.")
        except ImportError:
            st.warning("Install `streamlit-agraph` for the interactive view;"
                       " showing clusters as text.")
            for i, community in enumerate(communities, 1):
                titles = [g.nodes[n].get("title", n) for n in community[:5]]
                st.markdown(f"**Cluster {i}** ({len(community)}): " + "; ".join(titles))

        st.subheader("gaps - high-value papers to add")
        for s in graph_gaps(store, g=g, limit=10):
            col1, col2 = st.columns([5, 1])
            col1.markdown(f"{s.title} - `{s.reason}`, centrality {s.centrality:.4f}")
            if s.reason == "not-in-library" and col2.button("To-read", key=f"gap-{s.node}"):
                from research_cockpit.store import Document, new_id

                store.add_document(Document(
                    id=new_id(), collection="papers", title=s.title,
                    openalex_id=s.node if s.node.startswith("W") else None,
                    doi=s.node[4:] if s.node.startswith("doi:") else None,
                    status="to-read",
                ))
                st.rerun()

# ----------------------------------------------------------------- Citations

elif page == "Citations":
    st.markdown(ornaments.page_header("Citations", "The ledger"),
                unsafe_allow_html=True)
    st.markdown(ornaments.watermark("Citations"), unsafe_allow_html=True)
    show_flash()
    STYLE_LABELS = {
        "BibTeX (.bib - import into LaTeX)": "bibtex",
        "APA": "apa",
        "MLA": "mla",
        "Chicago (author-date)": "chicago",
    }
    col1, col2, col3, col4 = st.columns(4)
    style = STYLE_LABELS[col1.selectbox("Style", list(STYLE_LABELS))]
    tag = tag_filter(store, col2, "bib-tag")
    status = pick_filter(col3, "Status", list(STATUSES), "bib-status")
    project = project_filter(store, col4, "bib-project")

    text = bib.format_citations(store, style, tag=tag, status=status, project=project)
    n_entries = (text.count("@") if style == "bibtex"
                 else len([p for p in text.split("\n\n") if p.strip()]))
    if not text:
        st.info("No papers match these filters yet - clear a filter, or add"
                " papers on the Library page.")
    else:
        st.caption(f"{plural(n_entries, 'paper')} in this bibliography")
    if style == "bibtex":
        st.code(text or "% no matching papers", language="bibtex")
        st.download_button("Download refs.bib", data=text, file_name="refs.bib",
                           mime="text/x-bibtex")
    else:
        for line in text.split("\n\n"):
            if line.strip():
                st.markdown(line)
        st.download_button(f"Download {style}.txt", data=text,
                           file_name=f"citations-{style}.txt", mime="text/plain")

# -------------------------------------------------------------- Constellation

elif page == "Constellation":
    st.markdown(ornaments.page_header("Constellation", "The firmament of notes"),
                unsafe_allow_html=True)
    st.markdown(ornaments.watermark("Constellation"), unsafe_allow_html=True)
    show_flash()

    from research_cockpit.constellation import (
        add_source,
        confirmed_links,
        dismiss_suggestion,
        export_constellation,
        get_sources,
        link_notes,
        suggest_links,
        to_networkx,
    )

    notes = store.list_documents(collection="notes")
    if len(notes) < 2:
        st.markdown(ornaments.empty_state("Constellation"), unsafe_allow_html=True)
        st.info(
            "The Constellation maps connections between your **notes**."
            " Add at least two notes on the Library page, then come back to see"
            " semantic suggestions and manually link related ideas."
        )
    else:
        # ------- interactive graph
        g = to_networkx(store)
        suggestions = suggest_links(store, threshold=0.45, top_k=5)

        try:
            from streamlit_agraph import Config as AgraphConfig
            from streamlit_agraph import Edge, Node, agraph

            palette = ["#4A5D45", "#7B3F3A", "#8A6D3B", "#3B5B6D", "#6D3B5B"]
            agraph_nodes = [
                Node(id=n, label=(data.get("title") or "Untitled")[:35],
                     size=18, color=palette[i % len(palette)])
                for i, (n, data) in enumerate(g.nodes(data=True))
            ]
            agraph_edges = [
                Edge(source=u, target=v, color="#2E2A24", width=2)
                for u, v in g.edges()
            ]
            # show suggested edges as dashed
            for s in suggestions[:8]:
                agraph_edges.append(
                    Edge(source=s["a_id"], target=s["b_id"],
                         color="#D8CFBE", width=1, dashes=True)
                )

            st.caption(
                f"{plural(g.number_of_nodes(), 'note')}"
                f" · {plural(g.number_of_edges(), 'confirmed link')}"
                f" · {plural(len(suggestions), 'suggestion')}"
            )
            clicked = agraph(
                agraph_nodes, agraph_edges,
                AgraphConfig(width=850, height=480, directed=False,
                             physics=True, hierarchical=False),
            )
            if clicked:
                clicked_doc = store.get_document(clicked)
                if clicked_doc:
                    st.markdown(f"**{clicked_doc.title}** `{clicked_doc.id[:8]}`")
                    sources = get_sources(store, clicked_doc.id)
                    if sources:
                        st.markdown("**provenance:**")
                        for src in sources:
                            page_str = f" p.{src['page']}" if src["page"] else ""
                            quote_str = f' - "{src["quote"][:80]}"' if src["quote"] else ""
                            st.markdown(
                                f"  · {src['document_title']}{page_str}{quote_str}"
                            )
        except ImportError:
            st.warning(
                "Install `streamlit-agraph` (`pip install streamlit-agraph`)"
                " for the interactive graph view. Showing links as text."
            )
            for link in confirmed_links(store):
                a_doc = store.get_document(link["a_id"])
                b_doc = store.get_document(link["b_id"])
                a_title = a_doc.title if a_doc else link["a_id"][:8]
                b_title = b_doc.title if b_doc else link["b_id"][:8]
                label_str = f" ({link['label']})" if link["label"] else ""
                st.markdown(f"  · **{a_title}** ↔ **{b_title}**{label_str}")

        # ------- suggestions panel
        st.subheader("suggested links")
        if not suggestions:
            st.caption("No suggestions above threshold - add more notes or"
                       " lower the sensitivity.")
        for i, s in enumerate(suggestions[:10]):
            a_doc = store.get_document(s["a_id"])
            b_doc = store.get_document(s["b_id"])
            a_title = (a_doc.title if a_doc else s["a_id"][:8]) or "Untitled"
            b_title = (b_doc.title if b_doc else s["b_id"][:8]) or "Untitled"
            cols = st.columns([4, 1, 1, 1])
            cols[0].markdown(
                f"**{escape(a_title)}** ↔ **{escape(b_title)}** "
                f'<span class="rc-muted">({s["score"]:.2f})</span>',
                unsafe_allow_html=True,
            )
            label = cols[2].text_input("label", key=f"con-label-{i}",
                                       placeholder="optional",
                                       label_visibility="collapsed")
            if cols[1].button("✓ Confirm", key=f"con-confirm-{i}"):
                link_notes(store, s["a_id"], s["b_id"], label=label or None)
                flash(f"Linked: {a_title} ↔ {b_title}")
                st.rerun()
            if cols[3].button("Х Dismiss", key=f"con-dismiss-{i}"):
                dismiss_suggestion(store, s["a_id"], s["b_id"])
                flash(f"Dismissed suggestion: {a_title} ↔ {b_title}")
                st.rerun()

        # ------- manual link
        st.subheader("manual link")
        note_labels = {f"{doc.title or 'Untitled'} ({doc.id[:8]})": doc.id for doc in notes}
        mcol1, mcol2, mcol3 = st.columns([2, 2, 1])
        note_a = mcol1.selectbox("Note A", list(note_labels), key="con-a")
        note_b = mcol2.selectbox("Note B", list(note_labels), key="con-b")
        link_label = mcol3.text_input("Label", key="con-manual-label",
                                      placeholder="optional")
        if st.button("Link these notes"):
            a_id = note_labels[note_a]
            b_id = note_labels[note_b]
            if a_id == b_id:
                st.error("Cannot link a note to itself.")
            else:
                link_notes(store, a_id, b_id, label=link_label or None)
                flash(f"Linked: {note_a} ↔ {note_b}")
                st.rerun()

        # ------- provenance
        st.subheader("add provenance")
        st.caption("Record where a note's idea came from (paper + page + quote).")
        prov_note = st.selectbox("Note", list(note_labels), key="prov-note")
        papers = store.list_documents(collection="papers")
        paper_labels = {f"{doc_label(d)} · {d.id[:8]}": d.id for d in papers}
        if paper_labels:
            prov_paper = st.selectbox("Source paper", list(paper_labels), key="prov-paper")
            pcol1, pcol2 = st.columns(2)
            prov_page = pcol1.number_input("Page", min_value=1, value=1, key="prov-page")
            prov_quote = pcol2.text_input("Quote", key="prov-quote",
                                          placeholder="verbatim passage...")
            if st.button("Record provenance"):
                add_source(store, note_labels[prov_note], paper_labels[prov_paper],
                           page=prov_page, quote=prov_quote or None)
                flash("Provenance recorded.")
                st.rerun()
        else:
            st.caption("Add papers to the library first to record provenance.")

        # ------- export
        st.subheader("export")
        ecol1, ecol2 = st.columns(2)
        if ecol1.button("Export as JSON"):
            import tempfile as _tf

            with _tf.NamedTemporaryFile(suffix=".json", delete=False) as _f:
                export_constellation(store, Path(_f.name))
                data = Path(_f.name).read_text()
            st.download_button("Download notes.json", data=data,
                               file_name="constellation.json", mime="application/json")
        if ecol2.button("Export as GraphML"):
            import tempfile as _tf

            with _tf.NamedTemporaryFile(suffix=".graphml", delete=False) as _f:
                export_constellation(store, Path(_f.name))
                data = Path(_f.name).read_text()
            st.download_button("Download notes.graphml", data=data,
                               file_name="constellation.graphml", mime="application/xml")

# ------------------------------------------------------------------- Claims

elif page == "Claims":
    st.markdown(ornaments.page_header("Claims", "The argument"),
                unsafe_allow_html=True)
    st.markdown(ornaments.watermark("Claims"), unsafe_allow_html=True)
    show_flash()

    from research_cockpit.claims import (
        add_claim,
        attach_evidence,
        delete_claim,
        detach_evidence,
        get_claim,
        list_claims,
    )

    projects = store.list_projects()
    if not projects:
        st.markdown(ornaments.empty_state("Claims"), unsafe_allow_html=True)
        st.info(
            "Claims live inside **projects**. Create a project on the Library page"
            " first, then come back to build your argument outline."
        )
    else:
        project_names_list = [p["name"] for p in projects]
        selected_project = st.selectbox("Project", project_names_list, key="claims-project")

        # add claim form
        with st.expander("Add a claim"):
            claim_text = st.text_area("Claim statement", key="claim-new-text",
                                      placeholder="e.g. Humidity is the primary driver...")
            claim_notes = st.text_input("Notes (optional)", key="claim-new-notes")
            if st.button("Add claim") and claim_text.strip():
                add_claim(store, selected_project, claim_text.strip(),
                          notes=claim_notes or None)
                flash("Claim added.")
                st.rerun()

        claims = list_claims(store, selected_project)
        if not claims:
            st.caption("No claims yet - add one above to start building"
                       " your argument outline.")
        else:
            st.caption(f"{plural(len(claims), 'claim')} in project"
                       f" **{selected_project}**")

        for claim in claims:
            with st.container(border=True):
                cols = st.columns([5, 1])
                cols[0].markdown(
                    f"**{claim['ordinal'] + 1}.** {escape(claim['text'])}"
                    + (f' <span class="rc-muted">- {escape(claim["notes"])}</span>'
                       if claim["notes"] else ""),
                    unsafe_allow_html=True,
                )
                cols[0].caption(plural(claim["evidence_count"], "evidence passage"))
                if cols[1].button("Х", key=f"clm-del-{claim['id']}",
                                  help="Delete this claim"):
                    delete_claim(store, claim["id"])
                    flash("Claim deleted.")
                    st.rerun()

                # show full evidence when expanded
                with st.expander("evidence & attach"):
                    full = get_claim(store, claim["id"])
                    if full and full["evidence"]:
                        for ev in full["evidence"]:
                            ev_cols = st.columns([4, 1, 1])
                            stance_icon = {"supports": "+", "contradicts": "-",
                                           "context": "i"}.get(ev["stance"], ".")
                            page_str = f" p.{ev['page']}" if ev["page"] else ""
                            ev_cols[0].markdown(
                                f"{stance_icon} “{ev['quote'][:120]}” - "
                                f"*{ev['document_title']}*{page_str}"
                            )
                            ev_cols[1].caption(ev["stance"])
                            if ev_cols[2].button("Х", key=f"ev-del-{ev['id']}"):
                                detach_evidence(store, ev["id"])
                                flash("Evidence detached.")
                                st.rerun()
                    else:
                        st.caption("No evidence yet - attach a passage below.")

                    # attach evidence form
                    papers = store.list_documents(collection="papers")
                    if papers:
                        paper_labels_c = {f"{doc_label(d)} · {d.id[:8]}": d.id for d in papers}
                        ev_paper = st.selectbox(
                            "Source paper", list(paper_labels_c),
                            key=f"ev-paper-{claim['id']}",
                        )
                        ev_cols2 = st.columns([3, 1, 1])
                        ev_quote = ev_cols2[0].text_input(
                            "Quote", key=f"ev-quote-{claim['id']}",
                            placeholder="verbatim passage...",
                        )
                        ev_page = ev_cols2[1].number_input(
                            "Page", min_value=0, value=0,
                            key=f"ev-page-{claim['id']}",
                            help="0 = unknown",
                        )
                        ev_stance = ev_cols2[2].selectbox(
                            "Stance", ["supports", "contradicts", "context"],
                            key=f"ev-stance-{claim['id']}",
                        )
                        if st.button("Attach", key=f"ev-attach-{claim['id']}"):
                            if not ev_quote.strip():
                                st.error("Quote is required.")
                            else:
                                attach_evidence(
                                    store, claim["id"],
                                    paper_labels_c[ev_paper],
                                    ev_quote.strip(),
                                    page=ev_page or None,
                                    stance=ev_stance,
                                )
                                flash("Evidence attached.")
                                st.rerun()

# ---------------------------------------------------------------- Questions

elif page == "Questions":
    st.markdown(ornaments.page_header("Questions", "Open threads"),
                unsafe_allow_html=True)
    st.markdown(ornaments.watermark("Questions"), unsafe_allow_html=True)
    show_flash()

    from research_cockpit.questions import (
        add_item,
        add_question,
        close_question,
        get_question,
        list_questions,
    )

    projects = store.list_projects()
    project_names_list = [p["name"] for p in projects] if projects else []

    # add question form
    with st.expander("New research question"):
        q_text = st.text_area("Question", key="q-new-text",
                              placeholder="e.g. What are the mechanisms of cockling?")
        q_project = st.selectbox("Project (optional)",
                                 ["(none)", *project_names_list], key="q-new-project")
        if st.button("Save question") and q_text.strip():
            proj = q_project if q_project != "(none)" else None
            add_question(store, q_text.strip(), project_name=proj)
            flash("Question saved.")
            st.rerun()

    # filter
    q_filter_proj = st.selectbox("Filter by project",
                                 ["(all)", *project_names_list], key="q-filter-proj")
    filter_proj = q_filter_proj if q_filter_proj != "(all)" else None
    questions = list_questions(store, project_name=filter_proj)

    if not questions:
        st.markdown(ornaments.empty_state("Questions"), unsafe_allow_html=True)
        st.info("No research questions yet - add one above. Questions"
                " collect sources, notes, and gaps as you research.")
    for q in questions:
        status_icon = {"open": "○", "answered": "✓", "parked": "‖"}.get(q["status"], "·")
        with st.container(border=True):
            qcols = st.columns([5, 1, 1])
            qcols[0].markdown(f"{status_icon} **{q['text']}**")
            qcols[0].caption(f"Status: {q['status']} · {q['created_at'][:10]}")

            # status change
            new_status = qcols[1].selectbox(
                "Status", ["open", "answered", "parked"],
                index=["open", "answered", "parked"].index(q["status"]),
                key=f"qstat-{q['id']}", label_visibility="collapsed",
            )
            if new_status != q["status"]:
                close_question(store, q["id"], status=new_status)
                flash(f"Question status → {new_status}")
                st.rerun()

            # expand thread
            with st.expander("thread"):
                full_q = get_question(store, q["id"])
                if full_q and full_q["items"]:
                    for item in full_q["items"]:
                        # ink glyphs, not emoji - matches the engraved art
                        kind_icon = {"source": "§", "note": "О ",
                                     "gap": "?"}.get(item["kind"], "·")
                        st.markdown(f"{kind_icon} **{item['kind']}**: {item['text']}")
                else:
                    st.caption("No items yet - add sources, notes, or gaps below.")

                # add item form
                icols = st.columns([1, 3])
                item_kind = icols[0].selectbox(
                    "Kind", ["source", "note", "gap"],
                    key=f"qi-kind-{q['id']}", label_visibility="collapsed",
                )
                item_text = icols[1].text_input(
                    "Text", key=f"qi-text-{q['id']}",
                    placeholder="source reference, note, or gap description...",
                    label_visibility="collapsed",
                )
                if st.button("Add item", key=f"qi-add-{q['id']}") and item_text.strip():
                    add_item(store, q["id"], item_kind, item_text.strip())
                    flash("Item added to thread.")
                    st.rerun()

# ------------------------------------------------------------- closing plate
# Every page ends with a small public-domain print from the Met's Open Access
# collection (CC0), toned to the palette. Credits: assets/art/CREDITS.md.

PLATES = {
    "Ask": ("ask-tiepolo-magician.jpg",
            "Magician near a smoking Altar - G. B. Tiepolo, ca. 1743-52"),
    "Library": ("library-rembrandt-faust.jpg",
                "A Scholar in His Study (‘Faust’) - Rembrandt, ca. 1652"),
    "Reader": ("reader-seated-man.jpg",
               "Seated Man Reading - J. H. Fragonard, 1774"),
    "Review": ("philosopher-tiepolo.jpg",
               "The Philosopher - G. B. Tiepolo, ca. 1740"),
    "Graph": ("graph-dente-scholars.jpg",
              "Assembly of Scholars around an Open Book - M. Dente, ca. 1515-27"),
    "Citations": ("citations-durer-jerome.jpg",
                  "Saint Jerome in His Study - Albrecht Dürer, 1514"),
    "Constellation": ("constellation-armillary.jpg",
                      "Woman Examining an Armillary Sphere - Master F. P., 16th c."),
    "Claims": ("claims-cortona-thesis.jpg",
               "Design for a Thesis Print - Pietro da Cortona, ca. 1635"),
    "Questions": ("questions-durer-melencolia.jpg",
                  "Melencolia I - Albrecht Dürer, 1514"),
}
plate_name, plate_caption = PLATES.get(page, (None, None))
plate_path = ASSETS / "art" / plate_name if plate_name else None
if plate_path and plate_path.exists():
    st.markdown(f'<div class="rc-laurel">{ornaments.LAUREL}</div>',
                unsafe_allow_html=True)
    _, plate_col, _ = st.columns([2, 1.2, 2])
    plate_col.image(str(plate_path), width=240,
                    caption=f"{plate_caption} · The Met (public domain)")
