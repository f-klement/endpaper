"""Where a book file is said to be, over the API.

Shaped after the notes and quotes tests, because it is the same kind of thing:
a per book sub-resource behind `dependencies`. What is tested here beyond that
shape is the four things this feature does differently, and each of them is the
reason the ticket was not a column.

* A report is **idempotent on the location**, so re-importing a folder refreshes
  rows instead of doubling them.
* `confirmed_at` is this server's clock and a client cannot set it.
* A missing report **flags and never deletes**, and its timestamp does not move.
* Nothing here is verified, so no route claims it was.
"""

from datetime import timedelta

from models import DIGITAL_REFERENCE_PATH_MAX, DigitalReference
from schemas.digital import MAX_DIGITAL_REFERENCES_PER_BOOK

URL = "/api/books/{}/digital-references"


def report(client, headers, book_id, **fields):
    payload = {"root_label": "/books", "relative_path": "a/b.epub"} | fields
    return client.post(URL.format(book_id), json=payload, headers=headers)


def listing(client, headers, book_id):
    return client.get(URL.format(book_id), headers=headers)


class TestReportingWhereAFileIs:
    def test_a_report_comes_back_with_what_was_sent(self, client, admin, make_book):
        book = make_book(admin["headers"])
        res = report(
            client,
            admin["headers"],
            book["id"],
            relative_path="Le Guin/The Dispossessed.epub",
            size_bytes=481_233,
            root_confirmed=True,
        )
        assert res.status_code == 200
        body = res.json()
        assert body["relative_path"] == "Le Guin/The Dispossessed.epub"
        assert body["size_bytes"] == 481_233
        assert body["root_confirmed"] is True

    def test_a_root_that_was_not_corroborated_defaults_to_the_weaker_claim(
        self, client, admin, make_book
    ):
        """A client that does not say has not corroborated anything, and the
        row must not read as though it had."""
        book = make_book(admin["headers"])
        assert report(client, admin["headers"], book["id"]).json()["root_confirmed"] is False

    def test_a_second_report_of_the_same_file_does_not_add_a_row(
        self, client, admin, make_book
    ):
        """The whole reason a reference is identified by where the file is.
        Re-importing a folder somebody imported last month is the case."""
        book = make_book(admin["headers"])
        report(client, admin["headers"], book["id"])
        report(client, admin["headers"], book["id"])
        assert len(listing(client, admin["headers"], book["id"]).json()) == 1

    def test_a_second_report_of_a_different_file_adds_a_row(
        self, client, admin, make_book
    ):
        """The same book at two paths on two machines is the case that made this
        a table rather than a column."""
        book = make_book(admin["headers"])
        report(client, admin["headers"], book["id"], root_label="/nas")
        report(client, admin["headers"], book["id"], root_label="/laptop")
        assert len(listing(client, admin["headers"], book["id"]).json()) == 2

    def test_a_report_replaces_the_fingerprint_whole(self, client, admin, make_book):
        """A row is one client's one look. Merging a new size with an old
        modification time would produce a fingerprint nobody ever reported and
        that no re-check could match."""
        book = make_book(admin["headers"])
        report(
            client,
            admin["headers"],
            book["id"],
            size_bytes=100,
            file_modified_at="2020-01-01T00:00:00",
        )
        body = report(client, admin["headers"], book["id"], size_bytes=200).json()
        assert body["size_bytes"] == 200
        assert body["file_modified_at"] is None

    def test_a_book_that_the_caller_cannot_see_takes_no_report(
        self, client, member, other_user, make_book
    ):
        """404 and not 403, for the reason `dependencies._not_found` gives: a
        403 would confirm the book exists."""
        book = make_book(member["headers"], is_private=True)
        assert report(client, other_user["headers"], book["id"]).status_code == 404


