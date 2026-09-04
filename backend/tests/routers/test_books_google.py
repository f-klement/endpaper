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

import logging
from contextlib import contextmanager

import httpx
import pytest
import respx

from enums import SettingKey
from models import CATEGORIES_MAX, DESCRIPTION_MAX, TITLE_MAX, Classification
from routers.books import _bounded_match
from schemas import MAX_CLASSIFICATIONS_PER_BOOK
from tests.helpers import GOOGLE_BOOKS, K10PLUS, silence_catalogues, sru_response


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

    Enrichment reaches all nine sources now, so the rest have to be silenced
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

    def test_the_work_cluster_is_asked_with_the_books_own_isbn(
        self, client, admin, make_book, google_enabled
    ):
        """Other printings of this work, rather than a guess from the title.

        Open Library merges printings under a work and `/isbn/{isbn}.json` is
        the only handle on it, so this is the difference between the endpoint
        answering what a cataloguer asked and answering what a search engine
        thought they meant.
        """
        book = make_book(admin["headers"], isbn="9780262033848")
        with respx.mock(assert_all_called=False) as mock:
            cluster = mock.get(
                url__startswith="https://openlibrary.org/isbn/"
            ).mock(return_value=httpx.Response(404))
            silence_catalogues(mock)
            res = client.get(
                f"/api/books/{book['id']}/enrich/candidates",
                headers=admin["headers"],
            )

        assert res.status_code == 200
        assert cluster.called
        assert "9780262033848" in str(cluster.calls[0].request.url)

    def test_a_book_with_no_isbn_asks_no_cluster(
        self, client, admin, make_book, google_enabled
    ):
        """There is no handle on the work without one, and the search is the
        whole answer for that book."""
        book = make_book(admin["headers"])
        with respx.mock(assert_all_called=False) as mock:
            cluster = mock.get(
                url__startswith="https://openlibrary.org/isbn/"
            ).mock(return_value=httpx.Response(404))
            silence_catalogues(mock)
            res = client.get(
                f"/api/books/{book['id']}/enrich/candidates",
                headers=admin["headers"],
            )

        assert res.status_code == 200
        assert not cluster.called

    @staticmethod
    def _catalogue_record(headings: str) -> str:
        """One K10plus record for the book the test creates, plus `headings`."""
        return (
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<zs:searchRetrieveResponse xmlns:zs="http://www.loc.gov/zing/srw/">'
            "<zs:records><zs:record><zs:recordData>"
            '<record xmlns="http://www.loc.gov/MARC21/slim">'
            '<datafield tag="020"><subfield code="a">9783596294336</subfield>'
            "</datafield>"
            '<datafield tag="245"><subfield code="a">Der Zauberberg</subfield>'
            "</datafield>"
            '<datafield tag="100"><subfield code="a">Mann, Thomas</subfield>'
            '<subfield code="4">aut</subfield></datafield>'
            '<datafield tag="300"><subfield code="a">992 Seiten</subfield></datafield>'
            f"{headings}"
            "</record></zs:recordData></zs:record></zs:records>"
            "</zs:searchRetrieveResponse>"
        )

    def _candidates(self, client, admin, make_book, headings: str):
        book = make_book(
            admin["headers"], title="Der Zauberberg", author="Thomas Mann"
        )
        with respx.mock(assert_all_called=False) as mock:
            mock.get(url__startswith=K10PLUS).mock(
                return_value=sru_response(self._catalogue_record(headings))
            )
            silence_catalogues(mock)
            return client.get(
                f"/api/books/{book['id']}/enrich/candidates",
                headers=admin["headers"],
            )

    def test_a_record_over_the_heading_ceiling_does_not_lose_the_response(
        self, client, admin, make_book, google_enabled
    ):
        """This endpoint had no guard at all, where the search endpoint had one.

        `BookMatch` refuses a ninth heading and `main.py` has no
        `ValidationError` handler, so a record the schema refused answered 500
        for **every** candidate rather than costing one row. Measured over four
        live DNB searches on 2026-08-24: 8 of 189 records carry more than eight
        headings.
        """
        nine = "".join(
            f'<datafield tag="082"><subfield code="a">{100 + index}</subfield>'
            "</datafield>"
            for index in range(9)
        )
        res = self._candidates(client, admin, make_book, nine)

        assert res.status_code == 200
        assert len(res.json()[0]["classifications"]) == MAX_CLASSIFICATIONS_PER_BOOK

    def test_candidate_headings_are_evidence_not_a_book_write(
        self, client, admin, make_book, google_enabled, db
    ):
        book = make_book(
            admin["headers"], title="Der Zauberberg", author="Thomas Mann"
        )
        heading = '<datafield tag="082"><subfield code="a">004</subfield></datafield>'
        with respx.mock(assert_all_called=False) as mock:
            mock.get(url__startswith=K10PLUS).mock(
                return_value=sru_response(self._catalogue_record(heading))
            )
            silence_catalogues(mock)
            res = client.get(
                f"/api/books/{book['id']}/enrich/candidates",
                headers=admin["headers"],
            )

        assert res.status_code == 200
        assert res.json()[0]["classifications"] == [
            {"scheme": "ddc", "number": "004", "label": None}
        ]
        assert (
            db.query(Classification)
            .filter(Classification.book_id == book["id"])
            .count()
            == 0
        )

    def test_a_heading_the_column_could_not_hold_costs_the_heading(
        self, client, admin, make_book, google_enabled
    ):
        """The other half of the guard, which the count bound does not cover: a
        caption longer than the column is dropped rather than answered with."""
        long_caption = '<datafield tag="082"><subfield code="a">004 '
        long_caption += "x" * 400 + "</subfield></datafield>"
        res = self._candidates(client, admin, make_book, long_caption)

        assert res.status_code == 200
        assert res.json()[0]["classifications"] == []


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


