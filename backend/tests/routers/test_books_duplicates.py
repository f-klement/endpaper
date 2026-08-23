"""Finding duplicate entries and folding them together.

An accidental exact repeat is already refused by `uq_books_isbn_single_copy`,
so the case worth catching is the one it cannot see: a hardback and a paperback
are the same book and two legitimately different ISBNs. Deliberate copies of one
title are neither, and `tests/routers/test_books_copies.py` holds that line.
Detection is therefore deliberately lossy, and merge is a thing a person
confirms rather than something automatic.
"""


def merge(client, headers, book_ids, keep_id):
    return client.post(
        "/api/books/merge", json={"book_ids": book_ids, "keep_id": keep_id}, headers=headers
    )


def groups(client, headers):
    return client.get("/api/books/duplicates", headers=headers).json()


class TestDetection:
    def test_finds_the_same_title_and_author_twice(self, client, admin, make_book):
        make_book(admin["headers"], title="Dune", author="Frank Herbert")
        make_book(admin["headers"], title="Dune", author="Frank Herbert")

        [group] = groups(client, admin["headers"])

        assert len(group["books"]) == 2

    def test_ignores_case_and_punctuation(self, client, admin, make_book):
        make_book(admin["headers"], title="Dune!", author="Frank Herbert")
        make_book(admin["headers"], title="dune", author="frank herbert")

        assert len(groups(client, admin["headers"])) == 1

    def test_ignores_a_leading_article(self, client, admin, make_book):
        make_book(admin["headers"], title="The Hobbit", author="Tolkien")
        make_book(admin["headers"], title="Hobbit", author="Tolkien")

        assert len(groups(client, admin["headers"])) == 1

    def test_ignores_a_german_leading_article(self, client, admin, make_book):
        make_book(admin["headers"], title="Der Steppenwolf", author="Hesse")
        make_book(admin["headers"], title="Steppenwolf", author="Hesse")

        assert len(groups(client, admin["headers"])) == 1

    def test_matches_on_the_first_author_only(self, client, admin, make_book):
        """Two editions credit a collaboration differently all the time."""
        make_book(admin["headers"], title="Good Omens", author="Terry Pratchett")
        make_book(admin["headers"], title="Good Omens", author="Terry Pratchett, Neil Gaiman")

        assert len(groups(client, admin["headers"])) == 1

    def test_different_books_are_not_grouped(self, client, admin, make_book):
        make_book(admin["headers"], title="Dune", author="Frank Herbert")
        make_book(admin["headers"], title="Neuromancer", author="William Gibson")

        assert groups(client, admin["headers"]) == []

    def test_the_same_title_by_different_authors_is_not_a_duplicate(
        self, client, admin, make_book
    ):
        make_book(admin["headers"], title="Ulysses", author="James Joyce")
        make_book(admin["headers"], title="Ulysses", author="Alfred Tennyson")

        assert groups(client, admin["headers"]) == []

    def test_a_single_book_is_not_a_group(self, client, admin, make_book):
        make_book(admin["headers"], title="Dune", author="Frank Herbert")
        assert groups(client, admin["headers"]) == []

    def test_another_members_private_book_is_never_grouped(
        self, client, admin, member, make_book
    ):
        # Otherwise the duplicates view discloses a private book's title.
        make_book(admin["headers"], title="Dune", author="Frank Herbert", is_private=True)
        make_book(member["headers"], title="Dune", author="Frank Herbert")

        assert groups(client, member["headers"]) == []

    def test_requires_authentication(self, client):
        assert client.get("/api/books/duplicates").status_code == 401


