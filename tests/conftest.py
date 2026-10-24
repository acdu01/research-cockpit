from __future__ import annotations

import pytest

from research_cockpit.embed import HashEmbedder
from research_cockpit.store import Document, Store, new_id


@pytest.fixture
def store(tmp_path):
    s = Store(tmp_path / "test.db")
    yield s
    s.close()


@pytest.fixture
def embedder():
    return HashEmbedder(dim=128)


class FakeAdapter:
    """Deterministic LLM stand-in; records the prompts it saw."""

    def __init__(self, response: str = "The answer is X [1]."):
        self.response = response
        self.calls: list[tuple[str, str | None]] = []

    def generate(self, prompt: str, system: str | None = None) -> str:
        self.calls.append((prompt, system))
        return self.response


@pytest.fixture
def adapter():
    return FakeAdapter()


def make_paper(store: Store, title: str, **kwargs) -> Document:
    defaults = dict(collection="papers", status="to-read")
    defaults.update(kwargs)
    return store.add_document(Document(id=new_id(), title=title, **defaults))
