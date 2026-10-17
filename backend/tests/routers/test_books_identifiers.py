"""A store's own name for a book, kept through the import and never in `isbn`.

The two stores that decided this are measured on the browser side: the Kindle
for PC catalogue carries an ASIN on 1,032 of 1,032 entries and no ISBN anywhere,
and a Play Books Takeout carries a Google Books volume id and no ISBN either. So
what is pinned here is the round trip a member gets and the boundary that made
this a second field rather than a wider one.
"""

from sqlalchemy import event

import settings_store
from database import engine
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
        [served] = res.json()["identifiers"]
        assert (served["scheme"], served["value"]) == ("asin", ASIN)
        [stored] = identifiers(res.json()["id"], db)
        # The row id is served because it is what the delete route is addressed
        # by, and asserting it against the row is what says the client is given
        # this row's address rather than a number.
        assert served["id"] == stored.id

    def test_the_scan_route_stores_them_too(self, client, admin, db):
        """Both adding routes, because they share `_create_book` and the prose
        kept saying one.

        `POST /api/books/scan` is the route the store import actually posts to,
        and three files plus a published OpenAPI description said identifiers
        were written only by `POST /api/books`. A count of routes stated in
        prose is a count nobody was checking, so it is a test now. Found by the
        security seat.
        """
        res = client.post(
            "/api/books/scan",
            json={
                "title": "Praxiswissen Docker",
                "identifiers": [{"scheme": "asin", "value": ASIN}],
            },
            headers=admin["headers"],
        )

        assert res.status_code == 201
        assert [row.value for row in identifiers(res.json()["id"], db)] == [ASIN]

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


class TestAnAsinRecognisesTheBook:
    """A second Kindle import, whose entries carry an ASIN and no ISBN, used to
    add every book again."""

    def test_a_second_add_carrying_the_asin_answers_409_naming_the_book(self, client, admin):
        body = {"title": "Docker", "identifiers": [{"scheme": "asin", "value": ASIN}]}
        first = client.post("/api/books/scan", json=body, headers=admin["headers"])

        again = client.post("/api/books/scan", json=body, headers=admin["headers"])

        assert again.status_code == 409
        assert again.json()["detail"]["book_id"] == first.json()["id"]

    def test_two_books_carrying_it_outside_a_copy_group_answer_409_naming_neither(
        self, client, admin, db
    ):
        """The pair an earlier defect left, two imports of one Kindle library.
        A client lands files on the Book a 409 names and offers a copy of it,
        so naming the lower id would pick between two Books. The second row is
        written directly because an add now refuses it."""
        body = {"title": "Docker", "identifiers": [{"scheme": "asin", "value": ASIN}]}
        client.post("/api/books", json=body, headers=admin["headers"])
        twin = client.post("/api/books", json={"title": "Docker"}, headers=admin["headers"])
        db.add(BookIdentifier(book_id=twin.json()["id"], scheme="asin", value=ASIN))
        db.commit()

        res = client.post("/api/books/scan", json=body, headers=admin["headers"])

        assert res.status_code == 409
        assert isinstance(res.json()["detail"], str)

    def test_another_members_private_book_carrying_it_answers_as_no_book(
        self, client, admin, member
    ):
        """Refusing would confirm somebody holds that edition, and nothing makes
        an identifier unique the way an ISBN is."""
        body = {"title": "Docker", "identifiers": [{"scheme": "asin", "value": ASIN}]}
        client.post("/api/books", json=body | {"is_private": True}, headers=admin["headers"])

        res = client.post("/api/books", json=body, headers=member["headers"])

        assert res.status_code == 201


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
        """Two Books carrying one identifier are two imports of one library made
        before an add refused the second, or a private Book made public: without
        the drop the flush trips `uq_book_identifiers_book_scheme_value` and the
        merge 500s. The second row is written directly because an add now
        refuses it."""
        keeper = client.post(
            "/api/books",
            json={
                "title": "Docker",
                "identifiers": [{"scheme": "asin", "value": ASIN}],
            },
            headers=admin["headers"],
        ).json()
        loser = client.post(
            "/api/books", json={"title": "Docker"}, headers=admin["headers"]
        ).json()
        db.add(BookIdentifier(book_id=loser["id"], scheme="asin", value=ASIN))
        db.commit()

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


