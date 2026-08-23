"""Lending willingness on a book, and "ask me about it" per member.

Two fields that look alike and are not. One is a standing intention about an
object and is shared by the household; the other is a fact about one reader
that every other reader is meant to see. This file is mostly about keeping
those two apart.

The loan side of willingness lives in tests/routers/test_loans.py, beside the
endpoint that enforces it.
"""

import pytest

from tests.helpers import items, titles


def patch_details(client, headers, book_id: int, **fields):
    return client.patch(f"/api/books/{book_id}", json=fields, headers=headers)


def set_discuss(client, headers, book_id: int, wants: bool):
    return client.patch(
        f"/api/books/{book_id}/discuss",
        json={"wants_to_discuss": wants},
        headers=headers,
    )


def listed(client, headers, **params):
    return client.get("/api/books", params=params, headers=headers)


class TestLendingWillingness:
    def test_a_new_book_has_not_been_asked(self, client, admin, make_book):
        """Null, not a default. An unanswered question is not an answer."""
        assert make_book(admin["headers"])["lending"] is None

    def test_it_is_set_like_any_other_detail(self, client, admin, make_book):
        book = make_book(admin["headers"])

        res = patch_details(client, admin["headers"], book["id"], lending="happy")

        assert res.status_code == 200
        assert res.json()["lending"] == "happy"

    def test_an_explicit_null_puts_it_back_to_unanswered(self, client, admin, make_book):
        book = make_book(admin["headers"])
        patch_details(client, admin["headers"], book["id"], lending="never")

        res = patch_details(client, admin["headers"], book["id"], lending=None)

        assert res.json()["lending"] is None

    def test_a_value_outside_the_three_is_refused(self, client, admin, make_book):
        book = make_book(admin["headers"])
        res = patch_details(client, admin["headers"], book["id"], lending="maybe")
        assert res.status_code == 422

    def test_it_is_independent_of_ownership(self, client, admin, make_book):
        """Different axes. Willing to lend says nothing about the shelf."""
        book = make_book(admin["headers"])
        patch_details(client, admin["headers"], book["id"], lending="happy")

        body = client.get(f"/api/books/{book['id']}", headers=admin["headers"]).json()

        assert body["ownership"] == "owned"
        assert body["lending"] == "happy"


class TestFilteringByWillingness:
    @pytest.fixture
    def shelf(self, client, admin, make_book):
        happy = make_book(admin["headers"], title="Lend me")
        never = make_book(admin["headers"], title="Keep me")
        make_book(admin["headers"], title="Unasked")
        patch_details(client, admin["headers"], happy["id"], lending="happy")
        patch_details(client, admin["headers"], never["id"], lending="never")

    def test_it_narrows_to_one_value(self, client, admin, shelf):
        assert titles(listed(client, admin["headers"], lending="happy")) == ["Lend me"]

    def test_an_unasked_book_matches_nothing(self, client, admin, shelf):
        """Null is not one of the three, so it is in none of the three views."""
        found = [
            title
            for value in ("happy", "never", "in_use")
            for title in titles(listed(client, admin["headers"], lending=value))
        ]
        assert "Unasked" not in found

    def test_no_filter_returns_everything(self, client, admin, shelf):
        assert len(titles(listed(client, admin["headers"]))) == 3

    def test_an_unknown_value_is_refused(self, client, admin, shelf):
        assert listed(client, admin["headers"], lending="sometimes").status_code == 422


class TestAskMeAboutThisBook:
    def test_nobody_has_offered_by_default(self, client, admin, make_book):
        book = make_book(admin["headers"])
        assert book["my_wants_to_discuss"] is False
        assert book["discuss_with"] == []

    def test_it_creates_the_row_that_did_not_exist(self, client, admin, db, make_book):
        """`user_books` rows are lazy, so this is the status and rating path
        again: the first thing set has to make the row."""
        from models import UserBook

        book = make_book(admin["headers"])
        assert db.query(UserBook).filter(UserBook.book_id == book["id"]).count() == 0

        res = set_discuss(client, admin["headers"], book["id"], True)

        assert res.status_code == 200
        assert res.json()["my_wants_to_discuss"] is True
        assert db.query(UserBook).filter(UserBook.book_id == book["id"]).count() == 1

    def test_it_leaves_the_reading_status_alone(self, client, admin, make_book):
        """Wanting to talk about a book is not a claim to have read it."""
        book = make_book(admin["headers"])

        body = set_discuss(client, admin["headers"], book["id"], True).json()

        assert body["my_status"] == "unread"
        assert body["my_started_at"] is None

    def test_it_can_be_withdrawn(self, client, admin, make_book):
        book = make_book(admin["headers"])
        set_discuss(client, admin["headers"], book["id"], True)

        body = set_discuss(client, admin["headers"], book["id"], False).json()

        assert body["my_wants_to_discuss"] is False
        assert body["discuss_with"] == []

    def test_read_access_is_enough(self, client, admin, member, make_book):
        """Like status and rating: it is the caller's own flag."""
        book = make_book(admin["headers"])
        assert set_discuss(client, member["headers"], book["id"], True).status_code == 200

    def test_another_members_private_book_is_404(self, client, admin, member, make_book):
        book = make_book(admin["headers"], is_private=True)
        assert set_discuss(client, member["headers"], book["id"], True).status_code == 404

    def test_two_members_can_disagree(self, client, admin, member, make_book):
        book = make_book(admin["headers"])
        set_discuss(client, admin["headers"], book["id"], True)

        mine = client.get(f"/api/books/{book['id']}", headers=admin["headers"]).json()
        theirs = client.get(f"/api/books/{book['id']}", headers=member["headers"]).json()

        assert mine["my_wants_to_discuss"] is True
        assert theirs["my_wants_to_discuss"] is False