class TestTheServerSaysOnlyWhatItKnows:
    def test_a_client_cannot_state_when_the_file_was_seen(
        self, client, admin, make_book
    ):
        """`confirmed_at` is when this server was **told**. A client able to set
        it could write a freshness nobody looked for, which is exactly the claim
        that rots."""
        book = make_book(admin["headers"])
        res = client.post(
            URL.format(book["id"]),
            json={
                "root_label": "/books",
                "relative_path": "a.epub",
                "confirmed_at": "1999-01-01T00:00:00",
            },
            headers=admin["headers"],
        )
        assert res.status_code == 200
        assert not res.json()["confirmed_at"].startswith("1999")

    def test_a_new_reference_has_not_been_reported_missing(
        self, client, admin, make_book
    ):
        book = make_book(admin["headers"])
        assert report(client, admin["headers"], book["id"]).json()["missing_since"] is None


class TestAReferenceThatNoLongerResolves:
    def _one(self, client, headers, book_id):
        return report(client, headers, book_id).json()["id"]

    def test_a_missing_report_flags_the_row(self, client, admin, make_book):
        book = make_book(admin["headers"])
        one = self._one(client, admin["headers"], book["id"])
        res = client.post(
            f"{URL.format(book['id'])}/{one}/missing", headers=admin["headers"]
        )
        assert res.status_code == 200
        assert res.json()["missing_since"] is not None

    def test_a_missing_report_does_not_delete_the_row(self, client, admin, make_book):
        """The refusal that is the whole route. A phone that cannot reach the
        NAS reports every file on it missing and is telling the truth about what
        it can see."""
        book = make_book(admin["headers"])
        one = self._one(client, admin["headers"], book["id"])
        client.post(f"{URL.format(book['id'])}/{one}/missing", headers=admin["headers"])
        assert len(listing(client, admin["headers"], book["id"]).json()) == 1

    def test_a_second_missing_report_does_not_move_the_timestamp(
        self, client, admin, make_book, db
    ):
        """The column records when this was **first** said, so a client
        re-checking hourly cannot keep resetting the age of the problem.

        **The row is aged between the two reports, and without that this test
        passes with its own subject deleted.** `func.now()` is
        `CURRENT_TIMESTAMP` on SQLite, which has one second resolution, so two
        POSTs in a row land on the same value whether the guard is there or
        not: the assertion would be observing a second boundary rather than the
        rule. Ageing the row is what makes the two answers distinguishable.
        """
        book = make_book(admin["headers"])
        one = self._one(client, admin["headers"], book["id"])
        url = f"{URL.format(book['id'])}/{one}/missing"
        client.post(url, headers=admin["headers"])

        row = db.query(DigitalReference).filter(DigitalReference.id == one).one()
        row.missing_since = row.missing_since - timedelta(days=1)
        db.commit()
        aged = row.missing_since

        again = client.post(url, headers=admin["headers"]).json()["missing_since"]
        assert again.startswith(aged.isoformat()[:19])

    def test_a_sighting_clears_the_flag(self, client, admin, make_book):
        """Something has now looked and found it, which is the only evidence
        that ever contradicts a miss."""
        book = make_book(admin["headers"])
        one = self._one(client, admin["headers"], book["id"])
        client.post(f"{URL.format(book['id'])}/{one}/missing", headers=admin["headers"])
        assert report(client, admin["headers"], book["id"]).json()["missing_since"] is None

    def test_a_reference_on_another_book_is_not_reachable_through_this_one(
        self, client, admin, make_book
    ):
        """The book/reference pairing, without which an id from another book is
        reachable through a book the caller does hold."""
        mine, theirs = make_book(admin["headers"]), make_book(admin["headers"])
        one = self._one(client, admin["headers"], theirs["id"])
        res = client.post(
            f"{URL.format(mine['id'])}/{one}/missing", headers=admin["headers"]
        )
        assert res.status_code == 404


class TestTheServerClockIsNotReachableFromThePayload:
    """The half `tests/schemas/test_digital.py` cannot reach.

    That file asserts a client cannot **name** a server clock column. It says
    nothing about what the handler then puts in one, so a line reading
    `confirmed_at = payload.file_modified_at or func.now()` passes every test
    over there while making the column a client's word after all. This is the
    guard on the assignment rather than on the field list.
    """

    def test_a_reported_modification_time_does_not_become_the_confirmation(
        self, client, admin, make_book
    ):
        book = make_book(admin["headers"])
        body = report(
            client,
            admin["headers"],
            book["id"],
            file_modified_at="1999-03-04T05:06:07",
        ).json()
        assert body["file_modified_at"].startswith("1999")
        assert not body["confirmed_at"].startswith("1999")