@contextmanager
def only_google_answering(item: dict):
    """Google answers with one volume and every other catalogue holds nothing.

    The `google_search` fixture above with the volume chosen per test, which is
    what a bound needs: the value under test is the one the catalogue supplies.
    """
    with respx.mock(assert_all_called=False) as mock:
        mock.get(GOOGLE_BOOKS).mock(
            return_value=httpx.Response(200, json={"items": [item]})
        )
        silence_catalogues(mock)
        yield


def volume_with(**info) -> dict:
    """The standard volume with some of its `volumeInfo` replaced."""
    item = volume()
    item["volumeInfo"].update(info)
    return item


class TestACatalogueCannotWriteWhatTheColumnsRefuse:
    """`POST /{id}/enrich` writes what a catalogue answered, and it was the one
    route that bounded none of it.

    The threat model is not a hostile member, it is a hostile, compromised or
    merely broken upstream: every catalogue that answers here is somebody
    else's. Deliberately no count of them, because a roster sized number beside
    a roster noun is a number that rots, and `tests/test_roster_counts.py` took
    this docstring's first draft apart for carrying one.

    Until 2026-09-03 the ceilings on `BookMatch` applied to
    `POST /{id}/enrich/apply` and to neither half of this route, so the
    identical value was a 422 on one and a stored row on its neighbour.

    **The field is dropped, not the record.** A search page can lose a row and
    still answer; this route has the one record the catalogues returned, so
    refusing it whole would report `found=False` about a book they did find.
    """

    def test_a_series_index_past_the_ceiling_is_not_stored(
        self, client, admin, make_book, google_enabled
    ):
        """The sharp one. `list_series` computes `set(range(1, max + 1))` over
        this column for every member on every request, so a stored `1e9` is
        tens of gigabytes and tens of minutes until somebody finds the row.

        Reachable from a title alone: `_series_from_title` matches the shape
        below and calls `float()` on the digits, which is the same door
        `metadata._marc_title` opens from `245 $n`.
        """
        book = make_book(admin["headers"])

        with only_google_answering(
            volume_with(title="Dune (Dune Chronicles #1000000000)")
        ):
            res = client.post(
                f"/api/books/{book['id']}/enrich", headers=admin["headers"]
            )

        assert res.status_code == 200, res.text
        assert res.json()["found"] is True
        assert res.json()["book"]["series_index"] is None
        assert "series_index" not in res.json()["updated_fields"]

    def test_the_rest_of_the_record_still_lands(
        self, client, admin, make_book, google_enabled
    ):
        """Dropping the field rather than the record is the whole difference
        between this and `_match_rows`, so it is pinned rather than described.
        The series **name** is read off the same title as the refused index.
        """
        book = make_book(admin["headers"])

        with only_google_answering(
            volume_with(title="Dune (Dune Chronicles #1000000000)")
        ):
            res = client.post(
                f"/api/books/{book['id']}/enrich", headers=admin["headers"]
            )

        assert res.json()["book"]["page_count"] == 412
        assert res.json()["book"]["series_name"] == "Dune Chronicles"

    def test_a_series_index_the_column_holds_is_still_stored(
        self, client, admin, make_book, google_enabled
    ):
        """The diagonal. A guard that refuses everything is not a guard, and
        1000 is the ceiling itself rather than a value comfortably under it.
        """
        book = make_book(admin["headers"])

        with only_google_answering(volume_with(title="Dune (Dune Chronicles #1000)")):
            res = client.post(
                f"/api/books/{book['id']}/enrich", headers=admin["headers"]
            )

        assert res.json()["book"]["series_index"] == 1000
        assert "series_index" in res.json()["updated_fields"]

    def test_categories_past_the_column_are_dropped_and_the_book_still_fills(
        self, client, admin, make_book, google_enabled
    ):
        """`CATEGORIES_MAX` is read in one place, `BookMatch.categories`, and
        this route did not pass through it. Nothing caps the subject list
        upstream: `metadata._OPEN_LIBRARY_MAX_SUBJECTS` is the only slice in
        that module, and the lookup fold unions two records' subjects.
        """
        book = make_book(admin["headers"])

        with only_google_answering(
            volume_with(categories=["s" * (CATEGORIES_MAX + 1)])
        ):
            res = client.post(
                f"/api/books/{book['id']}/enrich", headers=admin["headers"]
            )

        assert res.status_code == 200, res.text
        assert res.json()["book"]["categories"] == []
        assert res.json()["book"]["page_count"] == 412

    def test_categories_the_column_holds_are_still_stored(
        self, client, admin, make_book, google_enabled
    ):
        """The other half of the diagonal, at the ceiling rather than under it."""
        book = make_book(admin["headers"])

        with only_google_answering(volume_with(categories=["s" * CATEGORIES_MAX])):
            res = client.post(
                f"/api/books/{book['id']}/enrich", headers=admin["headers"]
            )

        assert res.json()["book"]["categories"] == ["s" * CATEGORIES_MAX]


