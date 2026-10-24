"""Typer CLI - thin frontend over the core library (as is the Streamlit UI)."""

from __future__ import annotations

import sys
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from .config import Config
from .store import STATUSES, Store

app = typer.Typer(help="Research Cockpit: RAG, literature KB, citation graph.",
                  no_args_is_help=True)
kb_app = typer.Typer(help="Paper lifecycle, tags, annotations.", no_args_is_help=True)
bib_app = typer.Typer(help="BibTeX import/export.", no_args_is_help=True)
graph_app = typer.Typer(help="Citation graph build/clusters/gaps/export.",
                        no_args_is_help=True)
config_app = typer.Typer(help="Show or set config values.", no_args_is_help=True)
project_app = typer.Typer(help="Group documents into projects.", no_args_is_help=True)
extract_app = typer.Typer(help="Structured paper extraction.", no_args_is_help=True)
claim_app = typer.Typer(help="Claim-to-evidence workspace.", no_args_is_help=True)
app.add_typer(extract_app, name="extract")
app.add_typer(claim_app, name="claim")
app.add_typer(kb_app, name="kb")
app.add_typer(bib_app, name="bib")
app.add_typer(graph_app, name="graph")
app.add_typer(config_app, name="config")
app.add_typer(project_app, name="project")

console = Console()
err = Console(stderr=True, style="bold red")


def _config() -> Config:
    return Config.load()


def _store(cfg: Config) -> Store:
    return Store(cfg.store_path)


def _embedder(cfg: Config):
    from .embed import get_embedder

    return get_embedder(cfg.get("embeddings.model"))


def _resolve_or_die(store: Store, ref: str):
    doc = store.resolve_document(ref)
    if doc is None:
        err.print(f"No document matches '{ref}' (try `rc kb list` for ids).")
        raise typer.Exit(1)
    return doc


def _resolve_claim_or_die(store: Store, ref: str):
    from .claims import resolve_claim

    claim = resolve_claim(store, ref)
    if claim is None:
        err.print(f"No unique claim matches '{ref}' (try `rc claim list <project>` for ids).")
        raise typer.Exit(1)
    return claim


def _resolver(cfg: Config):
    from .apis import MetadataResolver, OpenAlexClient, S2Client

    return MetadataResolver(
        OpenAlexClient(mailto=cfg.get("citations.mailto", "")),
        S2Client(api_key=cfg.get("citations.s2_api_key", "")),
    )


# ---------------------------------------------------------------- ingestion


@app.command()
def add(
    refs: list[str] = typer.Argument(
        ..., help="PDF file(s) and/or DOI(s) or doi.org links to ingest as papers."
    ),
    no_resolve: bool = typer.Option(False, "--no-resolve", help="Skip online metadata lookup."),
):
    """Ingest papers from PDFs or DOIs.

    A DOI/doi.org link is resolved via OpenAlex/S2 and its open-access PDF is
    searched for, downloaded, and ingested; if no OA copy exists, a
    metadata-only to-read record is created (ingest the PDF later with
    `rc add <file>` - it merges by DOI).
    """
    from .apis import normalize_doi
    from .config import rc_home
    from .ingest import ingest_doi, ingest_pdf

    cfg = _config()
    store = _store(cfg)
    embedder = None
    resolver = None if no_resolve else _resolver(cfg)
    chunk_kwargs = dict(
        chunk_tokens=int(cfg.get("rag.chunk_tokens", 512)),
        chunk_overlap=int(cfg.get("rag.chunk_overlap", 64)),
    )
    failed = False
    for ref in refs:
        path = Path(ref).expanduser()
        if path.is_file():
            if embedder is None:
                embedder = _embedder(cfg)
            result = ingest_pdf(store, embedder, path, resolver=resolver, **chunk_kwargs)
        elif normalize_doi(ref):
            if resolver is None:
                err.print(f"Cannot ingest DOI '{ref}' with --no-resolve.")
                failed = True
                continue
            if embedder is None:
                embedder = _embedder(cfg)
            result = ingest_doi(store, embedder, ref, resolver,
                                pdf_dir=rc_home() / "papers", **chunk_kwargs)
        else:
            err.print(f"Not a file or DOI: {ref}")
            failed = True
            continue
        doc = result.document
        if result.deduped:
            console.print(f"[yellow]Already in library:[/] {doc.title} ({doc.id[:8]})")
        elif result.chunks == 0:
            if path.is_file():
                console.print(
                    f"[yellow]No searchable text found[/] in {path.name} ({doc.id[:8]})."
                    " Added a metadata-only record; run OCR on scanned PDFs before ingestion."
                )
            else:
                console.print(
                    f"[yellow]No open-access PDF found[/] for {doc.title} ({doc.id[:8]})"
                    " - added metadata-only record (to-read)."
                    " Ingest the PDF later with `rc add <file>`."
                )
        else:
            meta = "metadata resolved" if result.resolved else "metadata unresolved"
            fetched = "downloaded, " if result.downloaded else ""
            console.print(
                f"[green]Added[/] {doc.title} ({doc.id[:8]}) - "
                f"{fetched}{result.chunks} chunks, {meta}"
            )
    store.close()
    if failed:
        raise typer.Exit(1)


