"""A store's own name for a book, kept through the import and never in `isbn`.

The two stores that decided this are measured on the browser side: the Kindle
for PC catalogue carries an ASIN on 1,032 of 1,032 entries and no ISBN anywhere,
and a Play Books Takeout carries a Google Books volume id and no ISBN either. So
what is pinned here is the round trip a member gets and the boundary that made
this a second field rather than a wider one.
"""

import settings_store
from enums import SettingKey
from models import Book, BookIdentifier
from routers.public import PUBLIC_PREFIX
from schemas import MAX_IDENTIFIERS_PER_BOOK

ASIN = "B00J4YQKHY"
VOLUME_ID = "zyTCAlFPjgYC"


def identifiers(book_id, db):
    """The stored rows, re-read.

    `expire_all` first, because this session is not the app's: a row it loaded
    before the request under test would otherwise come back from its identity
    map and hide a write the request rolled back.
    """
    db.expire_all()
    return (
        db.query(BookIdentifier)
        .filter(BookIdentifier.book_id == book_id)
        .order_by(BookIdentifier.id)
        .all()
    )


class TestAddingABookWithIdentifiers:
    def test_one_posted_with_a_book_is_stored_and_served_back(self, client, admin, db):
        res = client.post(
            "/api/books",
            json={
                "title": "Praxiswissen Docker",
                "identifiers": [{"scheme": "asin", "value": ASIN}],
            },
            headers=admin["headers"],
        )

        assert res.status_code == 201
        assert res.json()["identifiers"] == [{"scheme": "asin", "value": ASIN}]
        assert len(identifiers(res.json()["id"], db)) == 1

    def test_a_book_added_without_one_carries_none(self, client, admin, make_book):
        book = make_book(admin["headers"])
        res = client.get(f"/api/books/{book['id']}", headers=admin["headers"])

        assert res.json()["identifiers"] == []

    def test_a_book_may_carry_two_schemes_at_once(self, client, admin, db):
        """The case that decided a table over a nullable column."""
        res = client.post(
            "/api/books",
            json={
                "title": "Docker",
                "identifiers": [
                    {"scheme": "asin", "value": ASIN},
                    {"scheme": "google_books", "value": VOLUME_ID},
                ],
            },
            headers=admin["headers"],
        )

        assert res.status_code == 201
        assert len(identifiers(res.json()["id"], db)) == 2

    def test_the_same_identifier_twice_in_one_payload_becomes_one_row(
        self, client, admin, db
    ):
        """A member reading two of their own files may find one book in both,
        and two identical rows in one flush trip the unique index rather than
        the check before it."""
        res = client.post(
            "/api/books",
            json={
                "title": "Docker",
                "identifiers": [
                    {"scheme": "asin", "value": ASIN},
                    {"scheme": "asin", "value": ASIN},
                ],
            },
            headers=admin["headers"],
        )

        assert res.status_code == 201
        assert len(identifiers(res.json()["id"], db)) == 1

    def test_a_scheme_no_reader_produces_is_refused(self, client, admin):
        """A closed enum, so a client cannot invent one: an identifier under a
        scheme nothing reads is a row that lies."""
        res = client.post(
            "/api/books",
            json={
                "title": "Docker",
                "identifiers": [{"scheme": "kobo", "value": "abc"}],
            },
            headers=admin["headers"],
        )

        assert res.status_code == 422

    def test_more_than_the_ceiling_in_one_payload_is_refused(self, client, admin):
        """`max_length` on the field, which bounds one request. The per Book
        total is bounded by `identifiers.add_identifiers` instead, and
        `tests/test_identifiers.py` is where that half is pinned."""
        res = client.post(
            "/api/books",
            json={
                "title": "Docker",
                "identifiers": [
                    {"scheme": "asin", "value": f"B{index:09d}"}
                    for index in range(MAX_IDENTIFIERS_PER_BOOK + 1)
                ],
            },
            headers=admin["headers"],
        )

        assert res.status_code == 422


