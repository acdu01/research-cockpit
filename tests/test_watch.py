"""M16: new-paper watchlists - CRUD + mock poll."""

from __future__ import annotations

from unittest import mock

from research_cockpit.watch import (
    add_watchlist,
    list_watchlists,
    poll,
    remove_watchlist,
)


def test_watchlist_crud(store):
    wid = add_watchlist(store, "topic", "parchment conservation")
    wl = list_watchlists(store)
    assert len(wl) == 1 and wl[0]["kind"] == "topic"
    remove_watchlist(store, wid)
    assert list_watchlists(store) == []


def test_poll_creates_toread_records(store):
    add_watchlist(store, "topic", "cockling", name="cockling-watch")

    fake_response = {
        "results": [
            {
                "id": "https://openalex.org/W999",
                "display_name": "New Cockling Study",
                "publication_year": 2025,
                "doi": "https://doi.org/10.9999/new.cockling",
                "authorships": [{"author": {"display_name": "New Author"}}],
                "primary_location": {"source": {"display_name": "Journal of Codex"}},
            }
        ]
    }

    class FakeClient:
        params = {}
        client = mock.Mock()

        @staticmethod
        def _parse_work(work):
            from research_cockpit.apis import OpenAlexClient
            return OpenAlexClient._parse_work(work)

    with mock.patch("research_cockpit.watch._get_with_backoff", return_value=fake_response):
        created = poll(store, client=FakeClient())

    assert len(created) == 1
    assert created[0].title == "New Cockling Study"
    assert created[0].status == "to-read"
    assert "watch:cockling-watch" in store.document_tags(created[0].id)
    # second poll is idempotent
    with mock.patch("research_cockpit.watch._get_with_backoff", return_value=fake_response):
        assert poll(store, client=FakeClient()) == []


def test_poll_dedupes_existing_library(store):
    from conftest import make_paper
    make_paper(store, "Already Here", doi="10.9999/existing")
    add_watchlist(store, "doi", "10.9999/existing")
    fake = {"results": [{
        "id": "https://openalex.org/W888",
        "display_name": "Already Here",
        "doi": "https://doi.org/10.9999/existing",
        "authorships": [],
        "primary_location": {},
    }]}

    class FakeClient:
        params = {}
        client = mock.Mock()

        @staticmethod
        def _parse_work(work):
            from research_cockpit.apis import OpenAlexClient
            return OpenAlexClient._parse_work(work)

    with mock.patch("research_cockpit.watch._get_with_backoff", return_value=fake):
        assert poll(store, client=FakeClient()) == []


def test_overlapping_watchlists_dedupe_papers_without_dois(store):
    add_watchlist(store, "topic", "conservation")
    add_watchlist(store, "topic", "parchment")
    work = {"id": "https://openalex.org/W999", "display_name": "No DOI paper"}
    from research_cockpit.apis import OpenAlexClient

    client = mock.Mock(params={}, _parse_work=OpenAlexClient._parse_work)
    with mock.patch(
        "research_cockpit.watch._get_with_backoff", return_value={"results": [work]}
    ):
        assert len(poll(store, client)) == 1
        assert poll(store, client) == []
    assert len(store.list_documents()) == 1