class TestMerge:
    def test_keeps_the_chosen_book(self, client, admin, make_book):
        keeper = make_book(admin["headers"], title="Dune")
        loser = make_book(admin["headers"], title="Dune")

        res = merge(client, admin["headers"], [keeper["id"], loser["id"]], keeper["id"])

        assert res.status_code == 200
        assert res.json()["id"] == keeper["id"]

    def test_removes_the_others(self, client, admin, make_book):
        keeper = make_book(admin["headers"], title="Dune")
        loser = make_book(admin["headers"], title="Dune")

        merge(client, admin["headers"], [keeper["id"], loser["id"]], keeper["id"])

        assert client.get(f"/api/books/{loser['id']}", headers=admin["headers"]).status_code == 404

    def test_absorbs_a_field_the_keeper_lacks(self, client, admin, make_book):
        keeper = make_book(admin["headers"], title="Dune", publisher=None)
        loser = make_book(admin["headers"], title="Dune", publisher="Chilton")

        res = merge(client, admin["headers"], [keeper["id"], loser["id"]], keeper["id"])

        assert res.json()["publisher"] == "Chilton"

    def test_never_overwrites_what_the_keeper_has(self, client, admin, make_book):
        """The kept row is the one a person chose."""
        keeper = make_book(admin["headers"], title="Dune", publisher="Ace")
        loser = make_book(admin["headers"], title="Dune", publisher="Chilton")

        res = merge(client, admin["headers"], [keeper["id"], loser["id"]], keeper["id"])

        assert res.json()["publisher"] == "Ace"

    def test_absorbs_an_isbn(self, client, admin, make_book):
        keeper = make_book(admin["headers"], title="Dune")
        loser = make_book(admin["headers"], title="Dune", isbn="9780441013593")

        res = merge(client, admin["headers"], [keeper["id"], loser["id"]], keeper["id"])

        assert res.json()["isbn"] == "9780441013593"

    def test_merges_three_at_once(self, client, admin, make_book):
        keeper = make_book(admin["headers"], title="Dune")
        second = make_book(admin["headers"], title="Dune", publisher="Chilton")
        third = make_book(admin["headers"], title="Dune", year=1965)

        res = merge(
            client, admin["headers"], [keeper["id"], second["id"], third["id"]], keeper["id"]
        )

        assert res.json()["publisher"] == "Chilton"
        assert res.json()["year"] == 1965

    def test_moves_the_tags_across(self, client, admin, make_book):
        tags = client.get("/api/books/tags", headers=admin["headers"]).json()
        fiction = next(t for t in tags if t["name"] == "Fiction")
        keeper = make_book(admin["headers"], title="Dune")
        loser = make_book(admin["headers"], title="Dune")
        client.post(
            f"/api/books/{loser['id']}/tags/{fiction['id']}", headers=admin["headers"]
        )

        res = merge(client, admin["headers"], [keeper["id"], loser["id"]], keeper["id"])

        assert [t["name"] for t in res.json()["tags"]] == ["Fiction"]

    def test_a_tag_on_both_is_not_duplicated(self, client, admin, make_book):
        tags = client.get("/api/books/tags", headers=admin["headers"]).json()
        fiction = next(t for t in tags if t["name"] == "Fiction")
        keeper = make_book(admin["headers"], title="Dune")
        loser = make_book(admin["headers"], title="Dune")
        for book in (keeper, loser):
            client.post(f"/api/books/{book['id']}/tags/{fiction['id']}", headers=admin["headers"])

        res = merge(client, admin["headers"], [keeper["id"], loser["id"]], keeper["id"])

        assert len(res.json()["tags"]) == 1

    def test_moves_the_notes_across(self, client, admin, make_book):
        keeper = make_book(admin["headers"], title="Dune")
        loser = make_book(admin["headers"], title="Dune")
        client.post(
            f"/api/books/{loser['id']}/notes",
            json={"content": "worth keeping"},
            headers=admin["headers"],
        )

        merge(client, admin["headers"], [keeper["id"], loser["id"]], keeper["id"])

        notes = client.get(f"/api/books/{keeper['id']}/notes", headers=admin["headers"]).json()
        assert [n["content"] for n in notes] == ["worth keeping"]

    def test_moves_a_reading_status_across(self, client, admin, make_book):
        keeper = make_book(admin["headers"], title="Dune")
        loser = make_book(admin["headers"], title="Dune")
        client.put(
            f"/api/books/{loser['id']}/status", json={"status": "read"}, headers=admin["headers"]
        )

        res = merge(client, admin["headers"], [keeper["id"], loser["id"]], keeper["id"])

        assert res.json()["my_status"] == "read"

    def test_a_status_on_both_keeps_the_survivors(self, client, admin, make_book):
        """(user_id, book_id) is unique, so both rows cannot survive. Deleting
        somebody's reading history to satisfy an index is not acceptable, so the
        row already on the keeper wins."""
        keeper = make_book(admin["headers"], title="Dune")
        loser = make_book(admin["headers"], title="Dune")
        client.put(
            f"/api/books/{keeper['id']}/status", json={"status": "reading"}, headers=admin["headers"]
        )
        client.put(
            f"/api/books/{loser['id']}/status", json={"status": "read"}, headers=admin["headers"]
        )

        res = merge(client, admin["headers"], [keeper["id"], loser["id"]], keeper["id"])

        assert res.json()["my_status"] == "reading"

    def test_two_members_statuses_both_survive(self, client, admin, member, make_book):
        keeper = make_book(admin["headers"], title="Dune")
        loser = make_book(admin["headers"], title="Dune")
        client.put(
            f"/api/books/{loser['id']}/status", json={"status": "read"}, headers=admin["headers"]
        )
        client.put(
            f"/api/books/{loser['id']}/status", json={"status": "reading"}, headers=member["headers"]
        )

        merge(client, admin["headers"], [keeper["id"], loser["id"]], keeper["id"])

        as_admin = client.get(f"/api/books/{keeper['id']}", headers=admin["headers"]).json()
        as_member = client.get(f"/api/books/{keeper['id']}", headers=member["headers"]).json()
        assert (as_admin["my_status"], as_member["my_status"]) == ("read", "reading")

    def test_moves_an_active_loan_across(self, client, admin, member, make_book):
        keeper = make_book(admin["headers"], title="Dune")
        loser = make_book(admin["headers"], title="Dune")
        client.post(
            "/api/loans",
            json={"book_id": loser["id"], "loaned_to_user_id": member["user"]["id"]},
            headers=admin["headers"],
        )

        res = merge(client, admin["headers"], [keeper["id"], loser["id"]], keeper["id"])

        assert res.json()["active_loan"] is not None