class TestAnIsbnLookupCannotBeGivenAnAsin:
    """The boundary this whole store exists to keep.

    `books.isbn` is the importer's match key and the lookup key, and every path
    into it check digits its input. A row carrying an ASIN there matches nothing
    and corrupts the deduplication for the rows that do.
    """

    def test_an_asin_posted_as_an_isbn_is_refused(self, client, admin):
        res = client.post(
            "/api/books",
            json={"title": "Docker", "isbn": ASIN},
            headers=admin["headers"],
        )

        assert res.status_code == 422

    def test_a_book_carrying_an_asin_carries_no_isbn(self, client, admin, db):
        """The identifier is stored beside the ISBN column, never into it, so a
        book whose store gave no ISBN still reads as having none."""
        res = client.post(
            "/api/books",
            json={
                "title": "Docker",
                "identifiers": [{"scheme": "asin", "value": ASIN}],
            },
            headers=admin["headers"],
        )

        assert res.json()["isbn"] is None
        assert db.get(Book, res.json()["id"]).isbn is None

    def test_two_books_may_share_an_identifier_where_they_could_not_share_an_isbn(
        self, client, admin
    ):
        """`uq_books_isbn_single_copy` answers 409 for a repeated ISBN, and this
        store deliberately does not: a second import of one library is the
        ordinary case, and the row that would collide is the one a member wants
        offered to `/duplicates` rather than refused."""
        first = client.post(
            "/api/books",
            json={
                "title": "Docker",
                "identifiers": [{"scheme": "asin", "value": ASIN}],
            },
            headers=admin["headers"],
        )
        second = client.post(
            "/api/books",
            json={
                "title": "Docker",
                "identifiers": [{"scheme": "asin", "value": ASIN}],
            },
            headers=admin["headers"],
        )

        assert first.status_code == 201
        assert second.status_code == 201


class TestAMergeMovesThem:
    def test_the_survivor_takes_the_losers_identifier(self, client, admin, db):
        keeper = client.post(
            "/api/books",
            json={
                "title": "Docker",
                "identifiers": [{"scheme": "asin", "value": ASIN}],
            },
            headers=admin["headers"],
        ).json()
        loser = client.post(
            "/api/books",
            json={
                "title": "Docker",
                "identifiers": [{"scheme": "google_books", "value": VOLUME_ID}],
            },
            headers=admin["headers"],
        ).json()

        res = client.post(
            "/api/books/merge",
            json={"book_ids": [keeper["id"], loser["id"]], "keep_id": keeper["id"]},
            headers=admin["headers"],
        )

        assert res.status_code == 200
        assert sorted(row.value for row in identifiers(keeper["id"], db)) == sorted(
            [ASIN, VOLUME_ID]
        )

    def test_two_differing_values_of_one_scheme_both_survive(self, client, admin, db):
        """The reason the unique index carries the value. Two Kindle entries a
        member declared the same book are two ASINs, and keying on the scheme
        alone would have made this an `IntegrityError` instead of a fact."""
        keeper = client.post(
            "/api/books",
            json={
                "title": "Docker",
                "identifiers": [{"scheme": "asin", "value": ASIN}],
            },
            headers=admin["headers"],
        ).json()
        loser = client.post(
            "/api/books",
            json={
                "title": "Docker",
                "identifiers": [{"scheme": "asin", "value": "B00OTHER01"}],
            },
            headers=admin["headers"],
        ).json()

        res = client.post(
            "/api/books/merge",
            json={"book_ids": [keeper["id"], loser["id"]], "keep_id": keeper["id"]},
            headers=admin["headers"],
        )

        assert res.status_code == 200
        assert len(identifiers(keeper["id"], db)) == 2

    def test_an_exact_repeat_is_dropped_rather_than_flushed_twice(
        self, client, admin, db
    ):
        """Two rows for one book are commonly two imports of one library, so
        this is the likely case rather than an edge: without the drop the flush
        trips `uq_book_identifiers_book_scheme_value` and the merge 500s."""
        keeper = client.post(
            "/api/books",
            json={
                "title": "Docker",
                "identifiers": [{"scheme": "asin", "value": ASIN}],
            },
            headers=admin["headers"],
        ).json()
        loser = client.post(
            "/api/books",
            json={
                "title": "Docker",
                "identifiers": [{"scheme": "asin", "value": ASIN}],
            },
            headers=admin["headers"],
        ).json()

        res = client.post(
            "/api/books/merge",
            json={"book_ids": [keeper["id"], loser["id"]], "keep_id": keeper["id"]},
            headers=admin["headers"],
        )

        assert res.status_code == 200
        assert len(identifiers(keeper["id"], db)) == 1

    def test_a_merge_cannot_carry_the_survivor_past_the_ceiling(
        self, client, admin, db
    ):
        """The merge is the second capped writer of this table and the larger
        hole if it is left out: `MergeRequest.book_ids` takes 20 books and
        carries no rate limiter, so an uncapped move is a stored write nobody
        bounded."""
        keeper = client.post(
            "/api/books",
            json={
                "title": "Docker",
                "identifiers": [
                    {"scheme": "asin", "value": f"B{index:09d}"}
                    for index in range(MAX_IDENTIFIERS_PER_BOOK)
                ],
            },
            headers=admin["headers"],
        ).json()
        loser = client.post(
            "/api/books",
            json={
                "title": "Docker",
                "identifiers": [{"scheme": "asin", "value": "B999999999"}],
            },
            headers=admin["headers"],
        ).json()

        res = client.post(
            "/api/books/merge",
            json={"book_ids": [keeper["id"], loser["id"]], "keep_id": keeper["id"]},
            headers=admin["headers"],
        )

        assert res.status_code == 200
        assert len(identifiers(keeper["id"], db)) == MAX_IDENTIFIERS_PER_BOOK
        assert "B999999999" not in {row.value for row in identifiers(keeper["id"], db)}