class TestTheOfferIsVisibleToEverybody:
    """The whole point of the flag. A marker only its owner can see is not a
    way to be asked about anything."""

    def test_another_member_sees_who_offered(self, client, admin, member, make_book):
        book = make_book(admin["headers"])
        set_discuss(client, admin["headers"], book["id"], True)

        body = client.get(f"/api/books/{book['id']}", headers=member["headers"]).json()

        assert [user["username"] for user in body["discuss_with"]] == ["admin"]

    def test_it_discloses_no_reading_status(self, client, admin, member, make_book):
        """Seeing that somebody wants to talk must not say what they made of
        it: `my_status` is the caller's own, always."""
        book = make_book(admin["headers"])
        client.put(
            f"/api/books/{book['id']}/status",
            json={"status": "read"},
            headers=admin["headers"],
        )
        set_discuss(client, admin["headers"], book["id"], True)

        body = client.get(f"/api/books/{book['id']}", headers=member["headers"]).json()

        assert body["my_status"] == "unread"
        assert [user["username"] for user in body["discuss_with"]] == ["admin"]

    def test_several_members_are_listed_in_one_order(
        self, client, admin, member, other_user, make_book
    ):
        book = make_book(admin["headers"])
        for account in (other_user, admin, member):
            set_discuss(client, account["headers"], book["id"], True)

        body = client.get(f"/api/books/{book['id']}", headers=admin["headers"]).json()

        assert [user["username"] for user in body["discuss_with"]] == [
            "admin",
            "member",
            "other",
        ]

    def test_it_is_not_carried_on_a_book_nobody_offered(
        self, client, admin, member, make_book
    ):
        offered = make_book(admin["headers"], title="Talk to me")
        make_book(admin["headers"], title="Quiet")
        set_discuss(client, admin["headers"], offered["id"], True)

        by_title = {
            book["title"]: book["discuss_with"]
            for book in items(listed(client, member["headers"]))
        }

        assert by_title["Quiet"] == []
        assert len(by_title["Talk to me"]) == 1


class TestFilteringByTheOffer:
    def test_it_finds_what_anybody_offered(self, client, admin, member, make_book):
        """Anybody's, not the caller's. The filter has to select exactly the
        books that carry the marker the grid draws."""
        book = make_book(admin["headers"], title="Talk to me")
        make_book(admin["headers"], title="Quiet")
        set_discuss(client, admin["headers"], book["id"], True)

        assert titles(listed(client, member["headers"], discuss=True)) == ["Talk to me"]

    def test_it_is_off_unless_asked_for(self, client, admin, make_book):
        make_book(admin["headers"], title="Quiet")
        assert titles(listed(client, admin["headers"])) == ["Quiet"]

    def test_a_withdrawn_offer_drops_out(self, client, admin, make_book):
        book = make_book(admin["headers"], title="Talk to me")
        set_discuss(client, admin["headers"], book["id"], True)
        set_discuss(client, admin["headers"], book["id"], False)

        assert titles(listed(client, admin["headers"], discuss=True)) == []

    def test_it_composes_with_the_status_filter(self, client, admin, make_book):
        """The status filter adds its own UserBook join, which is exactly what
        made `unrated` need an explicit correlation. Same trap, same fix."""
        book = make_book(admin["headers"], title="Talk to me")
        set_discuss(client, admin["headers"], book["id"], True)

        res = listed(client, admin["headers"], discuss=True, status="unread")

        assert res.status_code == 200
        assert titles(res) == ["Talk to me"]

    def test_it_does_not_leak_a_private_book(self, client, admin, member, make_book):
        """`visible_to` still decides what is listed, whoever offered."""
        book = make_book(admin["headers"], title="Secret", is_private=True)
        set_discuss(client, admin["headers"], book["id"], True)

        assert titles(listed(client, member["headers"], discuss=True)) == []
