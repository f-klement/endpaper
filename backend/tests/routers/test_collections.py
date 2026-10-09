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

    def test_a_control_character_is_removed_from_the_name(self, client, admin):
        """The name is case-insensitively unique, so an invisible character is
        a second shelf spelled like the first."""
        res = make_collection(client, admin["headers"], "Read\u0000twice")

        assert res.json()["name"] == "Readtwice"

    def test_a_name_of_only_control_characters_is_refused(self, client, admin):
        assert (
            make_collection(client, admin["headers"], "\u0000\u0001").status_code
            == 422
        )

    def test_a_name_that_already_exists_returns_that_collection(self, client, admin):
        """Somebody typing a name that is there means that shelf, not an error."""
        first = make_collection(client, admin["headers"], "Ebooks").json()

        again = make_collection(client, admin["headers"], "ebooks")

        assert again.status_code == 201
        assert again.json()["id"] == first["id"]
        assert len(collections(client, admin["headers"]).json()) == 1

    def test_the_collision_answers_with_the_stored_spelling(self, client, admin):
        """What the guess buys, pinned rather than described.

        The create hands back the stored row, so a caller who typed `ebooks`
        learns the shelf is called `Ebooks`. The name space is folded and
        globally unique, so that is reachable by guessing, and it is why
        `Shelving`'s "not closed" paragraph names the spelling and not only the
        existence. Returning the typed name instead is **not** the fix: the
        caller asked for that shelf and should see its real name.
        """
        make_collection(client, admin["headers"], "Ebooks")

        again = make_collection(client, admin["headers"], "ebooks")

        assert again.json()["name"] == "Ebooks"

    def test_the_database_refuses_a_case_insensitive_clash(self, db):
        """The handler's check races; `uq_collections_name_folded` does not."""
        db.add(Collection(name="Ebooks"))
        db.commit()
        db.add(Collection(name="EBOOKS"))
        with pytest.raises(IntegrityError):
            db.commit()
        db.rollback()

    def test_a_non_ascii_case_variant_returns_that_collection(self, client, admin):
        """Issue #77. This answered 201 with a second id, and the library then
        held two shelves a picker cannot tell apart. It is the ASCII case above
        with one letter changed, and it behaved differently because SQLite's
        `lower()` folds ASCII and nothing else."""
        first = make_collection(client, admin["headers"], "Ästhetik").json()

        again = make_collection(client, admin["headers"], "ästhetik")

        assert again.status_code == 201
        assert again.json()["id"] == first["id"]
        assert len(collections(client, admin["headers"]).json()) == 1

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

    def test_renaming_onto_a_non_ascii_case_variant_is_refused(self, client, admin):
        """409 and not 500, which is the distinction that matters here.

        `_named` and the unique index both fold in Python now. Had only the
        check been fixed, it would have found no clash, the insert would have
        hit the index, and the tag version of this bug is exactly that: an
        `IntegrityError` reaching the client as a 500.
        """
        make_collection(client, admin["headers"], "Ästhetik")
        sold = make_collection(client, admin["headers"], "Sold").json()

        res = client.patch(
            f"/api/collections/{sold['id']}",
            json={"name": "ästhetik"},
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


class TestWhoMayBeToldACollectionExists:
    """The list is what the caller may be told about, not what the library has.

    The rule is `shelving.Shelving` and its docstring carries the arms, the
    non monotonicity and the case that stays uncovered. What is pinned here is
    the behaviour a member sees, written before the module existed so the
    module is checked against the spec rather than the spec against the module.

    **Three of these arms were already in this file under other names**, which
    is what made the naive port of the tag rule red before anybody ran it:
    `test_they_are_ordered_case_insensitively` lists three empty collections,
    and `test_a_trashed_book_stops_counting` indexes `json()[0]` after trashing
    the only book. Neither was written for this rule. They are left where they
    are; these say the same things as sentences.
    """

    def test_a_collection_holding_only_a_hidden_book_is_not_listed(
        self, client, admin, member, make_book
    ):
        """The disclosure the ticket measured. The name was the evidence that
        somebody's books are filed somewhere, served on every page load."""
        shelf = make_collection(client, admin["headers"], "Divorce paperwork").json()
        secret = make_book(admin["headers"], title="Secret", is_private=True)
        file_book(client, admin["headers"], secret["id"], shelf["id"])

        assert collections(client, member["headers"]).json() == []
        assert [row["name"] for row in collections(client, admin["headers"]).json()] == [
            "Divorce paperwork"
        ]

    def test_a_collection_holding_a_visible_book_is_listed(
        self, client, admin, member, make_book
    ):
        """The arm that proves the rule does not over withhold."""
        shelf = make_collection(client, admin["headers"], "Ebooks").json()
        book = make_book(admin["headers"], title="Dune")
        file_book(client, admin["headers"], book["id"], shelf["id"])

        assert [row["name"] for row in collections(client, member["headers"]).json()] == [
            "Ebooks"
        ]

    def test_an_empty_collection_is_listed_for_everybody(self, client, admin, member):
        """A collection naming no book discloses no book, so withholding it
        buys nothing and costs the page it is made on."""
        make_collection(client, admin["headers"], "Sold")

        assert [row["name"] for row in collections(client, member["headers"]).json()] == [
            "Sold"
        ]

    def test_the_member_who_just_made_one_can_still_see_it(self, client, member):
        """The false refusal a count based rule ships, and it is a loop rather
        than a recoverable state: the create answers 201, the list refetches
        and shows nothing, and retyping the name reproduces it exactly."""
        make_collection(client, member["headers"], "Mine")

        assert [row["name"] for row in collections(client, member["headers"]).json()] == [
            "Mine"
        ]

    def test_a_collection_only_your_own_trash_carries_stays_listed(
        self, client, admin, make_book
    ):
        """Trashing the last book on a shelf must not destroy your own access
        to the shelf that book comes back into when it is restored."""
        shelf = make_collection(client, admin["headers"], "Ebooks").json()
        book = make_book(admin["headers"], title="Dune")
        file_book(client, admin["headers"], book["id"], shelf["id"])

        client.delete(f"/api/books/{book['id']}", headers=admin["headers"])

        listed = collections(client, admin["headers"]).json()
        assert [row["name"] for row in listed] == ["Ebooks"]
        assert listed[0]["book_count"] == 0

    def test_a_private_book_in_another_members_trash_does_not_carry_it_for_you(
        self, client, admin, member, make_book
    ):
        """The trash arm reaches exactly as far as the shelf does, no further:
        a private book stays private after it is deleted, so the collection
        holding it stays withheld.

        **Named for the private case, because that is the only case it
        covers.** It was called "somebody else's trash does not carry it for
        you", which is false for a public book and is the sentence the
        companion below was written against: a fixture that only ever agreed
        with the implementation.
        """
        shelf = make_collection(client, admin["headers"], "Ebooks").json()
        secret = make_book(admin["headers"], title="Secret", is_private=True)
        file_book(client, admin["headers"], secret["id"], shelf["id"])
        client.delete(f"/api/books/{secret['id']}", headers=admin["headers"])

        assert collections(client, member["headers"]).json() == []

    def test_a_public_book_in_another_members_trash_does_keep_it_listed(
        self, client, admin, member, make_book
    ):
        """The other direction of the same arm, and what the pair is for.

        `in_trash_for` is trashed **and visible**, never trashed **and
        theirs**, so a public book the admin deleted is in the member's trash
        too and keeps the shelf it was filed on listed for them. **Arm 3
        cannot explain this**: a book carries the collection, so the listing
        comes from the trash arm or from nowhere.
        """
        shelf = make_collection(client, admin["headers"], "Ebooks").json()
        book = make_book(admin["headers"], title="Dune")
        file_book(client, admin["headers"], book["id"], shelf["id"])
        client.delete(f"/api/books/{book['id']}", headers=admin["headers"])

        listed = collections(client, member["headers"]).json()
        assert [row["name"] for row in listed] == ["Ebooks"]
        assert listed[0]["book_count"] == 0

    def test_destroying_the_hidden_book_gives_the_collection_back(
        self, client, admin, member, make_book
    ):
        """The non monotonic transition, which is the behaviour most likely to
        be read as a bug and "fixed".

        Hidden while it holds one invisible book, public again once that book
        is gone, because the rule tracks what there is to disclose. The
        transition is itself observable and no bound on that is claimed here or
        at the site.
        """
        shelf = make_collection(client, admin["headers"], "Sold").json()
        secret = make_book(admin["headers"], title="Secret", is_private=True)
        file_book(client, admin["headers"], secret["id"], shelf["id"])
        assert collections(client, member["headers"]).json() == []

        client.delete(f"/api/books/{secret['id']}", headers=admin["headers"])
        client.delete(f"/api/books/{secret['id']}/permanent", headers=admin["headers"])

        assert [row["name"] for row in collections(client, member["headers"]).json()] == [
            "Sold"
        ]

    def test_a_zero_count_no_longer_means_books_you_cannot_see(
        self, client, admin, member, make_book
    ):
        """What the fix buys a reader rather than what it withholds.

        `book_count: 0` used to mean "empty, or holding books hidden from you",
        so the filtered count was readable against the unfiltered row set. The
        rows that made it readable are gone.
        """
        hidden = make_collection(client, admin["headers"], "Hidden").json()
        secret = make_book(admin["headers"], title="Secret", is_private=True)
        file_book(client, admin["headers"], secret["id"], hidden["id"])
        make_collection(client, admin["headers"], "Empty")

        rows = collections(client, member["headers"]).json()

        assert [(row["name"], row["book_count"]) for row in rows] == [("Empty", 0)]

    def test_the_list_costs_three_statements_whatever_it_holds(
        self, client, admin, member, make_book
    ):
        """Three arms, three grouped statements, none of them per row.

        Exact and not a ceiling: a smaller count is a weaker inequality, so a
        ceiling goes on passing with the batching deleted. The fourth statement
        is the table read itself; the rest of a request's SELECTs are the
        session lookup, which is why this counts the arms rather than the
        request.
        """
        from tests.helpers import rows_at_the_engine

        for name in ("One", "Two", "Three"):
            shelf = make_collection(client, admin["headers"], name).json()
            book = make_book(admin["headers"], title=f"Book {name}", is_private=True)
            file_book(client, admin["headers"], book["id"], shelf["id"])

        with rows_at_the_engine() as seen:
            collections(client, member["headers"])

        on_collections = [
            row for row in seen if " collections" in row.sql or "\nFROM collections" in row.sql
        ]
        on_books = [row for row in seen if "FROM books" in row.sql]
        assert len(on_collections) == 1, [row.sql for row in on_collections]
        assert len(on_books) == 3, [row.sql for row in on_books]
