"""Owning two paperbacks of one title, and saying so.

The whole feature is one distinction: a **copy** is deliberate and a
**duplicate** is an accident. Two rows sharing a `copy_group` are the first,
two rows that merely name the same book are the second, and every test here is
about keeping the app able to tell them apart.
"""

import covers
from models import Book


def add_copy(client, headers, book_id, **fields):
    return client.post(f"/api/books/{book_id}/copies", json=fields, headers=headers)


def copies(client, headers, book_id):
    return client.get(f"/api/books/{book_id}/copies", headers=headers)


class TestAddingACopy:
    def test_a_second_copy_is_a_second_book(self, client, admin, make_book):
        book = make_book(admin["headers"], title="Dune", isbn="9780441013593")

        res = add_copy(client, admin["headers"], book["id"])

        assert res.status_code == 201, res.text
        assert res.json()["id"] != book["id"]

    def test_the_copy_carries_the_same_work(self, client, admin, make_book):
        book = make_book(
            admin["headers"], title="Dune", author="Frank Herbert", isbn="9780441013593"
        )

        copy = add_copy(client, admin["headers"], book["id"]).json()

        assert copy["title"] == "Dune"
        assert copy["author"] == "Frank Herbert"
        assert copy["isbn"] == "9780441013593"

    def test_the_copy_carries_its_own_shelf(self, client, admin, make_book):
        """The point of a row per copy: one can be in the loft and one downstairs."""
        book = make_book(admin["headers"], title="Dune", location="Living room")

        copy = add_copy(client, admin["headers"], book["id"], location="Loft").json()

        assert copy["location"] == "Loft"
        assert client.get(f"/api/books/{book['id']}", headers=admin["headers"]).json()[
            "location"
        ] == "Living room"

    def test_the_copy_starts_unread(self, client, admin, make_book):
        """Reading is a fact about a person and an object, and this object is new."""
        book = make_book(admin["headers"], title="Dune")
        client.put(
            f"/api/books/{book['id']}/status", json={"status": "read"}, headers=admin["headers"]
        )

        copy = add_copy(client, admin["headers"], book["id"]).json()

        assert copy["my_status"] == "unread"

    def test_the_copy_inherits_the_tags(self, client, admin, make_book, db):
        book = make_book(admin["headers"], title="Dune")
        tag = client.post(
            "/api/books/tags", json={"name": "Signed"}, headers=admin["headers"]
        ).json()
        client.post(
            f"/api/books/{book['id']}/tags/{tag['id']}", headers=admin["headers"]
        )

        copy = add_copy(client, admin["headers"], book["id"]).json()

        assert [t["name"] for t in copy["tags"]] == ["Signed"]

    def test_both_rows_report_two_copies(self, client, admin, make_book):
        book = make_book(admin["headers"], title="Dune")
        copy = add_copy(client, admin["headers"], book["id"]).json()

        assert copy["copy_count"] == 2
        again = client.get(f"/api/books/{book['id']}", headers=admin["headers"]).json()
        assert again["copy_count"] == 2

    def test_a_book_with_one_copy_counts_one(self, client, admin, make_book):
        book = make_book(admin["headers"], title="Dune")
        assert book["copy_count"] == 1

    def test_a_third_copy_joins_the_same_group(self, client, admin, make_book, db):
        book = make_book(admin["headers"], title="Dune")
        second = add_copy(client, admin["headers"], book["id"]).json()
        third = add_copy(client, admin["headers"], second["id"]).json()

        tokens = {
            db.get(Book, row_id).copy_group
            for row_id in (book["id"], second["id"], third["id"])
        }
        assert len(tokens) == 1
        assert third["copy_count"] == 3

    def test_a_copy_of_an_invisible_book_is_404(self, client, admin, member, make_book):
        """404 rather than 403, like every other book route: a 403 confirms the id."""
        private = make_book(admin["headers"], title="Diary", is_private=True)

        res = add_copy(client, member["headers"], private["id"])

        assert res.status_code == 404