@app.command("add-note")
def add_note(
    file: str = typer.Argument(..., help="Note file path, or '-' for stdin."),
    title: str = typer.Option("", "--title", help="Note title (defaults to filename)."),
    tag: list[str] = typer.Option([], "--tag", help="Tag(s) to apply."),
):
    """Ingest a personal note into the notes collection (RAG-only; no lifecycle)."""
    from .ingest import ingest_note

    cfg = _config()
    if file == "-":
        text = sys.stdin.read()
        note_title = title or "stdin note"
        source = None
    else:
        path = Path(file).expanduser()
        if not path.exists():
            err.print(f"Not found: {path}")
            raise typer.Exit(1)
        text = path.read_text()
        note_title = title or path.stem
        source = str(path)
    if not text.strip():
        err.print("Note is empty.")
        raise typer.Exit(1)
    result = ingest_note(
        _store(cfg), _embedder(cfg), text, note_title, source_path=source, tags=list(tag),
        chunk_tokens=int(cfg.get("rag.chunk_tokens", 512)),
        chunk_overlap=int(cfg.get("rag.chunk_overlap", 64)),
    )
    verb = "Already ingested" if result.deduped else "Added note"
    console.print(f"[green]{verb}[/] {result.document.title}"
                  f" ({result.document.id[:8]}) - {result.chunks} chunks")


# ------------------------------------------------------------------ projects


@project_app.command("add")
def project_add(name: str = typer.Argument(...),
                description: str = typer.Option(None, "--description", "-d")):
    """Create a project."""
    store = _store(_config())
    created = store.create_project(name, description)
    console.print(f"Project [green]{created}[/] ready.")


@project_app.command("list")
def project_list():
    """List projects with document counts."""
    rows = _store(_config()).list_projects()
    if not rows:
        console.print("No projects yet - create one with `rc project add <name>`.")
        return
    table = Table(show_header=True, header_style="bold")
    table.add_column("project")
    table.add_column("documents", justify="right")
    table.add_column("description")
    for row in rows:
        table.add_row(row["name"], str(row["documents"]), row["description"] or "")
    console.print(table)


@project_app.command("assign")
def project_assign(ref: str = typer.Argument(..., help="Doc id/prefix, DOI, or title."),
                   projects: list[str] = typer.Argument(..., help="Project name(s).")):
    """Assign a document to project(s) (creates them if needed)."""
    store = _store(_config())
    doc = _resolve_or_die(store, ref)
    for name in projects:
        store.assign_project(doc.id, name)
    console.print(f"{doc.title}: {', '.join(store.document_projects(doc.id))}")


@project_app.command("unassign")
def project_unassign(ref: str = typer.Argument(...), project: str = typer.Argument(...)):
    """Remove a document from a project."""
    store = _store(_config())
    doc = _resolve_or_die(store, ref)
    store.unassign_project(doc.id, project)
    console.print(f"{doc.title}: {', '.join(store.document_projects(doc.id)) or '(none)'}")


@project_app.command("remove")
def project_remove(name: str = typer.Argument(...)):
    """Delete a project (documents are kept, just unassigned)."""
    _store(_config()).delete_project(name)
    console.print(f"Removed project {name}.")


# ------------------------------------------------------------ extraction


@extract_app.command("run")
def extract_run(
    ref: str = typer.Argument(None, help="One paper (default: every paper with chunks)."),
    force: bool = typer.Option(False, "--force",
                               help="Overwrite even human-corrected fields."),
):
    """LLM-extract structured fields (task/method/datasets/metrics/findings/limitations)."""
    from .extract import extract_paper
    from .llm import LLMError, degraded_notice, get_adapter

    cfg = _config()
    store = _store(cfg)
    adapter = get_adapter(cfg)
    docs = ([_resolve_or_die(store, ref)] if ref
            else store.list_documents(collection="papers"))
    for doc in docs:
        if store.chunk_count(doc.id) == 0:
            console.print(f"[dim]skip (no chunks)[/] {doc.title} ({doc.id[:8]})")
            continue
        try:
            extract_paper(store, adapter, doc, force=force)
            console.print(f"[green]extracted[/] {doc.title} ({doc.id[:8]})")
        except LLMError as exc:
            err.print(f"{doc.title}: {exc}")
    notice = degraded_notice(adapter)
    if notice:
        err.print(f"[yellow]Notice:[/] {notice}")