class TestMergeRefusals:
    def test_the_keeper_must_be_in_the_list(self, client, admin, make_book):
        # Spelled out rather than inferred, so a mistyped request fails instead
        # of silently keeping whichever row sorted first.
        first = make_book(admin["headers"], title="Dune")
        second = make_book(admin["headers"], title="Dune")
        other = make_book(admin["headers"], title="Elsewhere")

        res = merge(client, admin["headers"], [first["id"], second["id"]], other["id"])

        assert res.status_code == 422

    def test_needs_at_least_two_books(self, client, admin, make_book):
        book = make_book(admin["headers"], title="Dune")
        assert merge(client, admin["headers"], [book["id"], book["id"]], book["id"]).status_code == 422

    def test_an_unknown_id_is_not_silently_dropped(self, client, admin, make_book):
        book = make_book(admin["headers"], title="Dune")
        res = merge(client, admin["headers"], [book["id"], 9999], book["id"])
        assert res.status_code == 422

    def test_another_members_private_book_cannot_be_merged_in(
        self, client, admin, member, make_book
    ):
        private = make_book(admin["headers"], title="Dune", is_private=True)
        mine = make_book(member["headers"], title="Dune")

        res = merge(client, member["headers"], [mine["id"], private["id"]], mine["id"])

        assert res.status_code == 422

    def test_requires_authentication(self, client):
        assert client.post("/api/books/merge", json={"book_ids": [1, 2], "keep_id": 1}).status_code == 401


class TestTheLoanInvariant:
    """`returned_at IS NULL` is the single active loan, per docs/data-model.md.

    Merging two books that were both lent out broke it: every loan moved to
    the survivor unconditionally, so it ended up with two open. Every later
    lend on that book then 409s forever, and the UI renders one `active_loan`,
    so there is no way to see the other or close it.
    """

    def _lent_book(self, client, admin, member, make_book, title: str):
        book = make_book(admin["headers"], title=title, author="One Author")
        client.post(
            "/api/loans",
            json={"book_id": book["id"], "loaned_to_user_id": member["user"]["id"]},
            headers=admin["headers"],
        )
        return book

    def test_merging_two_lent_books_leaves_one_open_loan(
        self, client, admin, member, make_book, db
    ):
        from models import Loan

        first = self._lent_book(client, admin, member, make_book, "Dune")
        second = self._lent_book(client, admin, member, make_book, "Dune")

        res = client.post(
            "/api/books/merge",
            json={"book_ids": [first["id"], second["id"]], "keep_id": first["id"]},
            headers=admin["headers"],
        )

        assert res.status_code == 200
        db.expire_all()
        open_loans = (
            db.query(Loan)
            .filter(Loan.book_id == first["id"], Loan.returned_at.is_(None))
            .count()
        )
        assert open_loans == 1

    def test_the_survivor_can_still_be_lent_after_it_comes_back(
        self, client, admin, member, make_book
    ):
        first = self._lent_book(client, admin, member, make_book, "Dune")
        second = self._lent_book(client, admin, member, make_book, "Dune")
        client.post(
            "/api/books/merge",
            json={"book_ids": [first["id"], second["id"]], "keep_id": first["id"]},
            headers=admin["headers"],
        )

        [loan] = [
            row
            for row in client.get("/api/loans", headers=admin["headers"]).json()["items"]
            if row["book_id"] == first["id"]
        ]
        client.put(f"/api/loans/{loan['id']}/return", headers=admin["headers"])

        res = client.post(
            "/api/loans",
            json={"book_id": first["id"], "loaned_to_user_id": member["user"]["id"]},
            headers=admin["headers"],
        )
        assert res.status_code == 201

    def test_no_loan_history_is_destroyed(self, client, admin, member, make_book, db):
        """The extra loans are closed, not deleted: they happened."""
        from models import Loan

        first = self._lent_book(client, admin, member, make_book, "Dune")
        second = self._lent_book(client, admin, member, make_book, "Dune")

        client.post(
            "/api/books/merge",
            json={"book_ids": [first["id"], second["id"]], "keep_id": first["id"]},
            headers=admin["headers"],
        )

        db.expire_all()
        assert db.query(Loan).filter(Loan.book_id == first["id"]).count() == 2
