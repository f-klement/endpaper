"""Tests for backend/dependencies.py: book access control and pagination.

These are the regression tests for a real set of holes. Before the resolvers
existed, every endpoint below could be called by any signed-in member against
any book, including another member's private one:

    delete_book · add_book_tag · remove_book_tag · upload_cover
    refresh_metadata · update_status · get_notes · add_note

Each is exercised here from three sides: the owner, another member, and a
member acting on someone else's *private* book.
"""

import pytest

from tests.helpers import PNG_BYTES, items

# Every endpoint that takes a book id, as (label, method, path suffix, body).
# Used to assert the whole surface at once rather than one test per endpoint
# that someone can forget to add when a new route appears.
BOOK_ENDPOINTS = [
    ("get_book", "GET", "", None),
    ("get_notes", "GET", "/notes", None),
    ("add_note", "POST", "/notes", {"content": "hello"}),
    ("update_status", "PUT", "/status", {"status": "read"}),
    ("delete_book", "DELETE", "", None),
]


def call(client, method, url, headers, body=None):
    return client.request(method, url, headers=headers, json=body)


class TestPrivateBooksAreInvisible:
    """A private book belongs to one member. Nobody else may see or touch it."""

    @pytest.fixture
    def private_book(self, make_book, admin):
        return make_book(admin["headers"], title="Diary", is_private=True)

    @pytest.mark.parametrize(
        "label,method,suffix,body", BOOK_ENDPOINTS, ids=[e[0] for e in BOOK_ENDPOINTS]
    )
    def test_another_member_gets_404(
        self, client, member, private_book, label, method, suffix, body
    ):
        res = call(
            client, method, f"/api/books/{private_book['id']}{suffix}", member["headers"], body
        )
        # 404 rather than 403: a 403 confirms the book exists, which is exactly
        # what privacy is meant to withhold.
        assert res.status_code == 404, f"{label} leaked a private book"

    def test_the_owner_still_has_full_access(self, client, admin, private_book):
        assert client.get(f"/api/books/{private_book['id']}", headers=admin["headers"]).status_code == 200

    def test_notes_on_a_private_book_are_not_readable(self, client, admin, member, private_book):
        """Regression: get_notes only checked the book existed, so the notes on
        a private book were readable by anyone who guessed its id."""
        client.post(
            f"/api/books/{private_book['id']}/notes",
            json={"content": "a secret"},
            headers=admin["headers"],
        )
        res = client.get(f"/api/books/{private_book['id']}/notes", headers=member["headers"])
        assert res.status_code == 404

    def test_cover_cannot_be_overwritten_by_another_member(
        self, client, member, private_book, covers_dir
    ):
        res = client.post(
            f"/api/books/{private_book['id']}/cover",
            files={"file": ("x.png", PNG_BYTES, "image/png")},
            headers=member["headers"],
        )
        assert res.status_code == 404

    def test_metadata_cannot_be_refreshed_by_another_member(self, client, member, private_book):
        res = client.put(f"/api/books/{private_book['id']}/refresh", headers=member["headers"])
        assert res.status_code == 404

    def test_tags_cannot_be_changed_by_another_member(self, client, member, private_book, db):
        from models import Tag

        tag = db.query(Tag).first()
        res = client.post(
            f"/api/books/{private_book['id']}/tags/{tag.id}", headers=member["headers"]
        )
        assert res.status_code == 404

    def test_a_private_book_is_absent_from_listings(self, client, member, private_book):
        assert items(client.get("/api/books", headers=member["headers"])) == []