class TestPrivacy:
    def test_a_copy_of_a_private_book_is_private(self, client, admin, make_book):
        """The one field the caller does not get to choose: a public copy would
        disclose the book the original is hiding."""
        private = make_book(admin["headers"], title="Diary", is_private=True)

        copy = add_copy(client, admin["headers"], private["id"]).json()

        assert copy["is_private"] is True

    def test_another_member_never_sees_the_private_copy(
        self, client, admin, member, make_book
    ):
        private = make_book(admin["headers"], title="Diary", is_private=True)
        add_copy(client, admin["headers"], private["id"])

        listed = client.get("/api/books", headers=member["headers"]).json()

        assert listed["items"] == []

    def test_the_count_shows_only_what_the_caller_may_see(
        self, client, admin, member, make_book
    ):
        """A member who makes their own copy private does not thereby announce
        it on everybody else's card."""
        book = make_book(admin["headers"], title="Dune")
        copy = add_copy(client, admin["headers"], book["id"]).json()
        client.patch(
            f"/api/books/{copy['id']}/privacy",
            json={"is_private": True},
            headers=admin["headers"],
        )

        seen = client.get(f"/api/books/{book['id']}", headers=member["headers"]).json()

        assert seen["copy_count"] == 1


class TestListingCopies:
    def test_a_book_with_no_copies_lists_itself(self, client, admin, make_book):
        book = make_book(admin["headers"], title="Dune")

        listed = copies(client, admin["headers"], book["id"]).json()

        assert [row["id"] for row in listed] == [book["id"]]

    def test_every_copy_is_listed_in_the_order_added(self, client, admin, make_book):
        book = make_book(admin["headers"], title="Dune")
        second = add_copy(client, admin["headers"], book["id"]).json()

        listed = copies(client, admin["headers"], book["id"]).json()

        assert [row["id"] for row in listed] == [book["id"], second["id"]]

    def test_a_trashed_copy_is_not_listed(self, client, admin, make_book):
        book = make_book(admin["headers"], title="Dune")
        second = add_copy(client, admin["headers"], book["id"]).json()
        client.delete(f"/api/books/{second['id']}", headers=admin["headers"])

        listed = copies(client, admin["headers"], book["id"]).json()

        assert [row["id"] for row in listed] == [book["id"]]


