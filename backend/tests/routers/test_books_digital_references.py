"""Where a book file is said to be, over the API.

Shaped after the notes and quotes tests, because it is the same kind of thing:
a per book sub-resource behind `dependencies`. What is tested here beyond that
shape is what this feature does differently, and each of those is the reason
the ticket was not a column.

* A report is **idempotent on the location**, so re-importing a folder refreshes
  rows instead of doubling them.
* `confirmed_at` is this server's clock and a client cannot set it.
* A missing report **flags and never deletes**, and its timestamp does not move.
* Nothing here is verified, so no route claims it was.
* The flag has one reader that is **not** per book, and what scopes it is the
  Shelf alone, because a reference has no Member of its own:
  `TestTheShelfWideReaderOfTheFlag`.
"""

from datetime import timedelta

from main import app, iter_api_routes
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


MISSING_URL = "/api/books/digital-references/missing"


def flag(client, headers, book_id, **fields):
    """Report a file at a location and then report that it is not there."""
    one = report(client, headers, book_id, **fields).json()["id"]
    res = client.post(f"{URL.format(book_id)}/{one}/missing", headers=headers)
    assert res.status_code == 200, res.text
    return one


def missing(client, headers, **params):
    return client.get(MISSING_URL, headers=headers, params=params)


def age(db, reference_id, days):
    """Move a flag back in time, because `CURRENT_TIMESTAMP` has one second.

    Two flags raised in one test land on the same value, so an ordering
    assertion over them observes a second boundary rather than the ordering.
    """
    row = db.query(DigitalReference).filter(DigitalReference.id == reference_id).one()
    row.missing_since = row.missing_since - timedelta(days=days)
    db.commit()


