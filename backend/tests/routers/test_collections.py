"""Naming parts of the shelf, and what a name is allowed to do.

The rule every test here exists to protect is that a collection is **shelving,
never permission**. It groups books; it hides none, reveals none, and the
counts it serves are filtered by the same predicate as everything else.
"""

import pytest
from sqlalchemy.exc import IntegrityError

from models import Book, Collection


def make_collection(client, headers, name):
    return client.post("/api/collections", json={"name": name}, headers=headers)


def collections(client, headers):
    return client.get("/api/collections", headers=headers)


def file_book(client, headers, book_id, collection_id):
    return client.patch(
        f"/api/books/{book_id}/collection",
        json={"collection_id": collection_id},
        headers=headers,
    )


class TestMakingOne:
    def test_any_member_can_make_one(self, client, member):
        res = make_collection(client, member["headers"], "Ebooks")

        assert res.status_code == 201, res.text
        assert res.json()["name"] == "Ebooks"

    def test_a_new_collection_holds_nothing(self, client, admin):
        assert make_collection(client, admin["headers"], "Sold").json()["book_count"] == 0

    def test_the_name_is_tidied(self, client, admin):
        assert (
            make_collection(client, admin["headers"], "  Read   twice  ").json()["name"]
            == "Read twice"
        )

    def test_a_name_of_only_spaces_is_refused(self, client, admin):
        assert make_collection(client, admin["headers"], "   ").status_code == 422

    def test_a_name_that_already_exists_returns_that_collection(self, client, admin):
        """Somebody typing a name that is there means that shelf, not an error."""
        first = make_collection(client, admin["headers"], "Ebooks").json()

        again = make_collection(client, admin["headers"], "ebooks")

        assert again.status_code == 201
        assert again.json()["id"] == first["id"]
        assert len(collections(client, admin["headers"]).json()) == 1

    def test_the_database_refuses_a_case_insensitive_clash(self, db):
        """The handler's check races; `uq_collections_name_nocase` does not."""
        db.add(Collection(name="Ebooks"))
        db.commit()
        db.add(Collection(name="EBOOKS"))
        with pytest.raises(IntegrityError):
            db.commit()
        db.rollback()

    def test_an_anonymous_caller_is_refused(self, client):
        assert client.post("/api/collections", json={"name": "Ebooks"}).status_code == 401


class TestListing:
    def test_they_are_ordered_case_insensitively(self, client, admin):
        for name in ("zola", "Ebooks", "apples"):
            make_collection(client, admin["headers"], name)

        assert [row["name"] for row in collections(client, admin["headers"]).json()] == [
            "apples",
            "Ebooks",
            "zola",
        ]

    def test_the_count_is_what_the_caller_can_see(self, client, admin, member, make_book):
        """The count is the leak a collection could carry, so it is filtered."""
        shelf = make_collection(client, admin["headers"], "Ebooks").json()
        mine = make_book(admin["headers"], title="Public", isbn="9780441013593")
        secret = make_book(admin["headers"], title="Secret", is_private=True)
        file_book(client, admin["headers"], mine["id"], shelf["id"])
        file_book(client, admin["headers"], secret["id"], shelf["id"])

        as_admin = collections(client, admin["headers"]).json()[0]
        as_member = collections(client, member["headers"]).json()[0]

        assert as_admin["book_count"] == 2
        assert as_member["book_count"] == 1

    def test_a_trashed_book_stops_counting(self, client, admin, make_book):
        shelf = make_collection(client, admin["headers"], "Ebooks").json()
        book = make_book(admin["headers"], title="Dune")
        file_book(client, admin["headers"], book["id"], shelf["id"])

        client.delete(f"/api/books/{book['id']}", headers=admin["headers"])

        assert collections(client, admin["headers"]).json()[0]["book_count"] == 0


class TestRenaming:
    def test_any_member_can_rename_one(self, client, admin, member):
        shelf = make_collection(client, admin["headers"], "Ebooks").json()

        res = client.patch(
            f"/api/collections/{shelf['id']}",
            json={"name": "E books"},
            headers=member["headers"],
        )

        assert res.status_code == 200, res.text
        assert res.json()["name"] == "E books"

    def test_renaming_onto_an_existing_name_is_refused(self, client, admin):
        """A rename onto an occupied name would silently merge two shelves."""
        make_collection(client, admin["headers"], "Ebooks")
        sold = make_collection(client, admin["headers"], "Sold").json()

        res = client.patch(
            f"/api/collections/{sold['id']}",
            json={"name": "ebooks"},
            headers=admin["headers"],
        )

        assert res.status_code == 409

    def test_renaming_to_its_own_name_is_allowed(self, client, admin):
        shelf = make_collection(client, admin["headers"], "Ebooks").json()

        res = client.patch(
            f"/api/collections/{shelf['id']}",
            json={"name": "EBOOKS"},
            headers=admin["headers"],
        )

        assert res.status_code == 200
        assert res.json()["name"] == "EBOOKS"

    def test_an_unknown_collection_is_404(self, client, admin):
        res = client.patch(
            "/api/collections/999", json={"name": "Ebooks"}, headers=admin["headers"]
        )
        assert res.status_code == 404

    def test_the_books_keep_their_shelf(self, client, admin, make_book):
        shelf = make_collection(client, admin["headers"], "Ebooks").json()
        book = make_book(admin["headers"], title="Dune")
        file_book(client, admin["headers"], book["id"], shelf["id"])

        client.patch(
            f"/api/collections/{shelf['id']}",
            json={"name": "Digital"},
            headers=admin["headers"],
        )

        assert (
            client.get(f"/api/books/{book['id']}", headers=admin["headers"]).json()[
                "collection_name"
            ]
            == "Digital"
        )


class TestDeleting:
    def test_only_an_admin_may_delete_one(self, client, admin, member):
        """Same asymmetry as tags: creating is undone by deleting, and deleting
        empties a label off every book in the house at once."""
        shelf = make_collection(client, member["headers"], "Ebooks").json()

        assert (
            client.delete(
                f"/api/collections/{shelf['id']}", headers=member["headers"]
            ).status_code
            == 403
        )
        assert (
            client.delete(
                f"/api/collections/{shelf['id']}", headers=admin["headers"]
            ).status_code
            == 204
        )

    def test_the_books_survive_and_are_unfiled(self, client, admin, make_book, db):
        shelf = make_collection(client, admin["headers"], "Ebooks").json()
        book = make_book(admin["headers"], title="Dune")
        file_book(client, admin["headers"], book["id"], shelf["id"])

        client.delete(f"/api/collections/{shelf['id']}", headers=admin["headers"])

        survivor = client.get(f"/api/books/{book['id']}", headers=admin["headers"])
        assert survivor.status_code == 200
        assert survivor.json()["collection_id"] is None
        assert db.query(Book).count() == 1

    def test_somebody_elses_private_book_is_unfiled_too(
        self, client, admin, member, make_book, db
    ):
        """The unfiling is the database's rule, so it reaches rows the deleting
        admin cannot see. A row left pointing at a destroyed collection would
        be a dangling foreign key."""
        shelf = make_collection(client, admin["headers"], "Ebooks").json()
        hidden = make_book(member["headers"], title="Theirs", is_private=True)
        file_book(client, member["headers"], hidden["id"], shelf["id"])

        client.delete(f"/api/collections/{shelf['id']}", headers=admin["headers"])

        assert db.get(Book, hidden["id"]).collection_id is None

    def test_an_unknown_collection_is_404(self, client, admin):
        assert (
            client.delete("/api/collections/999", headers=admin["headers"]).status_code
            == 404
        )