class TestTheIsbnRule:
    def test_rescanning_a_book_still_conflicts(self, client, admin, make_book):
        """The mis-scan is the common case and stays exactly as hard as it was."""
        make_book(admin["headers"], title="Dune", isbn="9780441013593")

        res = client.post(
            "/api/books/scan",
            json={"title": "Dune", "isbn": "9780441013593"},
            headers=admin["headers"],
        )

        assert res.status_code == 409

    def test_the_conflict_names_the_book_to_copy(self, client, admin, make_book):
        book = make_book(admin["headers"], title="Dune", isbn="9780441013593")

        res = client.post(
            "/api/books/scan",
            json={"title": "Dune", "isbn": "9780441013593"},
            headers=admin["headers"],
        )

        assert res.json()["detail"]["book_id"] == book["id"]

    def test_rescanning_still_conflicts_once_copies_exist(
        self, client, admin, make_book
    ):
        """A group suspends the index, not the check. Two copies must not become
        three because somebody walked past the shelf again."""
        book = make_book(admin["headers"], title="Dune", isbn="9780441013593")
        add_copy(client, admin["headers"], book["id"])

        res = client.post(
            "/api/books/scan",
            json={"title": "Dune", "isbn": "9780441013593"},
            headers=admin["headers"],
        )

        assert res.status_code == 409

    def test_a_copy_of_a_book_with_no_isbn_is_allowed(self, client, admin, make_book):
        """Nothing about this hangs off the ISBN. A hand-typed book has copies too."""
        book = make_book(admin["headers"], title="Grandma's recipes", isbn=None)

        res = add_copy(client, admin["headers"], book["id"])

        assert res.status_code == 201

    def test_a_trashed_copy_does_not_block_re_adding(self, client, admin, make_book, db):
        """The holder lookup prefers a live row, so a trashed copy is only purged
        out of the way when every copy is trashed. Without the ordering this
        added a stray third row beside the group."""
        book = make_book(admin["headers"], title="Dune", isbn="9780441013593")
        second = add_copy(client, admin["headers"], book["id"]).json()
        client.delete(f"/api/books/{second['id']}", headers=admin["headers"])

        res = client.post(
            "/api/books/scan",
            json={"title": "Dune", "isbn": "9780441013593"},
            headers=admin["headers"],
        )

        assert res.status_code == 409
        assert db.get(Book, second["id"]) is not None


    def test_re_adding_when_every_copy_is_trashed(self, client, admin, make_book, db):
        """Two trashed copies used to answer **500**: one row was purged, the
        group shrank to one, the survivor's token was cleared, and that trashed
        survivor re-entered the partial index as the insert reclaimed the
        ISBN."""
        book = make_book(admin["headers"], title="Dune", isbn="9780441013593")
        second = add_copy(client, admin["headers"], book["id"]).json()
        for row in (book, second):
            client.delete(f"/api/books/{row['id']}", headers=admin["headers"])

        res = client.post(
            "/api/books/scan",
            json={"title": "Dune", "isbn": "9780441013593"},
            headers=admin["headers"],
        )

        assert res.status_code == 201, res.text
        live = db.query(Book).filter(Book.isbn == "9780441013593").all()
        assert [(row.id, row.copy_group) for row in live] == [(res.json()["id"], None)]

    def test_re_adding_when_three_copies_are_trashed(self, client, admin, make_book, db):
        """The case a guard on `_normalise_copy_group` does not reach. With two
        members left the group never shrinks to one, so nothing was normalised
        and the insert simply succeeded beside rows that still held the ISBN:
        **201**, and a stray fourth row."""
        book = make_book(admin["headers"], title="Dune", isbn="9780441013593")
        rows = [book]
        for _ in range(2):
            rows.append(add_copy(client, admin["headers"], book["id"]).json())
        for row in rows:
            client.delete(f"/api/books/{row['id']}", headers=admin["headers"])

        res = client.post(
            "/api/books/scan",
            json={"title": "Dune", "isbn": "9780441013593"},
            headers=admin["headers"],
        )

        assert res.status_code == 201, res.text
        remaining = db.query(Book).filter(Book.isbn == "9780441013593").all()
        assert [(row.id, row.copy_group) for row in remaining] == [
            (res.json()["id"], None)
        ]

    def test_a_copy_nobody_may_purge_keeps_the_409(
        self, client, admin, member, make_book, db
    ):
        """One member's trashed copy of a shared book is theirs. The whole
        group stays where it is rather than being partly destroyed."""
        book = make_book(admin["headers"], title="Dune", isbn="9780441013593")
        theirs = add_copy(client, member["headers"], book["id"]).json()
        client.patch(
            f"/api/books/{theirs['id']}/privacy",
            json={"is_private": True},
            headers=member["headers"],
        )
        client.delete(f"/api/books/{book['id']}", headers=admin["headers"])
        client.delete(f"/api/books/{theirs['id']}", headers=member["headers"])

        res = client.post(
            "/api/books/scan",
            json={"title": "Dune", "isbn": "9780441013593"},
            headers=admin["headers"],
        )

        assert res.status_code == 409
        # Nothing destroyed, and the id withheld: naming it would confirm that
        # a particular member owns a particular book.
        assert res.json()["detail"] == "Book with this ISBN already in catalog"
        assert db.get(Book, book["id"]) is not None
        assert db.get(Book, theirs["id"]) is not None

    def test_a_refused_add_keeps_the_cover_file(
        self, client, admin, member, make_book, db, covers_dir
    ):
        """The second half of the same bug: `_purge` unlinked the cover before
        the DELETE, so a 409 part way through a group left a book on the shelf
        whose `cover_url` named a file that no longer existed."""
        book = make_book(admin["headers"], title="Dune", isbn="9780441013593")
        theirs = add_copy(client, member["headers"], book["id"]).json()
        client.patch(
            f"/api/books/{theirs['id']}/privacy",
            json={"is_private": True},
            headers=member["headers"],
        )
        client.delete(f"/api/books/{book['id']}", headers=admin["headers"])
        client.delete(f"/api/books/{theirs['id']}", headers=member["headers"])
        cover = covers_dir / f"{book['id']}.jpg"
        cover.write_bytes(b"not really a jpeg")

        client.post(
            "/api/books/scan",
            json={"title": "Dune", "isbn": "9780441013593"},
            headers=admin["headers"],
        )

        assert cover.exists()

    def test_a_reused_id_keeps_the_new_book_s_own_cover(
        self, client, admin, make_book, db, covers_dir, monkeypatch
    ):
        """The success path, which the refusal test above cannot reach.

        SQLite reuses the id of the highest deleted row, so re-scanning a book
        that was just purged out of the way hands the new row the old row's id.
        The unlink has to happen after the commit and **before** the new book
        stores its own cover: later, and it deletes the cover it just fetched.

        Pinned rather than commented, because this is the second round in which
        the ordering of a cover unlink produced an unrecoverable file loss. A
        comment did not stop the first one.
        """
        book = make_book(admin["headers"], title="Dune", isbn="9780441013593")
        stale = covers_dir / f"{book['id']}.jpg"
        stale.write_bytes(b"the purged book's cover")
        client.delete(f"/api/books/{book['id']}", headers=admin["headers"])

        def store_a_cover(book_id, isbn, supplied, budget=None):
            (covers_dir / f"{book_id}.png").write_bytes(b"the new book's own cover")
            return f"/covers/{book_id}.png"

        # Over the top of the suite-wide "no cover to be had" stub, which would
        # leave nothing for a mis-ordered unlink to destroy.
        monkeypatch.setattr(covers, "resolve_and_store", store_a_cover)

        res = client.post(
            "/api/books/scan",
            json={"title": "Dune", "isbn": "9780441013593"},
            headers=admin["headers"],
        )

        new_id = res.json()["id"]
        assert new_id == book["id"], "this test is about a reused id"
        assert not stale.exists()
        assert (covers_dir / f"{new_id}.png").exists()


