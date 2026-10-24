"""Knowledge base: paper lifecycle, spaced repetition (SM-2 lite), flashcards.

Paper-only features - everything here filters collection='papers'.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

from .llm import LLMAdapter, LLMError, extract_json_array
from .store import STATUSES, Document, Store, now_iso

TAG_SYSTEM = (
    "You label academic papers for a personal research library. Given a paper's"
    " title and excerpts, propose 3-6 topical tags: short, lowercase, 1-3 words"
    " each. Prefer reusing tags from the existing vocabulary when they fit."
    ' Respond with ONLY a JSON array of tag strings. No prose, no markdown fences.'
)

ANNOTATION_SYSTEM = (
    "You distill papers into study annotations for later review. Given excerpts"
    " from a paper, write 3-6 concise annotations capturing the key claims,"
    " methods, results, and limitations - the things worth remembering. Respond"
    ' with ONLY a JSON array of objects with keys "text" and optional "page"'
    " (integer, from the [p.N] markers when present). No prose, no fences."
)

FLASHCARD_SYSTEM = (
    "You write concise flashcards for spaced repetition. Given excerpts from a"
    " paper the user read, produce 3-6 question/answer cards that test recall"
    " of the key claims, methods, and results. Questions must be answerable"
    " from the excerpts alone. Respond with ONLY a JSON array of objects with"
    ' keys "question" and "answer". No prose, no markdown fences.'
)


def set_status(store: Store, doc: Document, status: str) -> None:
    if doc.collection != "papers":
        raise ValueError("Lifecycle status applies to papers only")
    if status not in STATUSES:
        raise ValueError(f"status must be one of {STATUSES}")
    store.update_document(doc.id, status=status)


# -------------------------------------------------------------- llm enrichment


def _excerpts(store: Store, doc: Document, max_chunks: int = 6, with_pages: bool = False) -> str:
    chunks = store.document_chunks(doc.id)[:max_chunks]
    if with_pages:
        return "\n\n".join(
            (f"[p.{c.page}] " if c.page else "") + c.text for c in chunks
        )
    return "\n\n".join(c.text for c in chunks)


def suggest_tags(
    store: Store, adapter: LLMAdapter, doc: Document, apply: bool = True
) -> list[str]:
    """Ask the LLM for topical tags; optionally apply them to the document."""
    excerpts = _excerpts(store, doc)
    if not excerpts and not doc.title:
        return []
    vocabulary = ", ".join(store.all_tags()) or "(none yet)"
    prompt = (
        f"Paper: {doc.title or 'Untitled'}"
        + (f" ({doc.year})" if doc.year else "")
        + f"\n\nExisting tag vocabulary: {vocabulary}"
        + f"\n\nExcerpts:\n\n{excerpts[:6000]}"
    )
    raw = adapter.generate(prompt, system=TAG_SYSTEM)
    items = extract_json_array(raw)
    if not items and "[" not in raw:  # prose instead of JSON (an empty [] is a valid "none")
        raise LLMError(f"tag suggestion returned no parseable JSON: {raw[:160]}")
    tags = []
    for item in items:
        name = str(item).strip().lower()
        if name and len(name) <= 40 and name not in tags:
            tags.append(name)
    tags = tags[:6]
    if apply and tags:
        store.tag_document(doc.id, *tags)
    return tags


def generate_annotations(store: Store, adapter: LLMAdapter, doc: Document) -> list[str]:
    """LLM-written study annotations, stored with source='llm' alongside the
    human ones (they feed flashcards/review the same way)."""
    excerpts = _excerpts(store, doc, with_pages=True)
    if not excerpts:
        return []
    prompt = (
        f"Paper: {doc.title or 'Untitled'}"
        + (f" ({doc.year})" if doc.year else "")
        + f"\n\nExcerpts:\n\n{excerpts[:8000]}"
    )
    raw = adapter.generate(prompt, system=ANNOTATION_SYSTEM)
    items = extract_json_array(raw)
    if not items and "[" not in raw:  # prose instead of JSON (an empty [] is a valid "none")
        raise LLMError(f"annotation generation returned no parseable JSON: {raw[:160]}")
    created = []
    existing = {r["text"] for r in store.annotations(doc.id)}
    for item in items:
        if not isinstance(item, dict):
            continue
        text = str(item.get("text", "")).strip()
        if not text or text in existing:
            continue
        page = item.get("page")
        page = int(page) if isinstance(page, (int, float)) else None
        created.append(store.add_annotation(doc.id, text, page=page, source="llm"))
    if created and doc.collection == "papers" and doc.status == "to-read":
        store.update_document(doc.id, status="annotated")
    return created


# ------------------------------------------------------------------ SM-2 lite


@dataclass
class ReviewState:
    ease: float = 2.5
    interval_days: float = 0
    reps: int = 0


def sm2_update(state: ReviewState, grade: int) -> ReviewState:
    """SM-2 lite. grade: 0-5; <3 resets the interval."""
    grade = max(0, min(5, grade))
    if grade < 3:
        reps, interval = 0, 1.0
    else:
        reps = state.reps + 1
        if reps == 1:
            interval = 1.0
        elif reps == 2:
            interval = 6.0
        else:
            interval = round(state.interval_days * state.ease)
    ease = max(1.3, state.ease + (0.1 - (5 - grade) * (0.08 + (5 - grade) * 0.02)))
    return ReviewState(ease=ease, interval_days=max(1.0, interval), reps=reps)


def schedule_new(store: Store, document_id: str, on: date | None = None) -> None:
    """Put a paper on the review queue, due immediately."""
    if store.get_schedule(document_id) is None:
        store.upsert_schedule(
            document_id, ease=2.5, interval_days=0, reps=0,
            due_date=(on or date.today()).isoformat(),
        )


def record_review(store: Store, document_id: str, grade: int, on: date | None = None) -> date:
    on = on or date.today()
    row = store.get_schedule(document_id)
    state = ReviewState(
        ease=row["ease"] if row else 2.5,
        interval_days=row["interval_days"] if row else 0,
        reps=row["reps"] if row else 0,
    )
    new = sm2_update(state, grade)
    due = on + timedelta(days=int(new.interval_days))
    store.upsert_schedule(
        document_id, ease=new.ease, interval_days=new.interval_days, reps=new.reps,
        due_date=due.isoformat(), last_reviewed=now_iso(),
    )
    return due


# ------------------------------------------------------------------ flashcards


def ensure_flashcards(
    store: Store, adapter: LLMAdapter, doc: Document, regenerate: bool = False
) -> list:
    """Return cached cards, generating from annotations (or top chunks) if needed.

    Cards are regenerated when the annotation set has changed since generation.
    """
    annotations = store.annotations(doc.id)
    cached = store.flashcards(doc.id)
    if cached and not regenerate:
        cached_sources = {r["source_annotation_id"] for r in cached} - {None}
        current = {r["id"] for r in annotations}
        if not annotations or cached_sources == current:
            return list(cached)

    if annotations:
        excerpts = "\n\n".join(f"- {r['text']}" for r in annotations)
        source_label = "annotations"
    else:
        chunks = store.document_chunks(doc.id)[:6]
        if not chunks:
            return []
        excerpts = "\n\n".join(c.text for c in chunks)
        source_label = "opening excerpts"

    prompt = (
        f"Paper: {doc.title or 'Untitled'}"
        + (f" ({doc.year})" if doc.year else "")
        + f"\n\nUser's {source_label}:\n\n{excerpts}"
    )
    raw = adapter.generate(prompt, system=FLASHCARD_SYSTEM)
    cards = []
    default_src = annotations[0]["id"] if annotations else None
    for item in extract_json_array(raw):
        q, a = str(item.get("question", "")).strip(), str(item.get("answer", "")).strip()
        if q and a:
            cards.append((q, a, default_src))
    if cards:
        store.replace_flashcards(doc.id, cards)
    return list(store.flashcards(doc.id))
