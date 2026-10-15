"""Requesting access to a digital copy, and the holder's answer.

The holder is the member who added the book. A request is read by its
requester and its holder only, on a book the Shelf lets the caller see.
"""

import pytest


def request(client, who, book):
    return client.post(f"/api/books/{book['id']}/access-requests", headers=who["headers"])


def listing(client, who, book):
    return client.get(f"/api/books/{book['id']}/access-requests", headers=who["headers"])


def decide(client, who, book, request_id, granted=True):
    return client.put(
        f"/api/books/{book['id']}/access-requests/{request_id}",
        json={"granted": granted},
        headers=who["headers"],
    )


def with_a_file(client, who, book):
    res = client.post(
        f"/api/books/{book['id']}/digital-references",
        json={"root_label": "/audio", "relative_path": "a/b.m4b"},
        headers=who["headers"],
    )
    assert res.status_code == 200, res.text
    return book


def merge(client, who, keeper, loser):
    res = client.post(
        "/api/books/merge",
        json={"book_ids": [keeper["id"], loser["id"]], "keep_id": keeper["id"]},
        headers=who["headers"],
    )
    assert res.status_code == 200, res.text


@pytest.fixture
def ebook(admin, make_book):
    return make_book(admin["headers"], title="A file", format="ebook")


class TestRequesting:
    def test_a_member_asks_and_the_request_waits(self, client, member, ebook):
        res = request(client, member, ebook)
        assert res.status_code == 201
        assert res.json()["status"] == "pending"
        assert res.json()["requested_by"]["username"] == "member"

    def test_a_copy_that_is_not_digital_is_lent_not_requested(
        self, client, admin, member, make_book
    ):
        book = make_book(admin["headers"], format="paperback")
        res = request(client, member, book)
        assert res.status_code == 409
        assert res.json()["detail"]["code"] == "not_digital"

    def test_the_holder_has_nobody_to_ask(self, client, admin, ebook):
        res = request(client, admin, ebook)
        assert res.json()["detail"]["code"] == "no_holder"

    def test_a_waiting_request_is_not_doubled(self, client, member, ebook):
        request(client, member, ebook)
        res = request(client, member, ebook)
        assert res.json()["detail"]["code"] == "already_requested"

    def test_a_granted_request_is_not_asked_again(self, client, admin, member, ebook):
        asked = request(client, member, ebook).json()
        decide(client, admin, ebook, asked["id"])
        res = request(client, member, ebook)
        assert res.json()["detail"]["code"] == "already_requested"

    def test_an_audiobook_with_a_file_is_requested(self, client, admin, member, make_book):
        book = with_a_file(client, admin, make_book(admin["headers"], format="audiobook"))
        assert request(client, member, book).status_code == 201

    def test_an_audiobook_with_no_file_is_a_disc_and_is_lent(
        self, client, admin, member, make_book
    ):
        book = make_book(admin["headers"], format="audiobook")
        assert request(client, member, book).json()["detail"]["code"] == "not_digital"

    def test_a_declined_request_may_be_asked_again(self, client, admin, member, ebook):
        first = request(client, member, ebook).json()
        decide(client, admin, ebook, first["id"], granted=False)
        assert request(client, member, ebook).status_code == 201

    def test_a_private_book_of_another_member_is_not_found(
        self, client, admin, member, make_book
    ):
        hidden = make_book(admin["headers"], format="ebook", is_private=True)
        assert request(client, member, hidden).status_code == 404


class TestAnswering:
    def test_a_grant_records_who_and_when(self, client, admin, member, ebook):
        asked = request(client, member, ebook).json()
        res = decide(client, admin, ebook, asked["id"])
        assert res.status_code == 200
        assert res.json()["status"] == "granted"
        assert res.json()["decided_by"]["username"] == "admin"
        assert res.json()["decided_at"] is not None

    def test_the_requester_cannot_answer_their_own(self, client, member, ebook):
        asked = request(client, member, ebook).json()
        assert decide(client, member, ebook, asked["id"]).status_code == 403

    def test_an_answer_is_final(self, client, admin, member, ebook):
        asked = request(client, member, ebook).json()
        decide(client, admin, ebook, asked["id"])
        res = decide(client, admin, ebook, asked["id"], granted=False)
        assert res.json()["detail"]["code"] == "already_answered"


class TestWhoReadsARequest:
    def test_the_holder_reads_every_request(self, client, admin, member, other_user, ebook):
        request(client, member, ebook)
        request(client, other_user, ebook)
        assert len(listing(client, admin, ebook).json()) == 2

    def test_another_member_reads_only_their_own(
        self, client, member, other_user, ebook
    ):
        request(client, member, ebook)
        assert listing(client, other_user, ebook).json() == []

    def test_another_member_cannot_answer_one_they_cannot_read(
        self, client, member, other_user, ebook
    ):
        asked = request(client, member, ebook).json()
        assert decide(client, other_user, ebook, asked["id"]).status_code == 404


class TestMergingTwoBooks:
    """The holder is the one asked, whoever's entry the request ends up on."""

    def test_a_request_moves_to_the_survivor(self, client, admin, member, make_book):
        keeper = make_book(admin["headers"], title="One", format="ebook")
        loser = make_book(admin["headers"], title="Two", format="ebook")
        request(client, member, loser)
        merge(client, admin, keeper, loser)
        assert len(listing(client, member, keeper).json()) == 1

    def test_a_merge_into_the_requesters_entry_does_not_make_them_the_holder(
        self, client, admin, member, make_book
    ):
        held = make_book(admin["headers"], title="Held", format="ebook")
        asked = request(client, member, held).json()
        own = make_book(member["headers"], title="Own", format="ebook")
        merge(client, member, own, held)
        assert decide(client, member, own, asked["id"]).status_code == 403
        assert decide(client, admin, own, asked["id"]).json()["status"] == "granted"

    def test_a_merge_into_a_third_members_entry_shows_them_nothing(
        self, client, admin, member, other_user, make_book
    ):
        held = make_book(admin["headers"], title="Held", format="ebook")
        asked = request(client, member, held).json()
        third = make_book(other_user["headers"], title="Third", format="ebook")
        merge(client, other_user, third, held)
        assert listing(client, other_user, third).json() == []
        assert decide(client, other_user, third, asked["id"]).status_code == 404
        assert len(listing(client, admin, third).json()) == 1
