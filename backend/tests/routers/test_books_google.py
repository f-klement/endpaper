"""Tests for the Google Books surfaces on backend/routers/books.py.

Two endpoints share one gate (`_require_google_books`) and one upstream:

  POST /api/books/{id}/enrich              fill this book's gaps
  GET  /api/books/{id}/enrich/candidates   other editions of this book

Free-text search used to be a third and is not any more: it answers without a
key now, so it has neither this gate nor this upstream on its own. Its tests
are in `test_books_search.py`.

Every outbound call is intercepted with respx, so the suite never touches the
network and never needs a real API key.
"""

import httpx
import pytest
import respx

from enums import SettingKey
from tests.helpers import GOOGLE_BOOKS, silence_catalogues


def volume(
    volume_id: str = "abc123",
    title: str = "Dune",
    *,
    categories: list[str] | None = None,
    page_count: int | None = 412,
    isbn13: str | None = "9780441013593",
) -> dict:
    """One item as Google returns it, trimmed to the fields we read."""
    info: dict = {
        "title": title,
        "subtitle": "A Novel",
        "authors": ["Frank Herbert"],
        "publisher": "Chilton",
        "publishedDate": "1965-08-01",
        "description": "Desert planet politics.",
        "language": "en",
        "imageLinks": {"thumbnail": "https://books.google.com/thumb.jpg"},
    }
    if categories is not None:
        info["categories"] = categories
    if page_count is not None:
        info["pageCount"] = page_count
    if isbn13 is not None:
        info["industryIdentifiers"] = [{"type": "ISBN_13", "identifier": isbn13}]
    return {"id": volume_id, "volumeInfo": info}


@pytest.fixture
def google_enabled(client, admin):
    """Switch the feature on and store a key, as an admin would in Settings."""
    client.put(
        "/api/settings",
        json={"google_books_enabled": True, "google_books_api_key": "test-key"},
        headers=admin["headers"],
    )


@pytest.fixture
def google_search():
    """Google answers with one volume; every other catalogue holds nothing.

    Enrichment reaches all six sources now, so the rest have to be silenced
    for a test to prove that Google's answer is the one that landed.
    """
    with respx.mock(assert_all_called=False) as mock:
        mock.get(GOOGLE_BOOKS).mock(
            return_value=httpx.Response(200, json={"items": [volume()]})
        )
        yield silence_catalogues(mock)


class TestEnrichBook:
    def test_fills_the_gaps(self, client, admin, make_book, google_enabled, google_search):
        book = make_book(admin["headers"])

        res = client.post(f"/api/books/{book['id']}/enrich", headers=admin["headers"])

        assert res.status_code == 200
        assert res.json()["found"] is True
        assert res.json()["book"]["page_count"] == 412

    def test_reports_which_fields_changed(
        self, client, admin, make_book, google_enabled, google_search
    ):
        """A run that finds the volume but adds nothing is the common case."""
        book = make_book(admin["headers"])

        first = client.post(f"/api/books/{book['id']}/enrich", headers=admin["headers"]).json()
        second = client.post(f"/api/books/{book['id']}/enrich", headers=admin["headers"]).json()

        assert "page_count" in first["updated_fields"]
        assert second["found"] is True
        assert second["updated_fields"] == []

    def test_does_not_overrule_a_typed_value(
        self, client, admin, make_book, google_enabled, google_search
    ):
        # Somebody corrected the publisher by hand. Upstream does not win.
        book = make_book(admin["headers"], publisher="Ace Books")

        res = client.post(f"/api/books/{book['id']}/enrich", headers=admin["headers"])

        assert res.json()["book"]["publisher"] == "Ace Books"

    def test_another_members_private_book_is_not_enrichable(
        self, client, admin, member, make_book, google_enabled, google_search
    ):
        book = make_book(admin["headers"], is_private=True)

        res = client.post(f"/api/books/{book['id']}/enrich", headers=member["headers"])

        assert res.status_code == 404

    def test_requires_authentication(self, client, admin, make_book, google_enabled):
        book = make_book(admin["headers"])
        assert client.post(f"/api/books/{book['id']}/enrich").status_code == 401