class TestAnOverWidePairIs422AndNot500:
    """The schema and the CHECK bound the same inequality, and only one of them
    answers a member.

    `docs/api.md` opens its bounds paragraph with "all of them 422 rather than
    500". If the schema's rule is loosened by even one character, the pair
    reaches `ck_digital_references_bounds` instead and a member's own request
    becomes a server error. Nothing else in this tree measures the gap between
    the two layers.
    """

    def test_one_character_past_the_pair_bound_is_refused_by_the_schema(
        self, client, admin, make_book
    ):
        book = make_book(admin["headers"])
        half = (DIGITAL_REFERENCE_PATH_MAX + 1) // 2
        res = report(
            client,
            admin["headers"],
            book["id"],
            root_label="r" * half,
            relative_path="p" * (DIGITAL_REFERENCE_PATH_MAX + 1 - half),
        )
        assert res.status_code == 422

    def test_the_pair_bound_exactly_is_accepted(self, client, admin, make_book):
        """The other side, so the test above measures the bound rather than the
        route."""
        book = make_book(admin["headers"])
        half = DIGITAL_REFERENCE_PATH_MAX // 2
        res = report(
            client,
            admin["headers"],
            book["id"],
            root_label="r" * half,
            relative_path="p" * (DIGITAL_REFERENCE_PATH_MAX - half),
        )
        assert res.status_code == 200


class TestForgettingAReference:
    def test_a_member_can_delete_one(self, client, admin, make_book):
        book = make_book(admin["headers"])
        one = report(client, admin["headers"], book["id"]).json()["id"]
        res = client.delete(
            f"{URL.format(book['id'])}/{one}", headers=admin["headers"]
        )
        assert res.status_code == 204
        assert listing(client, admin["headers"], book["id"]).json() == []

    def test_purging_the_book_takes_its_references(self, client, admin, make_book, db):
        """Cascaded like the notes and the quotes: a purged book's references
        point at a book nobody holds."""
        book = make_book(admin["headers"])
        report(client, admin["headers"], book["id"])
        client.delete(f"/api/books/{book['id']}", headers=admin["headers"])
        client.delete("/api/books/trash", headers=admin["headers"])
        assert db.query(DigitalReference).count() == 0


class TestTheCeilingIsCountedPerBookAndNotPerRequest:
    """The distinction `MAX_CLASSIFICATIONS_PER_BOOK` records paying for: a
    route that bounds one payload while the writer is additive across requests
    bounds nothing at all."""

    def _fill(self, client, headers, book_id):
        for index in range(MAX_DIGITAL_REFERENCES_PER_BOOK):
            assert (
                report(client, headers, book_id, root_label=f"/root{index}").status_code
                == 200
            )

    def test_a_new_location_past_the_ceiling_is_refused(
        self, client, admin, make_book
    ):
        book = make_book(admin["headers"])
        self._fill(client, admin["headers"], book["id"])
        res = report(client, admin["headers"], book["id"], root_label="/one-too-many")
        assert res.status_code == 409

    def test_a_book_at_the_ceiling_can_still_re_confirm_what_it_holds(
        self, client, admin, make_book
    ):
        """The ceiling binds a **new** location. A library that filled it must
        not lose the ability to say a file is still there."""
        book = make_book(admin["headers"])
        self._fill(client, admin["headers"], book["id"])
        assert (
            report(client, admin["headers"], book["id"], root_label="/root0").status_code
            == 200
        )

    def test_another_books_references_do_not_count_against_this_one(
        self, client, admin, make_book
    ):
        """**Per book is the whole of the ceiling.** Counted over the table
        instead, one member filling their own shelf refuses everybody else's
        next reference, and every other test here creates far too few rows to
        notice: the count they drive is one book's either way.
        """
        full, other = make_book(admin["headers"]), make_book(admin["headers"])
        self._fill(client, admin["headers"], full["id"])
        assert report(client, admin["headers"], other["id"]).status_code == 200


