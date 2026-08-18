"""Ratings and reading dates.

Both are per person, both hang off `user_books`, and both are derived from
things a member already does rather than from a form nobody fills in. The dates
in particular are stamped from status transitions, so the rules for that are
what most of this file pins.
"""


class TestRating:
    def test_a_book_starts_unrated(self, client, admin, make_book):
        book = make_book(admin["headers"])
        assert book["my_rating"] is None

    def test_records_a_rating(self, client, admin, make_book):
        book = make_book(admin["headers"])

        res = client.patch(
            f"/api/books/{book['id']}/rating", json={"rating": 4}, headers=admin["headers"]
        )

        assert res.status_code == 200
        assert res.json()["my_rating"] == 4

    def test_a_rating_is_personal(self, client, admin, member, make_book):
        """A shared shelf does not mean a shared opinion of what is on it."""
        book = make_book(admin["headers"])
        client.patch(
            f"/api/books/{book['id']}/rating", json={"rating": 5}, headers=admin["headers"]
        )

        seen_by_member = client.get(f"/api/books/{book['id']}", headers=member["headers"])

        assert seen_by_member.json()["my_rating"] is None

    def test_a_null_clears_it(self, client, admin, make_book):
        book = make_book(admin["headers"])
        client.patch(
            f"/api/books/{book['id']}/rating", json={"rating": 3}, headers=admin["headers"]
        )

        res = client.patch(
            f"/api/books/{book['id']}/rating", json={"rating": None}, headers=admin["headers"]
        )

        assert res.json()["my_rating"] is None

    def test_rating_does_not_touch_the_reading_dates(self, client, admin, make_book):
        """Rating a book is not a claim to have finished it just now."""
        book = make_book(admin["headers"])

        res = client.patch(
            f"/api/books/{book['id']}/rating", json={"rating": 5}, headers=admin["headers"]
        )

        assert res.json()["my_finished_at"] is None
        assert res.json()["my_started_at"] is None

    def test_rating_does_not_change_the_status(self, client, admin, make_book):
        book = make_book(admin["headers"])

        res = client.patch(
            f"/api/books/{book['id']}/rating", json={"rating": 5}, headers=admin["headers"]
        )

        assert res.json()["my_status"] == "unread"

    def test_a_member_may_rate_a_public_book(self, client, admin, member, make_book):
        # Read access is enough, like status: it changes nothing for anyone else.
        book = make_book(admin["headers"])

        res = client.patch(
            f"/api/books/{book['id']}/rating", json={"rating": 2}, headers=member["headers"]
        )

        assert res.status_code == 200

    def test_another_members_private_book_is_not_rateable(
        self, client, admin, member, make_book
    ):
        book = make_book(admin["headers"], is_private=True)

        res = client.patch(
            f"/api/books/{book['id']}/rating", json={"rating": 2}, headers=member["headers"]
        )

        assert res.status_code == 404

    def test_out_of_range_is_rejected(self, client, admin, make_book):
        book = make_book(admin["headers"])
        for value in (0, 6, -1):
            res = client.patch(
                f"/api/books/{book['id']}/rating",
                json={"rating": value},
                headers=admin["headers"],
            )
            assert res.status_code == 422, value

    def test_requires_authentication(self, client, admin, make_book):
        book = make_book(admin["headers"])
        assert client.patch(f"/api/books/{book['id']}/rating", json={"rating": 3}).status_code == 401


def set_status(client, headers, book_id: int, status: str):
    return client.put(f"/api/books/{book_id}/status", json={"status": status}, headers=headers)