class TestLoans:
    def test_each_copy_lends_separately(self, client, admin, member, make_book):
        """One open loan per book row, and a copy is a book row. This is the
        sentence the whole rows-versus-a-count decision was made for."""
        book = make_book(admin["headers"], title="Dune")
        copy = add_copy(client, admin["headers"], book["id"]).json()

        first = client.post(
            "/api/loans",
            json={"book_id": book["id"], "loaned_to_user_id": member["user"]["id"]},
            headers=admin["headers"],
        )
        second = client.post(
            "/api/loans",
            json={"book_id": copy["id"], "loaned_to_user_id": member["user"]["id"]},
            headers=admin["headers"],
        )

        assert first.status_code == 201, first.text
        assert second.status_code == 201, second.text

    def test_one_copy_out_leaves_the_other_on_the_shelf(
        self, client, admin, member, make_book
    ):
        book = make_book(admin["headers"], title="Dune")
        copy = add_copy(client, admin["headers"], book["id"]).json()
        client.post(
            "/api/loans",
            json={"book_id": book["id"], "loaned_to_user_id": member["user"]["id"]},
            headers=admin["headers"],
        )

        listed = copies(client, admin["headers"], book["id"]).json()

        out = {row["id"]: row["active_loan"] is not None for row in listed}
        assert out == {book["id"]: True, copy["id"]: False}

    def test_the_same_copy_cannot_go_to_two_people(
        self, client, admin, member, make_book
    ):
        book = make_book(admin["headers"], title="Dune")
        client.post(
            "/api/loans",
            json={"book_id": book["id"], "loaned_to_user_id": member["user"]["id"]},
            headers=admin["headers"],
        )

        again = client.post(
            "/api/loans",
            json={"book_id": book["id"], "loaned_to_name": "Anna"},
            headers=admin["headers"],
        )

        assert again.status_code == 409


class TestDuplicatesLeaveCopiesAlone:
    def test_two_copies_are_not_offered_as_duplicates(self, client, admin, make_book):
        """They are the strongest possible title-and-author match, and merging
        them would destroy a book the library holds."""
        book = make_book(admin["headers"], title="Dune", author="Frank Herbert")
        add_copy(client, admin["headers"], book["id"])

        assert client.get("/api/books/duplicates", headers=admin["headers"]).json() == []

    def test_a_real_duplicate_beside_a_copy_is_still_found(
        self, client, admin, make_book
    ):
        book = make_book(admin["headers"], title="Dune", author="Frank Herbert")
        add_copy(client, admin["headers"], book["id"])
        stray = make_book(admin["headers"], title="dune", author="frank herbert")

        [group] = client.get("/api/books/duplicates", headers=admin["headers"]).json()

        ids = {row["id"] for row in group["books"]}
        assert stray["id"] in ids
        assert len(ids) == 2