class TestTheShelfReachesAReference:
    def test_another_member_cannot_list_them_on_a_private_book(
        self, client, member, other_user, make_book
    ):
        """A reference is an ordinary field on a book, so it is as invisible as
        the book is. 404 on the book, never a row."""
        book = make_book(member["headers"], is_private=True)
        assert listing(client, other_user["headers"], book["id"]).status_code == 404

    def test_a_member_can_add_one_to_a_public_book_somebody_else_added(
        self, client, member, other_user, make_book
    ):
        """The shared shelf rule `book_for_write` states for tags and covers:
        whoever may write the book may write its references."""
        book = make_book(member["headers"])
        assert report(client, other_user["headers"], book["id"]).status_code == 200


class TestMergingTwoBooksKeepsTheirReferences:
    def test_a_reference_moves_to_the_survivor(self, client, admin, make_book, db):
        """Without this the cascade on the loser takes it, and a merge silently
        forgets where the file is."""
        keeper = make_book(admin["headers"], title="One")
        loser = make_book(admin["headers"], title="Two")
        report(client, admin["headers"], loser["id"], root_label="/nas")
        res = client.post(
            "/api/books/merge",
            json={"book_ids": [keeper["id"], loser["id"]], "keep_id": keeper["id"]},
            headers=admin["headers"],
        )
        assert res.status_code == 200
        held = listing(client, admin["headers"], keeper["id"]).json()
        assert [entry["root_label"] for entry in held] == ["/nas"]

    def test_a_merge_past_the_ceiling_drops_the_overflow_rather_than_moving_it(
        self, client, admin, make_book
    ):
        """The second of the two capped writers, which was stated and untested.

        Without the arm, a merge of 20 books at 16 references apiece is a 320
        row stored write nobody bounded, which is the failure
        `MAX_CLASSIFICATIONS_PER_BOOK` is on record as having been bought by.
        """
        keeper, loser = make_book(admin["headers"], title="One"), make_book(
            admin["headers"], title="Two"
        )
        for index in range(MAX_DIGITAL_REFERENCES_PER_BOOK):
            report(client, admin["headers"], keeper["id"], root_label=f"/root{index}")
        report(client, admin["headers"], loser["id"], root_label="/overflow")

        res = client.post(
            "/api/books/merge",
            json={"book_ids": [keeper["id"], loser["id"]], "keep_id": keeper["id"]},
            headers=admin["headers"],
        )

        assert res.status_code == 200
        held = listing(client, admin["headers"], keeper["id"]).json()
        assert len(held) == MAX_DIGITAL_REFERENCES_PER_BOOK
        assert "/overflow" not in [entry["root_label"] for entry in held]

    def test_a_merge_under_the_ceiling_moves_the_reference_rather_than_dropping_it(
        self, client, admin, make_book
    ):
        """The other side of the same arm, so the test above measures the
        ceiling rather than the merge."""
        keeper, loser = make_book(admin["headers"], title="One"), make_book(
            admin["headers"], title="Two"
        )
        for index in range(MAX_DIGITAL_REFERENCES_PER_BOOK - 1):
            report(client, admin["headers"], keeper["id"], root_label=f"/root{index}")
        report(client, admin["headers"], loser["id"], root_label="/overflow")

        client.post(
            "/api/books/merge",
            json={"book_ids": [keeper["id"], loser["id"]], "keep_id": keeper["id"]},
            headers=admin["headers"],
        )

        held = listing(client, admin["headers"], keeper["id"]).json()
        assert "/overflow" in [entry["root_label"] for entry in held]

    def test_the_same_file_on_both_does_not_break_the_merge(
        self, client, admin, make_book
    ):
        """`uq_digital_references_location` would refuse the flush, and two rows
        for one book catalogued from one library is the likely case rather than
        an edge."""
        keeper = make_book(admin["headers"], title="One")
        loser = make_book(admin["headers"], title="Two")
        report(client, admin["headers"], keeper["id"])
        report(client, admin["headers"], loser["id"])
        res = client.post(
            "/api/books/merge",
            json={"book_ids": [keeper["id"], loser["id"]], "keep_id": keeper["id"]},
            headers=admin["headers"],
        )
        assert res.status_code == 200
        assert len(listing(client, admin["headers"], keeper["id"]).json()) == 1