class TestRemovingOne:
    """The correction the refusal to retype one depends on.

    `models.BookIdentifier` refuses to retype a row because an identifier is a
    claim about somebody else's file rather than a preference, and that refusal
    is only sound while a member may delete the row instead. These pin the
    delete, and the three that answer 404 pin what it refuses, across the four
    refusals they ask for: the pair comparing an invisible Book against an
    absent one issues two. **Tests, not responses**, stated because the two
    counts differ here and the sentence is the only thing that says which.

    The last three pin the way back, which is a detour, is not an undo, and is
    not always open. **The condition is not restated here**, because this
    docstring carried a copy of it without one and was the fifth site to do so:
    `models.BookIdentifier` is where it lives.
    """

    def a_book_with_one(self, client, headers, value=ASIN):
        return client.post(
            "/api/books",
            json={"title": "Docker", "identifiers": [{"scheme": "asin", "value": value}]},
            headers=headers,
        ).json()

    def test_the_member_who_added_the_book_removes_one(self, client, admin, db):
        book = self.a_book_with_one(client, admin["headers"])
        [row] = identifiers(book["id"], db)

        res = client.delete(
            f"/api/books/{book['id']}/identifiers/{row.id}", headers=admin["headers"]
        )

        assert res.status_code == 204
        assert identifiers(book["id"], db) == []

    def test_the_book_stops_serving_it(self, client, admin, db):
        book = self.a_book_with_one(client, admin["headers"])
        [row] = identifiers(book["id"], db)

        client.delete(
            f"/api/books/{book['id']}/identifiers/{row.id}", headers=admin["headers"]
        )

        res = client.get(f"/api/books/{book['id']}", headers=admin["headers"])
        assert res.json()["identifiers"] == []

    def test_another_member_removes_one_from_a_public_book(
        self, client, admin, member, db
    ):
        """A public Book is a shared shelf, which is what `BookForWrite` means.

        The same member may already retag it, re-cover it and refresh it, so an
        identifier being the one field they could not touch would be an
        exception with no reason behind it.
        """
        book = self.a_book_with_one(client, admin["headers"])
        [row] = identifiers(book["id"], db)

        res = client.delete(
            f"/api/books/{book['id']}/identifiers/{row.id}", headers=member["headers"]
        )

        assert res.status_code == 204
        assert identifiers(book["id"], db) == []

    def test_the_books_other_identifiers_stay(self, client, admin, db):
        book = client.post(
            "/api/books",
            json={
                "title": "Docker",
                "identifiers": [
                    {"scheme": "asin", "value": ASIN},
                    {"scheme": "google_books", "value": VOLUME_ID},
                ],
            },
            headers=admin["headers"],
        ).json()
        asin = next(row for row in identifiers(book["id"], db) if row.scheme == "asin")

        client.delete(
            f"/api/books/{book['id']}/identifiers/{asin.id}", headers=admin["headers"]
        )

        assert [row.value for row in identifiers(book["id"], db)] == [VOLUME_ID]

    def test_a_row_belonging_to_another_book_is_404_and_survives(
        self, client, admin, db
    ):
        """The pairing is in the query, not only in the path.

        Both Books here are the caller's own, so nothing about visibility
        refuses this: what refuses it is that the row is not on the Book named
        in the path.
        """
        mine = self.a_book_with_one(client, admin["headers"])
        theirs = self.a_book_with_one(client, admin["headers"], value="B00OTHER01")
        [row] = identifiers(theirs["id"], db)

        res = client.delete(
            f"/api/books/{mine['id']}/identifiers/{row.id}", headers=admin["headers"]
        )

        assert res.status_code == 404
        assert [stored.id for stored in identifiers(theirs["id"], db)] == [row.id]

    def test_a_row_id_naming_nothing_is_404(self, client, admin, db):
        book = self.a_book_with_one(client, admin["headers"])
        [row] = identifiers(book["id"], db)

        res = client.delete(
            f"/api/books/{book['id']}/identifiers/{row.id + 1000}",
            headers=admin["headers"],
        )

        assert res.status_code == 404

    def test_another_members_private_book_answers_exactly_what_an_absent_one_does(
        self, client, admin, member, db
    ):
        """404 and never 403, and identical to the body for a Book id nobody has.

        A 403 confirms the id exists, and so does a 404 phrased differently.
        Asserted against the other response rather than against a literal,
        because the two are the pair that has to agree: a later edit to one
        message is what this catches.
        """
        private = client.post(
            "/api/books",
            json={
                "title": "Docker",
                "is_private": True,
                "identifiers": [{"scheme": "asin", "value": ASIN}],
            },
            headers=admin["headers"],
        ).json()
        [row] = identifiers(private["id"], db)

        refused = client.delete(
            f"/api/books/{private['id']}/identifiers/{row.id}",
            headers=member["headers"],
        )
        absent = client.delete(
            f"/api/books/{private['id'] + 5000}/identifiers/{row.id}",
            headers=member["headers"],
        )

        assert refused.status_code == absent.status_code == 404
        assert refused.json() == absent.json()
        assert [stored.id for stored in identifiers(private["id"], db)] == [row.id]

    def test_it_takes_a_session(self, client, admin, db):
        book = self.a_book_with_one(client, admin["headers"])
        [row] = identifiers(book["id"], db)

        res = client.delete(f"/api/books/{book['id']}/identifiers/{row.id}")

        assert res.status_code == 401
        assert identifiers(book["id"], db) != []

    def test_importing_the_file_again_offers_the_book_and_not_the_row(
        self, client, admin, db
    ):
        """Half of the route's own claim, and the half a client repeats.

        `add_identifiers` is reached only from `_create_book`, which always
        builds a new Book, so the Book that lost a row does not get it back by
        importing the store file again: what that offers is the Book a second
        time.

        **This Book carries no ISBN**, which is the condition the next test is
        about and is stated here because a fixture named for what it tests is
        not evidence that it tests it.
        """
        book = self.a_book_with_one(client, admin["headers"])
        [row] = identifiers(book["id"], db)
        client.delete(
            f"/api/books/{book['id']}/identifiers/{row.id}", headers=admin["headers"]
        )

        again = self.a_book_with_one(client, admin["headers"])

        assert again["id"] != book["id"]
        assert identifiers(book["id"], db) == []

    def test_merging_that_second_book_in_carries_the_row_across(
        self, client, admin, db
    ):
        """The other half, and the reason the client does not promise finality.

        **The prose said the removal could not be undone and that was wrong.**
        `folding.fold` moves a merged Book's identifiers onto the
        survivor rather than re-asserting them, so import-then-merge puts the
        value back on the Book it came off. Both critic seats arrived at this
        from different directions, one from the writer register in
        `schemas/identifier.py` and one by executing the merge, which is what
        two seats are for.

        **Only where this Book carries no ISBN**, which the test below is for
        and which is why no client promises this road.
        """
        book = self.a_book_with_one(client, admin["headers"])
        [row] = identifiers(book["id"], db)
        client.delete(
            f"/api/books/{book['id']}/identifiers/{row.id}", headers=admin["headers"]
        )
        again = self.a_book_with_one(client, admin["headers"])

        res = client.post(
            "/api/books/merge",
            json={"book_ids": [book["id"], again["id"]], "keep_id": book["id"]},
            headers=admin["headers"],
        )

        assert res.status_code == 200
        assert [stored.value for stored in identifiers(book["id"], db)] == [ASIN]

    def test_a_book_holding_an_isbn_has_no_second_book_to_merge(
        self, client, admin, db
    ):
        """The condition that closes the road, and the common half rather than
        the corner.

        A store export carrying both an ISBN and an identifier is what a Play
        Books Takeout is, and `_create_book` answers 409 on an ISBN the
        catalogue already holds rather than making a second Book. So there is
        nothing to merge, and the removal really is final for that Book.

        **The test above was the whole evidence for a claim four files made,
        and its fixture posts no ISBN**, which is this repository's note about
        a guard whose own author picked the covered case. Found by the design
        seat, which read the importer rather than the test.
        """
        book = client.post(
            "/api/books",
            json={
                "title": "Docker",
                "isbn": "9783446470941",
                "identifiers": [{"scheme": "asin", "value": ASIN}],
            },
            headers=admin["headers"],
        ).json()
        [row] = identifiers(book["id"], db)
        client.delete(
            f"/api/books/{book['id']}/identifiers/{row.id}", headers=admin["headers"]
        )

        again = client.post(
            "/api/books",
            json={
                "title": "Docker",
                "isbn": "9783446470941",
                "identifiers": [{"scheme": "asin", "value": ASIN}],
            },
            headers=admin["headers"],
        )

        assert again.status_code == 409
        assert identifiers(book["id"], db) == []