class TestTheTwoRoutesAgreeAboutOneVolume:
    """The asymmetry `_match_rows` used to document, closed one layer down.

    That docstring recorded it as measured: on one volume with a 10,001
    character description, `GET /{id}/enrich/candidates` answered with **0**
    candidates while `POST /{id}/enrich` filled the rest of the record from the
    same volume, so the unattended route stored a record the picker would not
    show. `catalogue.Record` now clears a scalar its column cannot hold at
    construction, so neither route sees the value and both see the rest.
    """

    def test_a_description_no_column_can_hold_costs_the_field_not_the_candidate(
        self, client, admin, make_book, google_enabled
    ):
        book = make_book(admin["headers"])

        with only_google_answering(
            volume_with(description="d" * (DESCRIPTION_MAX + 1))
        ):
            res = client.get(
                f"/api/books/{book['id']}/enrich/candidates",
                headers=admin["headers"],
            )

        assert res.status_code == 200
        assert len(res.json()) == 1
        assert res.json()[0]["description"] is None
        assert res.json()[0]["page_count"] == 412

    def test_the_other_route_fills_the_same_book_from_the_same_volume(
        self, client, admin, make_book, google_enabled
    ):
        """The half that always worked, asserted beside the half that did not,
        because the finding was the disagreement rather than either answer."""
        book = make_book(admin["headers"])

        with only_google_answering(
            volume_with(description="d" * (DESCRIPTION_MAX + 1))
        ):
            res = client.post(
                f"/api/books/{book['id']}/enrich", headers=admin["headers"]
            )

        assert res.json()["found"] is True
        assert res.json()["book"]["description"] is None
        assert res.json()["book"]["page_count"] == 412

    def test_a_title_no_column_can_hold_still_costs_the_whole_search_row(
        self, client, admin, make_book, google_enabled
    ):
        """A second field, because a guard proved on one is then trusted for
        the ones beside it, and this one does **not** behave like the first.

        `BookMatch.title` is optional, so the schema would accept the row. It
        never reaches the schema: `metadata._merge_matches` skips a record with
        no title, because a search result nobody can read is not a result. So
        the answer here is 0 and the reason is a rule that has nothing to do
        with a ceiling.
        """
        book = make_book(admin["headers"])

        with only_google_answering(volume_with(title="t" * (TITLE_MAX + 1))):
            res = client.get(
                f"/api/books/{book['id']}/enrich/candidates",
                headers=admin["headers"],
            )

        assert res.status_code == 200
        assert res.json() == []

    def test_the_two_routes_agree_about_a_title_they_cannot_read_either(
        self, client, admin, make_book, google_enabled
    ):
        """Both routes read the same merged list, so the titleless row is
        missing from both rather than from one, which is the property this
        class is named for."""
        book = make_book(admin["headers"])

        with only_google_answering(volume_with(title="t" * (TITLE_MAX + 1))):
            res = client.post(
                f"/api/books/{book['id']}/enrich", headers=admin["headers"]
            )

        assert res.json()["found"] is False