@extract_app.command("show")
def extract_show(ref: str = typer.Argument(...)):
    """Show the extraction record for a paper."""
    from .extract import EXTRACTION_FIELDS, get_extraction

    store = _store(_config())
    doc = _resolve_or_die(store, ref)
    ext = get_extraction(store, doc.id)
    if ext is None:
        console.print("No extraction yet - run `rc extract run`.")
        return
    import json as _json

    sources = _json.loads(ext["field_sources"])
    for f in EXTRACTION_FIELDS:
        val = ext[f]
        src = sources.get(f, "-")
        if isinstance(val, list):
            val = _json.dumps(val, indent=2) if val else "[]"
        console.print(f"[bold]{f}[/] ({src}): {val or '-'}")


@extract_app.command("set")
def extract_set(
    ref: str = typer.Argument(...),
    field: str = typer.Option(..., "--field", help="Field name to set."),
    value: str = typer.Option(..., "--value", help="New value (JSON for arrays)."),
):
    """Manually set one extraction field (marks it as 'human' - survives re-runs)."""
    from .extract import set_extraction_field

    store = _store(_config())
    doc = _resolve_or_die(store, ref)
    try:
        set_extraction_field(store, doc.id, field, value)
    except ValueError as exc:
        err.print(str(exc))
        raise typer.Exit(1) from exc
    console.print(f"Set {field} for {doc.title} (source: human).")


@extract_app.command("status")
def extract_status_cmd():
    """Show extraction status for all papers."""
    from .extract import extraction_status

    rows = extraction_status(_store(_config()))
    if not rows:
        console.print("No papers in the library.")
        return
    table = Table(show_header=True, header_style="bold")
    table.add_column("id", width=8)
    table.add_column("title", overflow="fold")
    table.add_column("status")
    for doc, status in rows:
        color = {"extracted": "green", "partial": "yellow", "missing": "red"}[status]
        table.add_row(doc.id[:8], doc.title or "Untitled", f"[{color}]{status}[/]")
    console.print(table)


# ------------------------------------------------------------------- claims


@claim_app.command("add")
def claim_add(
    project: str = typer.Argument(..., help="Project name."),
    text: str = typer.Argument(..., help="Claim / outline statement."),
    notes: str = typer.Option(None, "--notes"),
):
    """Add a claim to a project outline."""
    from .claims import add_claim

    store = _store(_config())
    try:
        cid = add_claim(store, project, text, notes=notes)
    except ValueError as exc:
        err.print(str(exc))
        raise typer.Exit(1) from exc
    console.print(f"[green]Claim added[/] ({cid[:8]})")


@claim_app.command("list")
def claim_list(project: str = typer.Argument(...)):
    """List claims in outline order, with evidence counts."""
    from .claims import list_claims

    store = _store(_config())
    try:
        claims = list_claims(store, project)
    except ValueError as exc:
        err.print(str(exc))
        raise typer.Exit(1) from exc
    if not claims:
        console.print("No claims yet - add one with `rc claim add`.")
        return
    for c in claims:
        badge = f"[{c['evidence_count']} evidence]" if c["evidence_count"] else ""
        console.print(f"  {c['ordinal']}. {c['text']} {badge}  [dim]({c['id'][:8]})[/]")


@claim_app.command("show")
def claim_show(claim_ref: str = typer.Argument(..., help="Claim id or prefix.")):
    """Show a claim with its attached evidence."""
    store = _store(_config())
    claim = _resolve_claim_or_die(store, claim_ref)
    console.print(f"[bold]{claim['text']}[/]  ({claim['id'][:8]})")
    if claim["notes"]:
        console.print(f"  Notes: {claim['notes']}")
    if not claim["evidence"]:
        console.print("  [dim](no evidence attached)[/]")
    for ev in claim["evidence"]:
        page = f" p.{ev['page']}" if ev["page"] else ""
        console.print(
            f"  [{ev['stance']}] \"{ev['quote'][:80]}\" - {ev['document_title']}{page}"
        )