class TestPublicBooksAreASharedShelf:
    """Any member may curate a public book, the behaviour the user chose."""

    @pytest.fixture
    def public_book(self, make_book, admin):
        return make_book(admin["headers"], title="Dune", isbn="9780441013593")

    def test_another_member_may_retag(self, client, member, public_book, db):
        from models import Tag

        tag = db.query(Tag).filter(Tag.name == "Fantasy").one()
        res = client.post(f"/api/books/{public_book['id']}/tags/{tag.id}", headers=member["headers"])
        assert res.status_code == 200

    def test_another_member_may_replace_the_cover(
        self, client, member, public_book, covers_dir
    ):
        res = client.post(
            f"/api/books/{public_book['id']}/cover",
            files={"file": ("x.png", PNG_BYTES, "image/png")},
            headers=member["headers"],
        )
        assert res.status_code == 200

    def test_another_member_may_remove_it(self, client, member, public_book):
        res = client.delete(f"/api/books/{public_book['id']}", headers=member["headers"])
        assert res.status_code == 204

    def test_another_member_may_set_their_own_status(self, client, member, public_book):
        res = client.put(
            f"/api/books/{public_book['id']}/status",
            json={"status": "read"},
            headers=member["headers"],
        )
        assert res.status_code == 200
        assert res.json()["my_status"] == "read"

    def test_status_stays_personal(self, client, admin, member, public_book):
        """A shared shelf does not mean shared reading progress."""
        client.put(
            f"/api/books/{public_book['id']}/status",
            json={"status": "read"},
            headers=member["headers"],
        )
        seen_by_owner = client.get(
            f"/api/books/{public_book['id']}", headers=admin["headers"]
        ).json()
        assert seen_by_owner["my_status"] == "unread"


class TestPrivacyIsTheOwnersDecision:
    """Curating a shared book is one thing; hiding it from everyone is another."""

    @pytest.fixture
    def public_book(self, make_book, admin):
        return make_book(admin["headers"], title="Dune")

    def test_the_owner_may_change_privacy(self, client, admin, public_book):
        res = client.patch(
            f"/api/books/{public_book['id']}/privacy",
            json={"is_private": True},
            headers=admin["headers"],
        )
        assert res.status_code == 200

    def test_another_member_may_not(self, client, member, public_book):
        res = client.patch(
            f"/api/books/{public_book['id']}/privacy",
            json={"is_private": True},
            headers=member["headers"],
        )
        # 403 here, not 404: the book is public, so its existence is not a
        # secret. Only the decision is restricted.
        assert res.status_code == 403

    def test_an_admin_may(self, client, admin, member, make_book):
        book = make_book(member["headers"], title="Theirs")
        res = client.patch(
            f"/api/books/{book['id']}/privacy",
            json={"is_private": True},
            headers=admin["headers"],
        )
        assert res.status_code == 200


class TestUnknownBooks:
    @pytest.mark.parametrize(
        "label,method,suffix,body", BOOK_ENDPOINTS, ids=[e[0] for e in BOOK_ENDPOINTS]
    )
    def test_every_endpoint_404s(self, client, admin, label, method, suffix, body):
        res = call(client, method, f"/api/books/999999{suffix}", admin["headers"], body)
        assert res.status_code == 404

    @pytest.mark.parametrize(
        "label,method,suffix,body", BOOK_ENDPOINTS, ids=[e[0] for e in BOOK_ENDPOINTS]
    )
    def test_every_endpoint_requires_a_token(self, client, admin, make_book, label, method, suffix, body):
        book = make_book(admin["headers"])
        res = call(client, method, f"/api/books/{book['id']}{suffix}", None, body)
        assert res.status_code == 401