class TestBoundingOneRecord:
    """`routers.books._bounded_match`, the door that route now goes through.

    Its policy is per field where its neighbour `_match_rows` is per row, and
    the two disagree in a way a member can see: a record the picker refuses to
    show whole is a record the unattended route still fills a Book from.
    Measured, and filed rather than resolved here. These drive the arms the
    route tests above cannot reach from outside.
    """

    def test_a_clean_record_arrives_whole(self):
        match = _bounded_match({"title": "Dune", "page_count": 412, "year": 1965})

        assert (match.title, match.page_count, match.year) == ("Dune", 412, 1965)

    def test_only_the_refused_field_is_dropped(self):
        match = _bounded_match({"title": "Dune", "series_index": 1e9})

        assert match.title == "Dune"
        assert match.series_index is None

    def test_two_refused_fields_are_both_dropped(self):
        """Pydantic collects every field error in one pass, so this costs one
        iteration rather than two. Pinned anyway, because the loop's
        termination argument does not rest on that and a reader should not have
        to assume it.
        """
        match = _bounded_match({"title": "Dune", "series_index": 1e9, "year": 99999})

        assert match.title == "Dune"
        assert match.series_index is None
        assert match.year is None

    def test_a_refusal_naming_no_field_gives_up_on_the_record(
        self, monkeypatch, caplog
    ):
        """The arm there is nothing to drop for.

        `BookMatch` carries no model level validator today, which is exactly
        why this drives one in rather than asserting the arm is there.
        Measured: pydantic reports a `mode="after"` model validator's error at
        `loc == ()`, where a field error reports `loc == ("title",)`.

        The log is what separates this arm from the loop simply running out,
        which the bound makes it do to the same value. Without the early exit
        the record is reported as a dropped field, repeatedly, naming none.
        """
        from pydantic import BaseModel, Field, model_validator

        import routers.books as books_router

        class Stub(BaseModel):
            title: str | None = Field(default=None, max_length=500)

            @model_validator(mode="after")
            def _refuse_shouting(self):
                if self.title == "SHOUT":
                    raise ValueError("not that one")
                return self

        monkeypatch.setattr(books_router, "BookMatch", Stub)

        with caplog.at_level(logging.INFO, logger="endpaper.books"):
            assert books_router._bounded_match({"title": "SHOUT"}).title is None

        assert "Discarded" in caplog.text
        assert "Dropped" not in caplog.text
        assert books_router._bounded_match({"title": "Dune"}).title == "Dune"

    def test_a_record_whose_every_field_is_refused_is_not_a_discard(self, caplog):
        """The pass the loop bound's `+ 1` exists for.

        Every pass deletes at least one key, so a record of one refused field
        needs a second pass to answer with the empty match. A bound of exactly
        one pass per key falls through to the fallback instead and reaches the
        same value, so only the log tells the two apart: this record was read
        and stripped, it was not refused whole.
        """
        with caplog.at_level(logging.INFO, logger="endpaper.books"):
            match = _bounded_match({"series_index": 1e9})

        assert match.series_index is None
        assert "series_index" in caplog.text
        assert "Discarded" not in caplog.text

    def test_a_field_the_record_never_supplied_is_not_deleted_from_it(
        self, monkeypatch
    ):
        """The arm the first mutation round missed, under its right name.

        Pydantic reports a **missing** required field at a `loc` naming a key
        the record never sent, so without intersecting the refused names with
        the record's own keys the helper deletes a key that is not there.
        Measured on a stub carrying one required field: `Req(title="x" * 10)`
        reports `[('name',), ('title',)]`, only the second of which is in the
        record, and removing the intersection raises `KeyError: 'name'`.

        **It is a `KeyError`, not a stall**, which is what this test was called
        after for one round. There is no shape that repeats a pass: a refused
        set either meets the record, in which case the record shrinks, or it
        does not, in which case the old code raised.

        The same stub drives the give up arm, which is why they are one test:
        with `name` required, `Req()` raises too, so a fallback that validated
        would answer 500 on the one path that exists to avoid one.
        """
        from pydantic import BaseModel, Field

        import routers.books as books_router

        class Req(BaseModel):
            name: str
            title: str | None = Field(default=None, max_length=5)

        monkeypatch.setattr(books_router, "BookMatch", Req)

        match = books_router._bounded_match({"title": "far too long"})

        assert match.title is None

    def test_the_empty_match_is_what_the_fallback_builds(self):
        """`model_construct` skips validation, so it is worth pinning that it
        still produces the model `BookMatch()` produces rather than something
        emptier. If a required field is ever added the two stop agreeing, and
        this is where that shows up."""
        from schemas import BookMatch

        assert BookMatch.model_construct() == BookMatch()

    def test_it_says_what_it_dropped(self, caplog):
        """A dropped field is invisible in the response by design, so the log
        is where it is recorded. INFO, like `_match_rows`.
        """
        with caplog.at_level(logging.INFO, logger="endpaper.books"):
            _bounded_match({"source": "dnb", "title": "Dune", "series_index": 1e9})

        assert "series_index" in caplog.text
        assert "dnb" in caplog.text