@claim_app.command("attach")
def claim_attach(
    claim_ref: str = typer.Argument(..., help="Claim id or prefix."),
    doc_ref: str = typer.Argument(..., help="Document id/prefix, DOI, or title."),
    quote: str = typer.Argument(..., help="Verbatim passage to attach."),
    page: int = typer.Option(None, help="Page number."),
    stance: str = typer.Option("supports", help="supports | contradicts | context"),
    note: str = typer.Option(None),
):
    """Attach a cited passage to a claim."""
    from .claims import attach_evidence

    store = _store(_config())
    doc = _resolve_or_die(store, doc_ref)
    claim = _resolve_claim_or_die(store, claim_ref)
    try:
        attach_evidence(store, claim["id"], doc.id, quote, page=page, stance=stance, note=note)
    except ValueError as exc:
        err.print(str(exc))
        raise typer.Exit(1) from exc
    console.print("[green]Evidence attached.[/]")


@claim_app.command("detach")
def claim_detach(evidence_id: str = typer.Argument(...)):
    """Remove evidence from a claim."""
    from .claims import detach_evidence

    detach_evidence(_store(_config()), evidence_id)
    console.print("Evidence detached.")


@claim_app.command("move")
def claim_move(
    claim_ref: str = typer.Argument(...),
    position: int = typer.Argument(..., help="New 0-based position in the outline."),
):
    """Reorder a claim within its project outline."""
    from .claims import move_claim

    store = _store(_config())
    claim = _resolve_claim_or_die(store, claim_ref)
    try:
        move_claim(store, claim["id"], position)
    except ValueError as exc:
        err.print(str(exc))
        raise typer.Exit(1) from exc
    console.print("Claim reordered.")


# --------------------------------------------------------------- ask/search


@app.command()
def ask(
    question: str = typer.Argument(..., help="Natural-language question."),
    scope: str = typer.Option("papers", help="papers | notes | all"),
    tag: str = typer.Option(None, help="Restrict to a tag."),
    status: str = typer.Option(None, help="Restrict to a lifecycle status."),
    project: str = typer.Option(None, help="Restrict to a project."),
    synthesize: bool = typer.Option(False, "--synthesize",
                                    help="Compare/contrast sources, flag contradictions."),
    gaps_topic: str = typer.Option(None, "--gaps",
                                   help="Report what the corpus does NOT cover on a topic."),
    k: int = typer.Option(0, help="Top-k chunks (0 = config default)."),
):
    """Ask your library a question; answers cite [n] sources."""
    from . import rag
    from .llm import LLMError, degraded_notice, get_adapter

    cfg = _config()
    store = _store(cfg)
    mode = "gaps" if gaps_topic else ("synthesize" if synthesize else "ask")
    query = gaps_topic or question
    gap_candidates = None
    if mode == "gaps":
        from .graph import gaps as graph_gaps

        gap_candidates = [s.title for s in graph_gaps(store, limit=10)] or None
    adapter = get_adapter(cfg)
    try:
        answer = rag.ask(
            store, _embedder(cfg), adapter, query,
            scope=scope, tag=tag, status=status, project=project,
            k=k or int(cfg.get("rag.top_k", 8)), mode=mode,
            gap_candidates=gap_candidates,
            retrieval=cfg.get("rag.retrieval", "dense"),
            do_rerank=cfg.get_bool("rag.rerank"),
        )
    except (LLMError, ValueError) as exc:
        err.print(str(exc))
        raise typer.Exit(1) from exc
    notice = degraded_notice(adapter)
    if notice:
        err.print(f"[yellow]?  {notice}[/]")
    console.print(answer.text)
    if answer.sources:
        console.print("\n[bold]Sources[/]")
        console.print(answer.render_sources())


@app.command()
def search(
    query: str = typer.Argument(...),
    scope: str = typer.Option("papers", help="papers | notes | all"),
    tag: str = typer.Option(None),
    status: str = typer.Option(None),
    project: str = typer.Option(None),
    k: int = typer.Option(0, help="Top-k chunks (0 = config default)."),
):
    """Retrieval only - show the top matching chunks, no generation."""
    from . import rag

    cfg = _config()
    retrieval_mode = cfg.get("rag.retrieval", "dense")
    do_rerank = cfg.get_bool("rag.rerank")
    try:
        hits = rag.search(_store(cfg), _embedder(cfg), query, scope=scope, tag=tag,
                          status=status, project=project,
                          k=k or int(cfg.get("rag.top_k", 8)),
                          retrieval=retrieval_mode, do_rerank=do_rerank)
    except ValueError as exc:
        err.print(str(exc))
        raise typer.Exit(1) from exc
    if not hits:
        console.print("No matches.")
        return
    for chunk, doc, score in hits:
        page = f" p.{chunk.page}" if chunk.page else ""
        console.print(f"[bold]{score:.3f}[/] {doc.title}{page} ({doc.id[:8]})")
        snippet = chunk.text[:300].replace("\n", " ")
        console.print(f"  [dim]{snippet}...[/]\n")