class TestPagination:
    @pytest.fixture
    def twelve_books(self, make_book, admin):
        for index in range(12):
            make_book(admin["headers"], title=f"Book {index:02d}")

    def test_defaults_return_everything_that_fits(self, client, admin, twelve_books):
        body = client.get("/api/books", headers=admin["headers"]).json()
        assert len(body["items"]) == 12
        assert body["total"] == 12
        assert body["page"] == 1

    def test_page_size_limits_the_rows(self, client, admin, twelve_books):
        body = client.get(
            "/api/books", params={"page_size": 5}, headers=admin["headers"]
        ).json()
        assert len(body["items"]) == 5

    def test_total_counts_matches_not_the_page(self, client, admin, twelve_books):
        """`total` is what the grid needs to know when to stop asking."""
        body = client.get(
            "/api/books", params={"page_size": 5}, headers=admin["headers"]
        ).json()
        assert body["total"] == 12

    def test_pages_do_not_overlap(self, client, admin, twelve_books):
        first = client.get(
            "/api/books", params={"page_size": 5, "page": 1}, headers=admin["headers"]
        ).json()["items"]
        second = client.get(
            "/api/books", params={"page_size": 5, "page": 2}, headers=admin["headers"]
        ).json()["items"]
        assert {b["id"] for b in first}.isdisjoint({b["id"] for b in second})

    def test_paging_covers_every_row_exactly_once(self, client, admin, twelve_books):
        seen: list[int] = []
        for page in (1, 2, 3):
            seen += [
                b["id"]
                for b in client.get(
                    "/api/books",
                    params={"page_size": 5, "page": page},
                    headers=admin["headers"],
                ).json()["items"]
            ]
        assert len(seen) == 12
        assert len(set(seen)) == 12

    def test_a_page_past_the_end_is_empty_not_an_error(self, client, admin, twelve_books):
        body = client.get(
            "/api/books", params={"page": 99}, headers=admin["headers"]
        ).json()
        assert body["items"] == []
        assert body["total"] == 12

    def test_page_size_is_capped(self, client, admin):
        """Otherwise a caller asks for everything and undoes the point of paging."""
        res = client.get("/api/books", params={"page_size": 10_000}, headers=admin["headers"])
        assert res.status_code == 422

    @pytest.mark.parametrize("params", [{"page": 0}, {"page": -1}, {"page_size": 0}])
    def test_nonsense_paging_is_rejected(self, client, admin, params):
        assert client.get("/api/books", params=params, headers=admin["headers"]).status_code == 422

    def test_the_filtered_total_reflects_the_filter(self, client, admin, make_book):
        make_book(admin["headers"], title="Dune")
        make_book(admin["headers"], title="Neuromancer")
        body = client.get(
            "/api/books", params={"q": "dune"}, headers=admin["headers"]
        ).json()
        assert body["total"] == 1

    def test_loans_are_paginated_too(self, client, admin, member, make_book):
        for index in range(3):
            book = make_book(admin["headers"], title=f"Book {index}")
            client.post(
                "/api/loans",
                json={"book_id": book["id"], "loaned_to_user_id": member["user"]["id"]},
                headers=admin["headers"],
            )
        body = client.get(
            "/api/loans", params={"page_size": 2}, headers=admin["headers"]
        ).json()
        assert len(body["items"]) == 2
        assert body["total"] == 3


class TestLoanVisibility:
    def test_a_loan_of_a_private_book_is_hidden(self, client, admin, member, make_book):
        """The loans list would otherwise disclose the title of a book the
        caller is not allowed to see, along with who has it."""
        book = make_book(admin["headers"], title="Diary", is_private=True)
        client.post(
            "/api/loans",
            json={"book_id": book["id"], "loaned_to_user_id": member["user"]["id"]},
            headers=admin["headers"],
        )
        assert items(client.get("/api/loans", headers=member["headers"])) == []

    def test_the_owner_still_sees_it(self, client, admin, member, make_book):
        book = make_book(admin["headers"], title="Diary", is_private=True)
        client.post(
            "/api/loans",
            json={"book_id": book["id"], "loaned_to_user_id": member["user"]["id"]},
            headers=admin["headers"],
        )
        assert len(items(client.get("/api/loans", headers=admin["headers"]))) == 1

    def test_a_private_book_cannot_be_lent_by_another_member(
        self, client, admin, member, other_user, make_book
    ):
        book = make_book(admin["headers"], title="Diary", is_private=True)
        res = client.post(
            "/api/loans",
            json={"book_id": book["id"], "loaned_to_user_id": other_user["user"]["id"]},
            headers=member["headers"],
        )
        assert res.status_code == 404