class TestPurgingABookTakesThem:
    def test_no_row_is_left_naming_a_book_nobody_holds(self, client, admin, db):
        book = client.post(
            "/api/books",
            json={
                "title": "Docker",
                "identifiers": [{"scheme": "asin", "value": ASIN}],
            },
            headers=admin["headers"],
        ).json()

        assert (
            client.delete(f"/api/books/{book['id']}", headers=admin["headers"]).status_code
            == 204
        )
        assert (
            client.delete(
                f"/api/books/{book['id']}/permanent", headers=admin["headers"]
            ).status_code
            == 204
        )
        assert identifiers(book["id"], db) == []


class TestTheyAreTheBooksVisibilityAndNothingElse:
    """A row carries no member, so its privacy is the Book's entirely. The
    Shelf is what applies that, and these two are the ends of it."""

    def test_another_members_private_book_discloses_none(self, client, admin, member):
        private = client.post(
            "/api/books",
            json={
                "title": "Docker",
                "is_private": True,
                "identifiers": [{"scheme": "asin", "value": ASIN}],
            },
            headers=admin["headers"],
        ).json()

        res = client.get(f"/api/books/{private['id']}", headers=member["headers"])

        assert res.status_code == 404

    def test_the_published_catalogue_carries_none(self, client, admin, db):
        """Withheld from `PublicBookOut` by the partition in
        `tests/schemas/test_public.py`, which is where the reason lives. This is
        the other half of it, asserted against the payload a reader with no
        account gets rather than against the model: the partition holds a field
        out of a class, and this holds it out of a response.

        **Both switches on**, which is the only state that serves anything: a
        404 here would pass this assertion while proving nothing.
        """
        book = client.post(
            "/api/books",
            json={
                "title": "Docker",
                "identifiers": [{"scheme": "asin", "value": ASIN}],
            },
            headers=admin["headers"],
        ).json()
        settings_store.set_value(db, SettingKey.LIBRARY_MODE, "true")
        settings_store.set_value(db, SettingKey.PUBLIC_CATALOGUE_ENABLED, "true")

        res = client.get(f"{PUBLIC_PREFIX}/books/{book['id']}")

        assert res.status_code == 200
        assert res.json()["title"] == "Docker"
        assert "identifiers" not in res.json()