class TestEnrichmentCandidates:
    def test_offers_other_editions(
        self, client, admin, make_book, google_enabled, google_search
    ):
        book = make_book(admin["headers"])

        res = client.get(
            f"/api/books/{book['id']}/enrich/candidates", headers=admin["headers"]
        )

        assert res.status_code == 200
        assert res.json()[0]["title"] == "Dune"

    def test_does_not_suggest_tags(
        self, client, admin, make_book, google_enabled, google_search
    ):
        """The book already has tags, and they are somebody's deliberate choice."""
        book = make_book(admin["headers"])

        res = client.get(
            f"/api/books/{book['id']}/enrich/candidates", headers=admin["headers"]
        )

        assert res.json()[0]["suggested_tag_ids"] == []

    def test_another_members_private_book_is_invisible(
        self, client, admin, member, make_book, google_enabled, google_search
    ):
        book = make_book(admin["headers"], is_private=True)

        res = client.get(
            f"/api/books/{book['id']}/enrich/candidates", headers=member["headers"]
        )

        assert res.status_code == 404


class TestCategoriesSerialisation:
    """`categories` is one string in the database and a list on the wire."""

    def test_served_as_a_list(self, client, admin, make_book, google_enabled):
        with respx.mock(assert_all_called=False) as mock:
            mock.get(GOOGLE_BOOKS).mock(
                return_value=httpx.Response(
                    200, json={"items": [volume(categories=["Fiction", "Fantasy"])]}
                )
            )
            silence_catalogues(mock)
            book = make_book(admin["headers"])
            client.post(f"/api/books/{book['id']}/enrich", headers=admin["headers"])

        res = client.get(f"/api/books/{book['id']}", headers=admin["headers"])

        assert res.json()["categories"] == ["Fiction", "Fantasy"]

    def test_a_comma_inside_a_category_is_not_split(
        self, client, admin, make_book, google_enabled
    ):
        with respx.mock(assert_all_called=False) as mock:
            mock.get(GOOGLE_BOOKS).mock(
                return_value=httpx.Response(
                    200, json={"items": [volume(categories=["Fiction, general"])]}
                )
            )
            silence_catalogues(mock)
            book = make_book(admin["headers"])
            client.post(f"/api/books/{book['id']}/enrich", headers=admin["headers"])

        res = client.get(f"/api/books/{book['id']}", headers=admin["headers"])

        assert res.json()["categories"] == ["Fiction, general"]

    def test_a_book_with_no_categories_gets_an_empty_list(self, client, admin, make_book):
        # Not null: a client that has to handle both an absent list and an
        # empty one will eventually handle one of them wrong.
        book = make_book(admin["headers"])

        assert client.get(f"/api/books/{book['id']}", headers=admin["headers"]).json()[
            "categories"
        ] == []


class TestKeyHandling:
    def test_the_stored_key_is_sent_to_google(
        self, client, admin, make_book, google_enabled
    ):
        book = make_book(admin["headers"])
        with respx.mock(assert_all_called=False) as mock:
            route = mock.get(GOOGLE_BOOKS).mock(
                return_value=httpx.Response(200, json={"items": []})
            )
            silence_catalogues(mock)

            client.post(f"/api/books/{book['id']}/enrich", headers=admin["headers"])

        assert route.calls.last.request.url.params["key"] == "test-key"

    def test_the_key_is_stored_unmasked(self, client, admin, google_enabled, db):
        """The masking in SettingsOut is presentation, not storage.

        Worth pinning: masking the stored value instead of the response would
        break every lookup while still looking right in the settings screen.
        """
        import settings_store

        assert (
            settings_store.get_raw(db, SettingKey.GOOGLE_BOOKS_API_KEY) == "test-key"
        )