class TestMerging:
    def test_merging_two_copies_leaves_one_ordinary_book(
        self, client, admin, make_book, db
    ):
        """A member saying they were never two objects. The survivor must not
        keep a group token, or its ISBN stays out of the unique index."""
        book = make_book(admin["headers"], title="Dune", isbn="9780441013593")
        copy = add_copy(client, admin["headers"], book["id"]).json()

        res = client.post(
            "/api/books/merge",
            json={"book_ids": [book["id"], copy["id"]], "keep_id": book["id"]},
            headers=admin["headers"],
        )

        assert res.status_code == 200, res.text
        assert db.get(Book, book["id"]).copy_group is None
        assert res.json()["copy_count"] == 1

    def test_merging_a_stray_into_a_copy_leaves_the_group_alone(
        self, client, admin, make_book, db
    ):
        book = make_book(admin["headers"], title="Dune", author="Frank Herbert")
        copy = add_copy(client, admin["headers"], book["id"]).json()
        stray = make_book(admin["headers"], title="dune", author="frank herbert")

        client.post(
            "/api/books/merge",
            json={"book_ids": [copy["id"], stray["id"]], "keep_id": copy["id"]},
            headers=admin["headers"],
        )

        assert db.get(Book, copy["id"]).copy_group is not None
        assert db.get(Book, book["id"]).copy_group is not None

    def test_the_survivor_does_not_absorb_a_group(self, client, admin, make_book, db):
        """Absorbing `copy_group` would make the keeper a copy of the loser's
        siblings, which its own owner never agreed to."""
        book = make_book(admin["headers"], title="Dune", author="Frank Herbert")
        copy = add_copy(client, admin["headers"], book["id"]).json()
        stray = make_book(admin["headers"], title="dune", author="frank herbert")

        client.post(
            "/api/books/merge",
            json={"book_ids": [stray["id"], copy["id"]], "keep_id": stray["id"]},
            headers=admin["headers"],
        )

        assert db.get(Book, stray["id"]).copy_group is None


    def test_a_survivor_that_would_clash_keeps_its_group(
        self, client, admin, make_book, db
    ):
        """The guard in `_normalise_copy_group`, which nothing in the app can
        reach on its own and a hand-edited database can. Merging a copy into a
        stray hands the stray the group's ISBN, so clearing the last member's
        token would leave two ungrouped rows holding it and the delete would
        raise from inside somebody's merge."""
        book = make_book(
            admin["headers"], title="Dune", author="Frank Herbert", isbn="9780441013593"
        )
        copy = add_copy(client, admin["headers"], book["id"]).json()
        stray = make_book(admin["headers"], title="dune", author="frank herbert")

        res = client.post(
            "/api/books/merge",
            json={"book_ids": [stray["id"], copy["id"]], "keep_id": stray["id"]},
            headers=admin["headers"],
        )

        assert res.status_code == 200, res.text
        assert db.get(Book, stray["id"]).isbn == "9780441013593"
        assert db.get(Book, book["id"]).copy_group is not None


class TestPurging:
    def test_purging_a_copy_frees_the_survivor(self, client, admin, make_book, db):
        book = make_book(admin["headers"], title="Dune", isbn="9780441013593")
        copy = add_copy(client, admin["headers"], book["id"]).json()
        client.delete(f"/api/books/{copy['id']}", headers=admin["headers"])
        client.delete(f"/api/books/{copy['id']}/permanent", headers=admin["headers"])

        assert db.get(Book, book["id"]).copy_group is None

    def test_trashing_a_copy_keeps_the_group(self, client, admin, make_book, db):
        """A trashed copy can be restored, and clearing the token underneath it
        would leave two ungrouped rows with one ISBN: the restore would fail on
        a button that has nothing to do with copies."""
        book = make_book(admin["headers"], title="Dune", isbn="9780441013593")
        copy = add_copy(client, admin["headers"], book["id"]).json()

        client.delete(f"/api/books/{copy['id']}", headers=admin["headers"])

        assert db.get(Book, book["id"]).copy_group is not None
        restored = client.post(
            f"/api/books/{copy['id']}/restore", headers=admin["headers"]
        )
        assert restored.status_code == 200, restored.text

    def test_purging_one_of_three_keeps_the_group(self, client, admin, make_book, db):
        book = make_book(admin["headers"], title="Dune")
        second = add_copy(client, admin["headers"], book["id"]).json()
        third = add_copy(client, admin["headers"], book["id"]).json()
        client.delete(f"/api/books/{third['id']}", headers=admin["headers"])
        client.delete(f"/api/books/{third['id']}/permanent", headers=admin["headers"])

        assert db.get(Book, book["id"]).copy_group is not None
        assert db.get(Book, second["id"]).copy_group is not None