# ----------------------------------------------------------------------- kb


@kb_app.command("list")
def kb_list(
    status: str = typer.Option(None, help=f"Filter: {' | '.join(STATUSES)}"),
    tag: str = typer.Option(None),
    project: str = typer.Option(None),
    notes: bool = typer.Option(False, "--notes", help="List notes instead of papers."),
):
    """List papers grouped by lifecycle status (kanban-ish columns)."""
    store = _store(_config())
    collection = "notes" if notes else "papers"
    docs = store.list_documents(collection=collection, status=status, tag=tag,
                                project=project)
    if not docs:
        console.print("Nothing here yet.")
        return
    if notes or status:
        _print_doc_table(store, docs, show_status=not notes)
        return
    for column in STATUSES:
        group = [d for d in docs if d.status == column]
        if not group:
            continue
        console.print(f"\n[bold underline]{column}[/] ({len(group)})")
        _print_doc_table(store, group, show_status=False)


def _print_doc_table(store: Store, docs, show_status: bool = True):
    table = Table(show_header=True, header_style="bold")
    table.add_column("id", width=8)
    table.add_column("title", overflow="fold")
    table.add_column("year", width=5)
    if show_status:
        table.add_column("status")
    table.add_column("tags")
    for doc in docs:
        row = [doc.id[:8], doc.title or "Untitled", str(doc.year or "")]
        if show_status:
            row.append(doc.status or "")
        row.append(", ".join(store.document_tags(doc.id)))
        table.add_row(*row)
    console.print(table)


@kb_app.command("status")
def kb_status(ref: str = typer.Argument(..., help="Doc id/prefix, DOI, or title."),
              status: str = typer.Argument(..., help=" | ".join(STATUSES))):
    """Move a paper through the lifecycle: to-read -> reading -> annotated -> cited."""
    from .kb import set_status

    store = _store(_config())
    doc = _resolve_or_die(store, ref)
    try:
        set_status(store, doc, status)
    except ValueError as exc:
        err.print(str(exc))
        raise typer.Exit(1) from exc
    console.print(f"[green]{doc.title}[/] -> {status}")


@kb_app.command("tag")
def kb_tag(ref: str = typer.Argument(...),
           tags: list[str] = typer.Argument(..., help="Tag name(s).")):
    """Tag a document (papers or notes)."""
    store = _store(_config())
    doc = _resolve_or_die(store, ref)
    store.tag_document(doc.id, *tags)
    console.print(f"{doc.title}: {', '.join(store.document_tags(doc.id))}")


@kb_app.command("annotate")
def kb_annotate(ref: str = typer.Argument(...),
                text: str = typer.Argument(..., help="Highlight/note text."),
                page: int = typer.Option(None)):
    """Add an annotation to a paper (feeds flashcard generation)."""
    store = _store(_config())
    doc = _resolve_or_die(store, ref)
    store.add_annotation(doc.id, text, page=page)
    if doc.collection == "papers" and doc.status == "to-read":
        store.update_document(doc.id, status="annotated")
    console.print(f"Annotated {doc.title} ({len(store.annotations(doc.id))} total)")


@kb_app.command("show")
def kb_show(ref: str = typer.Argument(...)):
    """Show a document record: metadata, tags, annotations, schedule."""
    store = _store(_config())
    doc = _resolve_or_die(store, ref)
    console.print(f"[bold]{doc.title}[/]")
    console.print(f"  id: {doc.id}")
    console.print(f"  collection: {doc.collection}  status: {doc.status or '-'}")
    console.print(f"  authors: {', '.join(doc.authors) or '-'}")
    console.print(f"  year: {doc.year or '-'}  venue: {doc.venue or '-'}")
    console.print(f"  doi: {doc.doi or '-'}  openalex: {doc.openalex_id or '-'}")
    console.print(f"  tags: {', '.join(store.document_tags(doc.id)) or '-'}")
    console.print(f"  projects: {', '.join(store.document_projects(doc.id)) or '-'}")
    console.print(f"  chunks: {store.chunk_count(doc.id)}")
    annotations = store.annotations(doc.id)
    if annotations:
        console.print("  annotations:")
        for row in annotations:
            page = f" (p.{row['page']})" if row["page"] else ""
            badge = " [dim](ai)[/]" if row["source"] == "llm" else ""
            console.print(f"    -{badge} {row['text']}{page}")
    schedule = store.get_schedule(doc.id)
    if schedule:
        console.print(f"  review due: {schedule['due_date']}"
                      f" (ease {schedule['ease']:.2f}, reps {schedule['reps']})")