class TestApplyingAChosenEdition:
    """Nothing is written until somebody says which printing it is."""

    def choice(self, **overrides) -> dict:
        base = {
            "source": "open_library",
            "google_books_id": "abc123",
            "title": "Dune",
            "subtitle": "A Novel",
            "author": "Frank Herbert",
            "publisher": "Chilton",
            "year": 1965,
            "description": "Desert planet politics.",
            "page_count": 412,
            "language": "en",
            "categories": None,
            "cover_url": "https://example.test/cover.jpg",
            "isbn13": "9780441013593",
            "series_name": None,
            "series_index": None,
            "suggested_tag_ids": [],
        }
        return {**base, **overrides}

    def test_fills_the_gaps_from_the_chosen_edition(self, client, admin, make_book):
        book = make_book(admin["headers"])

        res = client.post(
            f"/api/books/{book['id']}/enrich/apply",
            json=self.choice(),
            headers=admin["headers"],
        )

        assert res.status_code == 200
        assert res.json()["book"]["page_count"] == 412
        assert set(res.json()["updated_fields"]) >= {"page_count", "publisher"}

    def test_writes_nothing_upstream(self, client, admin, make_book):
        """No catalogue is called: the caller already has the record."""
        book = make_book(admin["headers"])
        with respx.mock(assert_all_called=False) as mock:
            silence_catalogues(mock)
            client.post(
                f"/api/books/{book['id']}/enrich/apply",
                json=self.choice(),
                headers=admin["headers"],
            )
            assert not any(route.called for route in mock.routes)

    def test_does_not_overrule_a_typed_value(self, client, admin, make_book):
        book = make_book(admin["headers"], title="Dune", author="Somebody Else")

        client.post(
            f"/api/books/{book['id']}/enrich/apply",
            json=self.choice(),
            headers=admin["headers"],
        )

        res = client.get(f"/api/books/{book['id']}", headers=admin["headers"])
        assert res.json()["author"] == "Somebody Else"

    def test_overwrite_replaces_a_stored_value(self, client, admin, make_book):
        book = make_book(admin["headers"], author="Somebody Else")

        client.post(
            f"/api/books/{book['id']}/enrich/apply",
            params={"overwrite": True},
            json=self.choice(),
            headers=admin["headers"],
        )

        res = client.get(f"/api/books/{book['id']}", headers=admin["headers"])
        assert res.json()["author"] == "Frank Herbert"

    def test_never_takes_the_isbn(self, client, admin, make_book):
        """It is unique, and a chosen printing's ISBN is not this copy's."""
        book = make_book(admin["headers"], isbn=None)

        client.post(
            f"/api/books/{book['id']}/enrich/apply",
            json=self.choice(),
            headers=admin["headers"],
        )

        res = client.get(f"/api/books/{book['id']}", headers=admin["headers"])
        assert res.json()["isbn"] is None

    def test_another_members_private_book_is_not_found(
        self, client, admin, member, make_book
    ):
        private = make_book(member["headers"], is_private=True)

        res = client.post(
            f"/api/books/{private['id']}/enrich/apply",
            json=self.choice(),
            headers=admin["headers"],
        )

        assert res.status_code == 404

    def test_requires_authentication(self, client, admin, make_book):
        book = make_book(admin["headers"])
        res = client.post(
            f"/api/books/{book['id']}/enrich/apply", json=self.choice()
        )
        assert res.status_code == 401


class TestAnEnrichmentBodyCannotOverflowTheDatabase:
    """`POST /{id}/enrich/apply` takes a `BookMatch` as its body, and
    `merge_into` writes `year` and `page_count` onto the book. Unbounded, a
    value past SQLite's INTEGER raises `OverflowError` on the commit: a 500 for
    any member, from a plain JSON field.

    Found by `tests/test_house_rules.py::TestEveryRequestBodyRowIdIsBounded`
    rather than by a person, which is the point of that lint.
    """

    TOO_BIG = 9_223_372_036_854_775_808

    def test_an_absurd_year_is_refused(self, client, admin, make_book):
        book = make_book(admin["headers"], title="Dune")

        res = client.post(
            f"/api/books/{book['id']}/enrich/apply",
            json={"title": "Dune", "year": self.TOO_BIG},
            headers=admin["headers"],
        )

        assert res.status_code == 422, res.text

    def test_an_absurd_page_count_is_refused(self, client, admin, make_book):
        book = make_book(admin["headers"], title="Dune")

        res = client.post(
            f"/api/books/{book['id']}/enrich/apply",
            json={"title": "Dune", "page_count": self.TOO_BIG},
            headers=admin["headers"],
        )

        assert res.status_code == 422, res.text
