"""Literature review builder (M14): comparison tables + cited drafts.

Select papers (by project/tag/explicit ids) → build a comparison table of M8
citation fields + M9 extraction fields → export Markdown/LaTeX; optionally
LLM-synthesize a cited draft referencing `\\cite{key}` / `[@key]` with cite
keys from `bib.py`.
"""

from __future__ import annotations

from .bib import _cite_key, export_bibtex
from .extract import get_extraction
from .store import Document, Store


def _escape_latex(text: str) -> str:
    for ch in ("&", "%", "$", "#", "_", "{", "}"):
        text = text.replace(ch, f"\\{ch}")
    return text


def comparison_table(
    store: Store,
    docs: list[Document],
    fields: tuple[str, ...] = ("task", "method", "datasets", "findings", "limitations"),
) -> list[dict]:
    """Build a comparison matrix: one row per paper, columns = citation fields + extraction fields.

    Returns a list of dicts (one per paper) suitable for rendering to markdown/latex.
    """
    rows = []
    for doc in docs:
        ext = get_extraction(store, doc.id) or {}
        row = {
            "cite_key": _cite_key(doc),
            "title": doc.title or "Untitled",
            "authors": ", ".join(doc.authors) if doc.authors else "-",
            "year": doc.year or "-",
            "venue": doc.venue or "-",
        }
        for f in fields:
            val = ext.get(f)
            if isinstance(val, list):
                row[f] = "; ".join(str(v) if isinstance(v, str) else v.get("name", str(v))
                                   for v in val) if val else "-"
            else:
                row[f] = val or "-"
        rows.append(row)
    return rows


def render_table_markdown(rows: list[dict], fields: tuple[str, ...] | None = None) -> str:
    """Render a comparison table as a Markdown pipe-table."""
    if not rows:
        return "(no papers selected)"
    cols = list(rows[0].keys()) if fields is None else ["cite_key", "title", *fields]
    header = "| " + " | ".join(cols) + " |"
    sep = "| " + " | ".join("---" for _ in cols) + " |"
    lines = [header, sep]
    for row in rows:
        cells = [str(row.get(c, "-")).replace("|", "/").replace("\n", " ")[:80] for c in cols]
        lines.append("| " + " | ".join(cells) + " |")
    return "\n".join(lines)


def render_table_latex(rows: list[dict], fields: tuple[str, ...] | None = None) -> str:
    """Render a comparison table as a LaTeX booktabs table."""
    if not rows:
        return "% (no papers selected)"
    cols = list(rows[0].keys()) if fields is None else ["cite_key", "title", *fields]
    col_spec = "l" * len(cols)
    header = " & ".join(_escape_latex(c) for c in cols) + r" \\"
    lines = [
        r"\begin{table}[htbp]",
        r"\centering",
        f"\\begin{{tabular}}{{{col_spec}}}",
        r"\toprule",
        header,
        r"\midrule",
    ]
    for row in rows:
        cells = [_escape_latex(str(row.get(c, "-"))[:60]) for c in cols]
        lines.append(" & ".join(cells) + r" \\")
    lines += [r"\bottomrule", r"\end{tabular}", r"\end{table}"]
    return "\n".join(lines)


# -------------------------------------------------------------- cited draft


REVIEW_SYSTEM = (
    "You write concise academic literature review sections. Given a structured"
    " comparison of papers (title, key, and extracted fields), synthesize a"
    " review paragraph that:"
    "\n1. Compares and contrasts the papers' methods, findings, and limitations."
    "\n2. Cites every factual claim using LaTeX `\\cite{key}` markers."
    "\n3. Is suitable for a Related Work or Background section in an academic paper."
    "\nDo NOT invent facts not present in the provided data. Be concise."
)


def generate_draft(
    store: Store,
    adapter,
    docs: list[Document],
    fields: tuple[str, ...] = ("task", "method", "findings", "limitations"),
) -> tuple[str, str]:
    """Generate a cited review draft. Returns (draft_text, bib_text).

    The draft uses `\\cite{key}` markers; the bib_text is a generated .bib
    matching those keys, ready to compile.
    """
    rows = comparison_table(store, docs, fields)
    if not rows:
        return "(no papers to review)", ""

    prompt_parts = ["Papers for review:\n"]
    for row in rows:
        prompt_parts.append(f"- [{row['cite_key']}] {row['title']} ({row['year']})")
        for f in fields:
            prompt_parts.append(f"    {f}: {row.get(f, '-')}")
    prompt = "\n".join(prompt_parts)


    draft = adapter.generate(prompt, system=REVIEW_SYSTEM)
    bib_text = export_bibtex(store, project=None, tag=None, status=None)
    return draft, bib_text