@kb_app.command("meta")
def kb_meta(
    ref: str = typer.Argument(..., help="Doc id/prefix, DOI, or title."),
    set_fields: list[str] = typer.Option(
        [], "--set", help="Fill a field manually: --set volume=30 --set pages=5998-6008"
    ),
):
    """Full citation record - missing fields show as -; fill them with --set."""
    from .meta import CITATION_FIELDS, missing_fields, set_field

    store = _store(_config())
    doc = _resolve_or_die(store, ref)
    for spec in set_fields:
        name, _, value = spec.partition("=")
        try:
            set_field(store, doc, name.strip(), value)
        except ValueError as exc:
            err.print(str(exc))
            raise typer.Exit(1) from exc
    if set_fields:
        doc = store.get_document(doc.id)
    console.print(f"[bold]{doc.title or 'Untitled'}[/]  ({doc.id[:8]})")
    for name in CITATION_FIELDS:
        if name == "title":
            continue
        value = getattr(doc, name)
        if name == "authors":
            value = ", ".join(value) if value else None
        elif name == "abstract" and value:
            value = value[:200] + ("..." if len(value) > 200 else "")
        shown = value if value else "[dim]-[/]"
        console.print(f"  {name:>17}: {shown}")
    gaps = missing_fields(doc)
    if gaps:
        console.print(
            f"\n[yellow]{len(gaps)} field(s) missing[/] ({', '.join(gaps)}) - try"
            " `rc kb backfill-meta` or fill manually with --set field=value"
        )


@kb_app.command("backfill-meta")
def kb_backfill_meta(
    ref: str = typer.Argument(None, help="One paper (default: every paper)."),
):
    """Re-resolve papers via OpenAlex/S2 and fill ONLY the missing fields.

    Never overwrites a non-empty field, so manual fixes always survive.
    """
    from .meta import backfill_document, missing_fields

    cfg = _config()
    store = _store(cfg)
    resolver = _resolver(cfg)
    docs = ([_resolve_or_die(store, ref)] if ref
            else store.list_documents(collection="papers"))
    for doc in docs:
        if not missing_fields(doc):
            console.print(f"[dim]complete[/]    {doc.title} ({doc.id[:8]})")
            continue
        result = backfill_document(store, resolver, doc)
        if result.filled:
            console.print(f"[green]backfilled[/]  {doc.title} ({doc.id[:8]}):"
                          f" {', '.join(result.filled)}")
        elif result.resolved:
            console.print(f"[dim]no new data[/] {doc.title} ({doc.id[:8]})")
        else:
            console.print(f"[yellow]unresolved[/]  {doc.title} ({doc.id[:8]})"
                          " - no API match (fill manually: `rc kb meta --set`)")


@kb_app.command("incomplete")
def kb_incomplete():
    """Papers missing core citation fields (authors/year/venue/item type)."""
    from .meta import incomplete_documents

    rows = incomplete_documents(_store(_config()))
    if not rows:
        console.print("Every paper has a complete core citation record.")
        return
    table = Table(show_header=True, header_style="bold")
    table.add_column("id", width=8)
    table.add_column("title", overflow="fold")
    table.add_column("missing")
    for doc, gaps in rows:
        table.add_row(doc.id[:8], doc.title or "Untitled", ", ".join(gaps))
    console.print(table)
    console.print("[dim]Fill via `rc kb backfill-meta` or `rc kb meta <ref> --set f=v`.[/]")


@kb_app.command("enrich")
def kb_enrich(
    ref: str = typer.Argument(..., help="Doc id/prefix, DOI, or title."),
    tags: bool = typer.Option(True, "--tags/--no-tags", help="Generate topical tags."),
    annotations: bool = typer.Option(True, "--annotations/--no-annotations",
                                     help="Generate study annotations."),
):
    """LLM-generate tags and study annotations for a paper (marked as AI-made)."""
    from .kb import generate_annotations, suggest_tags
    from .llm import LLMError, degraded_notice, get_adapter

    cfg = _config()
    store = _store(cfg)
    doc = _resolve_or_die(store, ref)
    adapter = get_adapter(cfg)
    try:
        if tags:
            new_tags = suggest_tags(store, adapter, doc)
            console.print(f"Tags: {', '.join(new_tags) or '(none generated)'}")
        if annotations:
            created = generate_annotations(store, adapter, doc)
            console.print(f"Added {len(created)} AI annotation(s):")
            for row in store.annotations(doc.id):
                if row["id"] in created:
                    console.print(f"  [dim](ai)[/] {row['text']}")
    except LLMError as exc:
        err.print(str(exc))
        raise typer.Exit(1) from exc
    notice = degraded_notice(adapter)
    if notice:
        err.print(f"[yellow]Notice:[/] {notice}")