class TestTheShelfWideReaderOfTheFlag:
    """The one route in this family that is not per book.

    It exists because the flag otherwise has no reader at shelf scale: finding
    every flagged file meant one request per book across the whole catalogue,
    and almost every book holds none.
    """

    def test_a_flagged_reference_is_listed_with_its_book(
        self, client, admin, make_book
    ):
        book = make_book(admin["headers"], title="The Dispossessed")
        flag(client, admin["headers"], book["id"], relative_path="ursula/d.epub")

        body = missing(client, admin["headers"]).json()
        assert body["total"] == 1
        row = body["items"][0]
        assert row["relative_path"] == "ursula/d.epub"
        assert row["book_title"] == "The Dispossessed"
        assert row["missing_since"] is not None

    def test_a_row_carries_the_book_it_is_on(self, client, admin, make_book):
        """Without `book_id` no row on this page can be acted on: flagging,
        re-confirming and forgetting are all addressed by book. It lives on
        `DigitalReferenceOut`, where `NoteOut` and `QuoteOut` both put it."""
        book = make_book(admin["headers"])
        flag(client, admin["headers"], book["id"])
        assert missing(client, admin["headers"]).json()["items"][0]["book_id"] == book["id"]

    def test_a_reference_nobody_reported_missing_is_not_listed(
        self, client, admin, make_book
    ):
        book = make_book(admin["headers"])
        report(client, admin["headers"], book["id"])
        assert missing(client, admin["headers"]).json()["total"] == 0

    def test_a_sighting_takes_it_off_the_list(self, client, admin, make_book):
        """Something looked and found it, which is the only evidence that ever
        contradicts a miss."""
        book = make_book(admin["headers"])
        flag(client, admin["headers"], book["id"])
        report(client, admin["headers"], book["id"])
        assert missing(client, admin["headers"]).json()["total"] == 0

    def test_a_flagged_reference_on_a_book_somebody_else_added_is_listed(
        self, client, admin, member, make_book
    ):
        """The disclosure this route makes, pinned rather than left to be
        discovered.

        A reference has no Member of its own, so its visibility is its Book's
        entirely, and this listing is that rule at shelf scale: every flagged
        row on a Book the caller can see, in one request, where reading them per
        book is one request each. A row is an unverified path on somebody's
        machine, so that is what is being handed over, and the honest place to
        say so is here and at the route.
        """
        theirs = make_book(member["headers"], title="Their Book")
        flag(
            client,
            member["headers"],
            theirs["id"],
            root_label="their-nas",
            relative_path="their/layout/x.epub",
        )

        body = missing(client, admin["headers"]).json()
        assert body["total"] == 1
        assert body["items"][0]["relative_path"] == "their/layout/x.epub"

    def test_a_flagged_reference_on_a_private_book_is_not_listed(
        self, client, admin, member, make_book
    ):
        """**The leak this route must never make**, and the test that goes red
        if the query stops going through the Shelf.

        A private Book is invisible to everybody but its adder, so its
        references are too. Reaching one here would disclose the Book, the path
        and that the member holds it, in a single 200.
        """
        theirs = make_book(member["headers"], title="Their Diary", is_private=True)
        flag(
            client,
            member["headers"],
            theirs["id"],
            relative_path="private/diary.epub",
        )

        res = missing(client, admin["headers"])
        assert res.json()["total"] == 0
        assert res.json()["items"] == []
        assert "private/diary.epub" not in res.text

    def test_a_members_own_report_on_a_book_somebody_else_added_is_listed(
        self, client, admin, member, make_book
    ):
        """The case an ownership arm hid, and the reason there is no arm.

        Whoever may read a Book may report a file on it, so a member's own files
        are catalogued against Books other members added: that is the ordinary
        household shelf. Scoping this listing by who added the Book would drop
        exactly those rows, which is the half of the feature somebody would
        actually be looking for.
        """
        theirs = make_book(member["headers"], title="Their Book")
        flag(
            client,
            admin["headers"],
            theirs["id"],
            root_label="my-nas",
            relative_path="mine/on/their/book.epub",
        )

        body = missing(client, admin["headers"]).json()
        assert [row["relative_path"] for row in body["items"]] == [
            "mine/on/their/book.epub"
        ]

    def test_a_plain_member_gets_the_reader(self, client, member, make_book):
        """Not an admin report, asserted by somebody who is not one.

        Every other test in this class holds the `admin` fixture, and only
        because it is the first account this app makes. A class that never calls
        the route as anybody else cannot tell `CurrentUser` from an admin gate,
        and a fix round deleted the one test that did while the count went up:
        measured 2026-09-10, swapping the dependency for `require_admin` left
        the whole class green without it.
        """
        theirs = make_book(member["headers"])
        one = flag(client, member["headers"], theirs["id"], relative_path="theirs.epub")

        body = missing(client, member["headers"]).json()
        assert [row["id"] for row in body["items"]] == [one]

    def test_a_reference_on_a_book_in_the_trash_is_not_listed(
        self, client, admin, make_book
    ):
        """The Shelf's other refusal, and the one privacy alone would not make.

        A trashed Book is still visible to its adder in the trash, so what
        excludes it here is `visible_to`'s `deleted_at IS NULL` rather than
        anything about who may see it. Red if the query stops going through the
        Shelf.
        """
        book = make_book(admin["headers"])
        flag(client, admin["headers"], book["id"])
        client.delete(f"/api/books/{book['id']}", headers=admin["headers"])
        body = missing(client, admin["headers"]).json()
        # Both halves. A `total` alone is answered by the count query and says
        # nothing about the rows: measured, a mutation dropping the Shelf from
        # the rows query only left this test green.
        assert body["total"] == 0
        assert body["items"] == []

    def test_the_listing_is_paginated(self, client, admin, make_book):
        """Bounded like every other many-book query here. The test that goes red
        when the page's limit comes off the query."""
        book = make_book(admin["headers"])
        for index in range(3):
            flag(client, admin["headers"], book["id"], relative_path=f"{index}.epub")

        body = missing(client, admin["headers"], page_size=2).json()
        assert len(body["items"]) == 2
        assert body["total"] == 3
        assert body["page_size"] == 2

    def test_the_total_counts_references_and_not_books(
        self, client, admin, make_book
    ):
        """A book at three paths with two of them gone is two rows, because the
        flag is per location and so is the thing to go and look at."""
        book = make_book(admin["headers"])
        flag(client, admin["headers"], book["id"], root_label="nas")
        flag(client, admin["headers"], book["id"], root_label="laptop")
        report(client, admin["headers"], book["id"], root_label="phone")

        assert missing(client, admin["headers"]).json()["total"] == 2

    def test_the_newest_miss_comes_first(self, client, admin, make_book, db):
        """A miss reported minutes ago is the one whose cause a member can still
        name."""
        book = make_book(admin["headers"])
        old = flag(client, admin["headers"], book["id"], relative_path="old.epub")
        flag(client, admin["headers"], book["id"], relative_path="new.epub")
        age(db, old, days=1)

        paths = [row["relative_path"] for row in missing(client, admin["headers"]).json()["items"]]
        assert paths == ["new.epub", "old.epub"]

    def test_it_is_declared_before_every_single_book_route(self):
        """The ordering itself, asserted against the app rather than inferred
        from a 200.

        A request answering 200 today proves nothing about the ordering: this
        path has two segments and `/{book_id}` has one, so nothing collides
        **yet**. What the ordering protects against is the day somebody declares
        a second segment under `/{book_id}`, and by then the route has moved and
        the 200 is gone. So the assertion is on the declaration order, which is
        the property the section comment claims, and it goes red if this route
        is relocated below `/{book_id}`.

        **Below every route under `/{book_id}` and not merely the bare one**,
        because a path param matches one segment: what collides with this route
        is a two segment `/{book_id}/<anything>`, and the bare route is only the
        first of that family in declaration order today.

        **Through `iter_api_routes`, because `app.routes` does not hold these
        routes at all**: `include_router` appends a wrapper around the child
        router rather than splicing its routes in, which `main.py` records as
        how the first version of its own check passed while testing nothing.
        Measured here on the way to the same mistake: `app.routes` is 19 entries
        and not one of them is under `/api/books`.
        """
        paths = [route.path for route in iter_api_routes(app.routes)]
        mine = paths.index("/api/books/digital-references/missing")
        # **Every** route under `/{book_id}`, not the bare one. The bare route
        # is simply the first of that section today, so anchoring on it would
        # pass a `/{book_id}/missing` declared above it, which is the exact
        # collision the section comment is about.
        swallowers = [
            index
            for index, path in enumerate(paths)
            if path.startswith("/api/books/{book_id}")
        ]
        assert swallowers, (
            "no route under /api/books/{book_id} was found, so this guard is "
            "anchored on nothing and is passing for the wrong reason"
        )
        assert mine < min(swallowers)

    def test_it_takes_a_session(self, client):
        assert client.get(MISSING_URL).status_code == 401

    def test_page_two_returns_the_rest(self, client, admin, make_book, db):
        """The offset, which a first page cannot exercise: without it every page
        is page one and a client paging through a burst never reaches the end.
        """
        book = make_book(admin["headers"])
        for index in range(3):
            one = flag(
                client, admin["headers"], book["id"], relative_path=f"{index}.epub"
            )
            age(db, one, days=index)

        body = missing(client, admin["headers"], page_size=2, page=2).json()
        assert [row["relative_path"] for row in body["items"]] == ["2.epub"]
        assert body["page"] == 2

    def test_two_misses_at_one_instant_come_back_newest_id_first(
        self, client, admin, make_book, db
    ):
        """The tiebreak, pinned as the contract rather than as a consequence.

        `func.now()` is `CURRENT_TIMESTAMP`, one second wide, and a client
        sweeping a directory posts its misses inside one tick, so ties are the
        ordinary case here and not a corner. Ordering on that column alone
        leaves their order to the database, which no SQL requires to be the same
        twice, and a paged reader of one burst can then see a row twice and
        never see another.

        **What this asserts is the order of the tied pair, and that is
        deliberate**: the repeat-across-pages failure is undefined behaviour and
        cannot be provoked on demand, so a test shaped like it passes on a
        mutant. Measured 2026-09-10 on this file: with the tiebreak deleted, a
        two page walk still returned both rows and caught nothing, while this
        assertion goes red, because SQLite falls back to rowid order and hands
        the pair back oldest first.
        """
        book = make_book(admin["headers"])
        first = flag(client, admin["headers"], book["id"], relative_path="a.epub")
        second = flag(client, admin["headers"], book["id"], relative_path="b.epub")
        at = db.query(DigitalReference).filter(DigitalReference.id == first).one()
        other = db.query(DigitalReference).filter(DigitalReference.id == second).one()
        other.missing_since = at.missing_since
        db.commit()

        rows = missing(client, admin["headers"]).json()["items"]
        assert [row["id"] for row in rows] == [second, first]

    def test_the_total_does_not_multiply_by_the_books_on_the_shelf(
        self, client, admin, make_book
    ):
        """One flagged reference is one, however many books the caller holds.

        The count is written through `Shelf.select()`, whose docstring records
        that a caller naming another table and forgetting to join it gets a
        cartesian product rather than an error. Every other test here has one
        book on the shelf, where that product is indistinguishable from the
        right answer.
        """
        make_book(admin["headers"], title="One")
        make_book(admin["headers"], title="Two")
        third = make_book(admin["headers"], title="Three")
        flag(client, admin["headers"], third["id"])

        body = missing(client, admin["headers"]).json()
        assert body["total"] == 1
        assert len(body["items"]) == 1