class TestReadingDates:
    """Stamped from the status transition, never typed in.

    Nobody fills in a date field; everybody moves a book to "reading" when they
    start it.
    """

    def test_starting_stamps_the_start(self, client, admin, make_book):
        book = make_book(admin["headers"])

        body = set_status(client, admin["headers"], book["id"], "reading").json()

        assert body["my_started_at"] is not None
        assert body["my_finished_at"] is None

    def test_finishing_stamps_the_finish(self, client, admin, make_book):
        book = make_book(admin["headers"])
        set_status(client, admin["headers"], book["id"], "reading")

        body = set_status(client, admin["headers"], book["id"], "read").json()

        assert body["my_finished_at"] is not None

    def test_going_straight_to_read_stamps_both(self, client, admin, make_book):
        """Plenty of books are only ever marked once, after the fact.

        A finish date with no start reads like missing data.
        """
        book = make_book(admin["headers"])

        body = set_status(client, admin["headers"], book["id"], "read").json()

        assert body["my_started_at"] is not None
        assert body["my_finished_at"] is not None

    def test_re_selecting_the_same_status_does_not_move_the_date(
        self, client, admin, make_book
    ):
        """A UI with pressable buttons makes this easy to do by accident."""
        book = make_book(admin["headers"])
        first = set_status(client, admin["headers"], book["id"], "read").json()

        again = set_status(client, admin["headers"], book["id"], "read").json()

        assert again["my_finished_at"] == first["my_finished_at"]
        assert again["my_started_at"] == first["my_started_at"]

    def test_going_back_to_reading_clears_the_finish(self, client, admin, make_book):
        book = make_book(admin["headers"])
        set_status(client, admin["headers"], book["id"], "read")

        body = set_status(client, admin["headers"], book["id"], "reading").json()

        assert body["my_finished_at"] is None
        # The start survives: it did start, and that has not stopped being true.
        assert body["my_started_at"] is not None

    def test_going_back_to_unread_clears_both(self, client, admin, make_book):
        # Otherwise a book marked unread again stays in "books finished this
        # year" forever.
        book = make_book(admin["headers"])
        set_status(client, admin["headers"], book["id"], "read")

        body = set_status(client, admin["headers"], book["id"], "unread").json()

        assert body["my_started_at"] is None
        assert body["my_finished_at"] is None

    def test_want_to_read_clears_both(self, client, admin, make_book):
        book = make_book(admin["headers"])
        set_status(client, admin["headers"], book["id"], "read")

        body = set_status(client, admin["headers"], book["id"], "want_to_read").json()

        assert body["my_started_at"] is None
        assert body["my_finished_at"] is None

    def test_dates_are_personal(self, client, admin, member, make_book):
        book = make_book(admin["headers"])
        set_status(client, admin["headers"], book["id"], "read")

        seen_by_member = client.get(f"/api/books/{book['id']}", headers=member["headers"])

        assert seen_by_member.json()["my_finished_at"] is None


class TestUnratedFilter:
    def test_lists_only_what_you_have_not_rated(self, client, admin, make_book):
        rated = make_book(admin["headers"], title="Rated")
        make_book(admin["headers"], title="Unrated")
        client.patch(
            f"/api/books/{rated['id']}/rating", json={"rating": 4}, headers=admin["headers"]
        )

        res = client.get("/api/books", params={"unrated": True}, headers=admin["headers"])

        assert [b["title"] for b in res.json()["items"]] == ["Unrated"]

    def test_is_personal(self, client, admin, member, make_book):
        """Another member's rating does not remove a book from your own list."""
        book = make_book(admin["headers"], title="Dune")
        client.patch(
            f"/api/books/{book['id']}/rating", json={"rating": 4}, headers=admin["headers"]
        )

        res = client.get("/api/books", params={"unrated": True}, headers=member["headers"])

        assert [b["title"] for b in res.json()["items"]] == ["Dune"]

    def test_a_status_without_a_rating_still_counts_as_unrated(
        self, client, admin, make_book
    ):
        # The row exists but `rating` is null, which is the case a naive
        # "no user_books row" implementation would miss.
        book = make_book(admin["headers"], title="Dune")
        set_status(client, admin["headers"], book["id"], "read")

        res = client.get("/api/books", params={"unrated": True}, headers=admin["headers"])

        assert [b["title"] for b in res.json()["items"]] == ["Dune"]

    def test_combines_with_another_filter(self, client, admin, make_book):
        """The unrated filter must not depend on the conditional status join."""
        make_book(admin["headers"], title="Unrated")
        res = client.get(
            "/api/books",
            params={"unrated": True, "status": "unread"},
            headers=admin["headers"],
        )
        assert [b["title"] for b in res.json()["items"]] == ["Unrated"]