# --------------------------------------------------------------------- review


@app.command()
def review(
    regenerate: bool = typer.Option(False, "--regenerate", help="Force new flashcards."),
):
    """Spaced-repetition session over due papers (SM-2 lite, grades 0-5)."""
    from .kb import ensure_flashcards, record_review, schedule_new
    from .llm import LLMError, degraded_notice, get_adapter

    cfg = _config()
    store = _store(cfg)
    # any annotated/cited paper not yet scheduled joins the queue
    for doc in store.list_documents(collection="papers"):
        if doc.status in ("annotated", "cited") and store.get_schedule(doc.id) is None:
            schedule_new(store, doc.id)
    due = store.due_documents()
    if not due:
        console.print("Nothing due for review.")
        return
    adapter = get_adapter(cfg)
    console.print(f"[bold]{len(due)} paper(s) due.[/]\n")
    for doc in due:
        console.print(f"[bold underline]{doc.title}[/] ({doc.year or 'n.d.'})")
        try:
            cards = ensure_flashcards(store, adapter, doc, regenerate=regenerate)
        except LLMError as exc:
            err.print(f"Flashcard generation failed: {exc}")
            cards = []
        notice = degraded_notice(adapter)
        if notice:
            err.print(f"[yellow]Notice:[/] {notice}")
        if not cards:
            console.print("[dim]No flashcards available; grade your overall recall.[/]")
        for card in cards:
            console.print(f"\n[bold]Q:[/] {card['question']}")
            typer.prompt("  (enter to reveal)", default="", show_default=False)
            console.print(f"[green]A:[/] {card['answer']}")
        grade = typer.prompt("Grade this paper 0-5 (0=blank, 5=perfect)", type=int)
        due_date = record_review(store, doc.id, grade)
        console.print(f"[dim]Next review: {due_date.isoformat()}[/]\n")


# ------------------------------------------------------------------------ bib


@bib_app.command("export")
def bib_export(
    output: Path = typer.Option(Path("refs.bib"), "-o", "--output"),
    tag: str = typer.Option(None),
    status: str = typer.Option(None, help="e.g. cited"),
    project: str = typer.Option(None),
):
    """Export papers matching the filters to a .bib file (LaTeX-importable)."""
    from .bib import export_bibtex

    text = export_bibtex(_store(_config()), tag=tag, status=status, project=project)
    output.write_text(text)
    entries = text.count("@")
    console.print(f"Wrote {entries} entrie(s) to {output}")


@bib_app.command("cite")
def bib_cite(
    style: str = typer.Option("apa", help="apa | mla | chicago | bibtex"),
    tag: str = typer.Option(None),
    status: str = typer.Option(None),
    project: str = typer.Option(None),
    ref: str = typer.Option(None, help="Cite a single document instead."),
):
    """Print formatted citations (APA, MLA, Chicago, or BibTeX for LaTeX)."""
    from .bib import format_citation, format_citations

    store = _store(_config())
    try:
        if ref:
            doc = _resolve_or_die(store, ref)
            console.print(format_citation(doc, style))
        else:
            text = format_citations(store, style, tag=tag, status=status, project=project)
            console.print(text or "No matching papers.")
    except ValueError as exc:
        err.print(str(exc))
        raise typer.Exit(1) from exc


@bib_app.command("import")
def bib_import(file: Path = typer.Argument(...)):
    """Seed paper records from a .bib file (metadata only, status to-read)."""
    from .bib import import_bibtex

    if not file.exists():
        err.print(f"Not found: {file}")
        raise typer.Exit(1)
    created = import_bibtex(_store(_config()), file.read_text())
    console.print(f"Imported {len(created)} record(s).")
    for doc in created:
        console.print(f"  {doc.id[:8]}  {doc.title}")


# ---------------------------------------------------------------------- graph


def _fetcher(cfg: Config):
    from .apis import OpenAlexClient, S2Client
    from .graph import EdgeFetcher

    return EdgeFetcher(
        OpenAlexClient(mailto=cfg.get("citations.mailto", "")),
        S2Client(api_key=cfg.get("citations.s2_api_key", "")),
    )