CALIBRE_UUID = "3f2a6c1e-8b4d-4e2a-9c7f-1d5e0b6a2c94"


class TestACalibreRecordIsRecognisedByItsUuid:
    """A Calibre record with no file and no ISBN has nothing else to be
    recognised by when the library is imported again."""

    def calibre_add(self, client, headers, **overrides):
        return client.post(
            "/api/books/scan",
            json={
                "title": "A record with no file",
                "identifiers": [{"scheme": "calibre_uuid", "value": CALIBRE_UUID}],
            }
            | overrides,
            headers=headers,
        )

    def test_a_second_add_of_the_record_answers_409_naming_the_book(self, client, admin):
        first = self.calibre_add(client, admin["headers"])

        again = self.calibre_add(client, admin["headers"])

        assert again.status_code == 409
        assert again.json()["detail"]["book_id"] == first.json()["id"]

    def test_a_book_the_caller_cannot_see_answers_as_no_book(self, client, admin, member):
        """Refusing on a hidden holder would confirm somebody else holds that
        record, and nothing makes a uuid unique the way an ISBN is."""
        self.calibre_add(client, admin["headers"], is_private=True)

        res = self.calibre_add(client, member["headers"])

        assert res.status_code == 201

    def test_a_hidden_or_trashed_holder_answers_exactly_as_no_holder(
        self, client, admin, member
    ):
        """Same status, same body and the same statements as a uuid nobody
        holds, so the answer carries nothing about the holder. Trashed is the
        caller's own Book: the Shelf excludes the trash, so a re-import beside
        it makes a new Book rather than reviving it."""
        hidden = CALIBRE_UUID
        trashed = CALIBRE_UUID[:-1] + "5"
        absent = CALIBRE_UUID[:-1] + "6"
        self.calibre_add(client, admin["headers"], is_private=True)
        own = self.calibre_add(
            client,
            member["headers"],
            identifiers=[{"scheme": "calibre_uuid", "value": trashed}],
        ).json()
        client.delete(f"/api/books/{own['id']}", headers=member["headers"])
        # Warms whatever a member's first request loads, so the three below
        # are compared on the lookup alone.
        client.get("/api/books", headers=member["headers"])

        def answer(uuid):
            statements = []

            def record(_conn, _cursor, statement, *_rest):
                statements.append(statement)

            event.listen(engine, "before_cursor_execute", record)
            try:
                res = self.calibre_add(
                    client,
                    member["headers"],
                    identifiers=[{"scheme": "calibre_uuid", "value": uuid}],
                )
            finally:
                event.remove(engine, "before_cursor_execute", record)
            body = res.json()
            return (
                res.status_code,
                body["title"],
                [(one["scheme"], one["value"] == uuid) for one in body["identifiers"]],
                len(statements),
            )

        nobody = answer(absent)
        assert nobody[0] == 201
        assert answer(hidden) == nobody
        assert answer(trashed) == nobody

    def test_the_uuid_holder_answers_where_the_isbn_names_another_book(
        self, client, admin
    ):
        """Asked before the ISBN walk, so the 409 names the Book this record
        already is rather than one that merely shares its ISBN."""
        client.post(
            "/api/books",
            json={"title": "Dune", "isbn": "9780441013593"},
            headers=admin["headers"],
        )
        record = self.calibre_add(client, admin["headers"]).json()

        again = self.calibre_add(client, admin["headers"], isbn="9780441013593")

        assert again.status_code == 409
        assert again.json()["detail"]["book_id"] == record["id"]