@graph_app.command("build")
def graph_build(seed: str = typer.Option(None, "--seed", help="Doc id/DOI (default: all papers)")):
    """Fetch references + cited-by edges from OpenAlex (S2 fallback)."""
    from .graph import build_graph

    cfg = _config()
    store = _store(cfg)
    seed_doc = _resolve_or_die(store, seed) if seed else None
    result = build_graph(store, _fetcher(cfg), seed=seed_doc)
    console.print(f"Fetched edges for {result.seeds} paper(s); {result.edges} edges upserted.")
    for title in result.skipped:
        console.print(f"  [yellow]skipped[/] {title} (no DOI/OpenAlex id)")


@graph_app.command("clusters")
def graph_clusters():
    """Community detection; prints clusters with sizes and representative titles."""
    from .graph import clusters as find_clusters
    from .graph import to_networkx

    g = to_networkx(_store(_config()))
    communities = find_clusters(g)
    if not communities:
        console.print("No graph yet - run `rc graph build` first.")
        return
    for i, community in enumerate(communities, 1):
        titles = [g.nodes[n].get("title", n) for n in community[:3]]
        console.print(f"[bold]Cluster {i}[/] ({len(community)} nodes)")
        for title in titles:
            console.print(f"  - {title}")


@graph_app.command("gaps")
def graph_gaps_cmd(limit: int = typer.Option(15)):
    """High-centrality papers not in your library (or unread) - reading suggestions."""
    from .graph import gaps

    suggestions = gaps(_store(_config()), limit=limit)
    if not suggestions:
        console.print("No suggestions - build the graph first.")
        return
    table = Table(show_header=True, header_style="bold")
    table.add_column("centrality", width=10)
    table.add_column("title", overflow="fold")
    table.add_column("why")
    for s in suggestions:
        table.add_row(f"{s.centrality:.4f}", s.title, s.reason)
    console.print(table)


@graph_app.command("export")
def graph_export(output: Path = typer.Option(..., "-o", "--output",
                                             help="*.graphml | *.dot | *.json")):
    """Export the citation graph for external tools."""
    from .graph import export_graph, to_networkx

    g = to_networkx(_store(_config()))
    try:
        export_graph(g, output)
    except ValueError as exc:
        err.print(str(exc))
        raise typer.Exit(1) from exc
    console.print(f"Wrote {g.number_of_nodes()} nodes / {g.number_of_edges()} edges to {output}")


# ------------------------------------------------------------------------- ui


@app.command()
def ui():
    """Launch the localhost Streamlit UI (binds 127.0.0.1 only, never 0.0.0.0)."""
    import subprocess
    import threading
    import webbrowser

    cfg = _config()
    app_path = Path(__file__).parent / "ui" / "app.py"
    port = str(cfg.get("ui.port", 8501))
    url = f"http://{cfg.ui_host}:{port}"
    argv = [
        sys.executable, "-m", "streamlit", "run", str(app_path),
        "--server.address", cfg.ui_host,  # loopback enforced in Config
        "--server.port", port,
        # headless skips Streamlit's first-run email prompt (which would
        # otherwise block the server); we open the browser ourselves
        "--server.headless", "true",
        "--browser.gatherUsageStats", "false",
        "--theme.base", "light",
        "--theme.primaryColor", "#4A5D45",
        "--theme.backgroundColor", "#F5F1E8",
        "--theme.secondaryBackgroundColor", "#FBF8F1",
        "--theme.textColor", "#2E2A24",
        "--theme.font", "serif",
    ]
    console.print(f"Research Cockpit UI: [bold]{url}[/] (Ctrl-C to stop)")
    threading.Timer(2.0, webbrowser.open, args=(url,)).start()
    try:
        raise typer.Exit(subprocess.call(argv))
    except FileNotFoundError as exc:
        err.print("Streamlit not installed - run: pip install 'research-cockpit[ui]'")
        raise typer.Exit(1) from exc


# --------------------------------------------------------------------- config


@config_app.command("show")
def config_show():
    """Print the effective config."""
    cfg = _config()
    for section, values in cfg.data.items():
        console.print(f"[bold]\\[{section}][/]")
        for key, val in values.items():
            console.print(f"  {key} = {val!r}")


@config_app.command("set")
def config_set(key: str = typer.Argument(..., help="Dotted key, e.g. llm.backend"),
               value: str = typer.Argument(...)):
    """Set a config value and save it."""
    cfg = _config()
    cfg.set(key, value)
    cfg.save()
    console.print(f"{key} = {cfg.get(key)!r}  [dim]({cfg.path})[/]")


if __name__ == "__main__":
    app()
