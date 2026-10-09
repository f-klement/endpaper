"""Tests for the trash on backend/routers/books.py.

A delete is one tap away from every book, it is the only action here that
repeating does not undo, and a catalogue is somebody's hours of typing. So
deleting parks the row and `visible_to()` hides it.

Four things are worth pinning and none of them is "a deleted book disappears".

**The reach.** Soft deletion is only safe because every book query already
applies `visible_to()`. A trashed book must therefore be absent from the
listing, the search, the export, the statistics, the duplicate detector, the
series gaps and the loans list, without any of them having been edited. Those
are the tests that would catch someone adding a query that forgets.

**The restore.** Everything comes back, because none of it ever left. A restore
that loses the notes is re-adding the book, not undoing anything.

**The ISBN.** A trashed row still holds the unique ISBN, so deleting a book and
re-scanning it would report "already exists" for a book nobody can see. That is
a worse bug than the one this fixes.

**Privacy.** The trash is not a hole in it. Somebody else's private book is as
invisible in the trash as it is on the shelf, and their trashed book is not
purgeable by scanning its ISBN.
"""

import pytest

from models import Book


@pytest.fixture
def trashed(client, admin, make_book):
    """A book the admin has deleted."""
    book = make_book(admin["headers"], title="Deleted Book", author="A Writer")
    client.delete(f"/api/books/{book['id']}", headers=admin["headers"])
    return book


class TestTheRowSurvives:
    def test_delete_still_answers_204(self, client, admin, make_book):
        """The contract is unchanged, so nothing calling this has to know."""
        book = make_book(admin["headers"])
        res = client.delete(f"/api/books/{book['id']}", headers=admin["headers"])
        assert res.status_code == 204

    def test_the_row_is_kept_and_stamped(self, client, admin, trashed, db):
        book = db.get(Book, trashed["id"])
        assert book is not None
        assert book.deleted_at is not None

    def test_deleting_twice_keeps_the_original_time(self, client, admin, trashed, db):
        """The second delete is a 404: it is already off the shelf."""
        first = db.get(Book, trashed["id"]).deleted_at
        assert (
            client.delete(
                f"/api/books/{trashed['id']}", headers=admin["headers"]
            ).status_code
            == 404
        )
        db.expire_all()
        assert db.get(Book, trashed["id"]).deleted_at == first


class TestItLeavesEveryView:
    """`visible_to()` is the only thing making this true. See models.py."""

    def test_it_is_gone_from_the_listing(self, client, admin, trashed):
        assert client.get("/api/books", headers=admin["headers"]).json()["total"] == 0

    def test_it_is_gone_from_a_search(self, client, admin, trashed):
        res = client.get(
            "/api/books", params={"q": "Deleted"}, headers=admin["headers"]
        )
        assert res.json()["total"] == 0

    def test_it_is_gone_from_the_export(self, client, admin, trashed):
        body = client.get("/api/books/export", headers=admin["headers"]).text
        assert "Deleted Book" not in body

    def test_it_is_gone_from_the_statistics(self, client, admin, trashed):
        assert client.get("/api/stats", headers=admin["headers"]).json()["total"] == 0

    def test_it_is_gone_from_the_duplicate_detector(
        self, client, admin, make_book, trashed
    ):
        """Otherwise a deleted book is offered as a duplicate of its replacement."""
        make_book(admin["headers"], title="Deleted Book", author="A Writer")
        assert client.get("/api/books/duplicates", headers=admin["headers"]).json() == []

    def test_it_is_gone_from_the_series_gaps(self, client, admin, make_book):
        book = make_book(admin["headers"], series_name="Discworld", series_index=2)
        make_book(admin["headers"], series_name="Discworld", series_index=1)
        client.delete(f"/api/books/{book['id']}", headers=admin["headers"])

        [series] = client.get("/api/books/series", headers=admin["headers"]).json()
        assert series["book_count"] == 1

    def test_it_is_gone_from_the_loans_list(
        self, client, admin, member, make_book
    ):
        book = make_book(admin["headers"])
        client.post(
            "/api/loans",
            json={"book_id": book["id"], "loaned_to_user_id": member["user"]["id"]},
            headers=admin["headers"],
        )
        client.delete(f"/api/books/{book['id']}", headers=admin["headers"])

        assert client.get("/api/loans", headers=admin["headers"]).json()["total"] == 0

    def test_fetching_it_directly_is_404(self, client, admin, trashed):
        res = client.get(f"/api/books/{trashed['id']}", headers=admin["headers"])
        assert res.status_code == 404

    def test_it_cannot_be_edited_while_trashed(self, client, admin, trashed):
        res = client.patch(
            f"/api/books/{trashed['id']}",
            json={"title": "Sneaky"},
            headers=admin["headers"],
        )
        assert res.status_code == 404


class TestTheTrashListing:
    def test_it_holds_what_was_deleted(self, client, admin, trashed):
        body = client.get("/api/books/trash", headers=admin["headers"]).json()
        assert body["total"] == 1
        assert body["items"][0]["title"] == "Deleted Book"

    def test_it_is_empty_before_anything_is_deleted(self, client, admin, make_book):
        make_book(admin["headers"])
        assert client.get("/api/books/trash", headers=admin["headers"]).json()["total"] == 0

    def test_most_recently_deleted_first(self, client, admin, make_book):
        """The trash is read to find something just lost, not to browse."""
        first = make_book(admin["headers"], title="First")
        second = make_book(admin["headers"], title="Second")
        client.delete(f"/api/books/{first['id']}", headers=admin["headers"])
        client.delete(f"/api/books/{second['id']}", headers=admin["headers"])

        items = client.get("/api/books/trash", headers=admin["headers"]).json()["items"]
        assert [book["title"] for book in items] == ["Second", "First"]

    def test_requires_authentication(self, client):
        assert client.get("/api/books/trash").status_code == 401

    def test_trash_is_not_read_as_a_book_id(self, client, admin):
        """Declared before `/{book_id}`, which would otherwise claim the word."""
        assert client.get("/api/books/trash", headers=admin["headers"]).status_code == 200


class TestRestore:
    def test_it_comes_back_to_the_shelf(self, client, admin, trashed):
        res = client.post(
            f"/api/books/{trashed['id']}/restore", headers=admin["headers"]
        )

        assert res.status_code == 200
        assert client.get("/api/books", headers=admin["headers"]).json()["total"] == 1

    def test_it_leaves_the_trash(self, client, admin, trashed):
        client.post(f"/api/books/{trashed['id']}/restore", headers=admin["headers"])
        assert client.get("/api/books/trash", headers=admin["headers"]).json()["total"] == 0

    def test_the_notes_come_back_with_it(self, client, admin, make_book):
        """A restore that loses these is re-adding the book, not undoing."""
        book = make_book(admin["headers"])
        client.post(
            f"/api/books/{book['id']}/notes",
            json={"content": "Borrowed from Ana"},
            headers=admin["headers"],
        )
        client.delete(f"/api/books/{book['id']}", headers=admin["headers"])
        client.post(f"/api/books/{book['id']}/restore", headers=admin["headers"])

        notes = client.get(
            f"/api/books/{book['id']}/notes", headers=admin["headers"]
        ).json()
        assert [note["content"] for note in notes] == ["Borrowed from Ana"]

    def test_the_reading_status_comes_back_with_it(self, client, admin, make_book):
        book = make_book(admin["headers"])
        client.put(
            f"/api/books/{book['id']}/status",
            json={"status": "read"},
            headers=admin["headers"],
        )
        client.delete(f"/api/books/{book['id']}", headers=admin["headers"])
        restored = client.post(
            f"/api/books/{book['id']}/restore", headers=admin["headers"]
        ).json()

        assert restored["my_status"] == "read"

    def test_the_tags_come_back_with_it(self, client, admin, make_book, db):
        from models import Tag

        book = make_book(admin["headers"])
        tag = db.query(Tag).first()
        client.post(
            f"/api/books/{book['id']}/tags/{tag.id}", headers=admin["headers"]
        )
        client.delete(f"/api/books/{book['id']}", headers=admin["headers"])
        restored = client.post(
            f"/api/books/{book['id']}/restore", headers=admin["headers"]
        ).json()

        assert [t["id"] for t in restored["tags"]] == [tag.id]

    def test_restoring_a_live_book_is_404(self, client, admin, make_book):
        book = make_book(admin["headers"])
        res = client.post(f"/api/books/{book['id']}/restore", headers=admin["headers"])
        assert res.status_code == 404

    def test_restoring_an_unknown_id_is_404(self, client, admin):
        assert (
            client.post("/api/books/9999/restore", headers=admin["headers"]).status_code
            == 404
        )


class TestPurge:
    def test_one_book_is_destroyed(self, client, admin, trashed, db):
        res = client.delete(
            f"/api/books/{trashed['id']}/permanent", headers=admin["headers"]
        )

        assert res.status_code == 204
        assert db.get(Book, trashed["id"]) is None

    def test_purging_a_live_book_is_404(self, client, admin, make_book):
        """Permanent deletion is reachable only through the trash, on purpose."""
        book = make_book(admin["headers"])
        res = client.delete(
            f"/api/books/{book['id']}/permanent", headers=admin["headers"]
        )
        assert res.status_code == 404

    def test_emptying_reports_what_it_destroyed(self, client, admin, make_book):
        for title in ("One", "Two"):
            book = make_book(admin["headers"], title=title)
            client.delete(f"/api/books/{book['id']}", headers=admin["headers"])

        res = client.delete("/api/books/trash", headers=admin["headers"])

        assert res.status_code == 200
        assert res.json()["purged"] == 2

    def test_emptying_leaves_the_shelf_alone(self, client, admin, make_book, trashed):
        make_book(admin["headers"], title="Still here")

        client.delete("/api/books/trash", headers=admin["headers"])

        assert client.get("/api/books", headers=admin["headers"]).json()["total"] == 1

    def test_emptying_an_empty_trash_is_not_an_error(self, client, admin):
        res = client.delete("/api/books/trash", headers=admin["headers"])
        assert res.status_code == 200
        assert res.json()["purged"] == 0

    def test_the_cover_file_goes_too(self, client, admin, make_book, covers_dir):
        """Covers are named by book id, and SQLite reuses ids.

        Leaving the file behind gives the next book to take that id somebody
        else's cover.
        """
        from tests.helpers import JPEG_BYTES

        book = make_book(admin["headers"])
        client.post(
            f"/api/books/{book['id']}/cover",
            files={"file": ("c.jpg", JPEG_BYTES, "image/jpeg")},
            headers=admin["headers"],
        )
        assert (covers_dir / f"{book['id']}.jpg").exists()

        client.delete(f"/api/books/{book['id']}", headers=admin["headers"])
        client.delete(f"/api/books/{book['id']}/permanent", headers=admin["headers"])

        assert not (covers_dir / f"{book['id']}.jpg").exists()

    def test_trashing_keeps_the_cover_so_a_restore_still_has_one(
        self, client, admin, make_book, covers_dir
    ):
        from tests.helpers import JPEG_BYTES

        book = make_book(admin["headers"])
        client.post(
            f"/api/books/{book['id']}/cover",
            files={"file": ("c.jpg", JPEG_BYTES, "image/jpeg")},
            headers=admin["headers"],
        )
        client.delete(f"/api/books/{book['id']}", headers=admin["headers"])

        assert (covers_dir / f"{book['id']}.jpg").exists()


class TestTheIsbnIsFreedAgain:
    """Mis-scan, delete, re-scan is the most common delete in this app."""

    ISBN = "9780743273565"

    def test_re_adding_the_same_isbn_works(self, client, admin, make_book):
        book = make_book(admin["headers"], isbn=self.ISBN, title="Mis-scanned")
        client.delete(f"/api/books/{book['id']}", headers=admin["headers"])

        res = client.post(
            "/api/books",
            json={"isbn": self.ISBN, "title": "Correct"},
            headers=admin["headers"],
        )

        assert res.status_code == 201
        assert res.json()["title"] == "Correct"

    def test_the_trashed_row_is_destroyed_rather_than_restored(
        self, client, admin, make_book, db
    ):
        """Restoring instead would hand back the record just rejected.

        Asserted on the title and on the trash rather than on the id. SQLite
        makes `INTEGER PRIMARY KEY` an alias for the rowid, so purging the
        highest row frees its id and the replacement takes it: checking that
        the id is gone would fail against a database that did exactly the right
        thing.
        """
        book = make_book(admin["headers"], isbn=self.ISBN, title="Mis-scanned")
        client.delete(f"/api/books/{book['id']}", headers=admin["headers"])

        client.post(
            "/api/books",
            json={"isbn": self.ISBN, "title": "Correct"},
            headers=admin["headers"],
        )

        db.expire_all()
        titles = [
            row.title for row in db.query(Book).all()
        ]
        assert titles == ["Correct"]
        assert client.get("/api/books/trash", headers=admin["headers"]).json()["total"] == 0

    def test_a_live_book_still_conflicts(self, client, admin, make_book):
        make_book(admin["headers"], isbn=self.ISBN)
        res = client.post(
            "/api/books",
            json={"isbn": self.ISBN, "title": "Second copy"},
            headers=admin["headers"],
        )
        assert res.status_code == 409

    def test_the_scan_route_frees_it_too(self, client, admin, make_book):
        book = make_book(admin["headers"], isbn=self.ISBN)
        client.delete(f"/api/books/{book['id']}", headers=admin["headers"])

        res = client.post(
            "/api/books/scan",
            json={"isbn": self.ISBN, "title": "Rescanned"},
            headers=admin["headers"],
        )
        assert res.status_code == 201


class TestPrivacy:
    def test_another_members_trashed_book_is_invisible(
        self, client, admin, member, make_book
    ):
        book = make_book(admin["headers"], title="Private", is_private=True)
        client.delete(f"/api/books/{book['id']}", headers=admin["headers"])

        assert client.get("/api/books/trash", headers=member["headers"]).json()["total"] == 0

    def test_another_members_trashed_book_cannot_be_restored(
        self, client, admin, member, make_book
    ):
        book = make_book(admin["headers"], title="Private", is_private=True)
        client.delete(f"/api/books/{book['id']}", headers=admin["headers"])

        res = client.post(f"/api/books/{book['id']}/restore", headers=member["headers"])
        assert res.status_code == 404

    def test_emptying_the_trash_does_not_reach_another_members_private_book(
        self, client, admin, member, make_book, db
    ):
        book = make_book(admin["headers"], title="Private", is_private=True)
        client.delete(f"/api/books/{book['id']}", headers=admin["headers"])

        client.delete("/api/books/trash", headers=member["headers"])

        assert db.get(Book, book["id"]) is not None

    def test_scanning_an_isbn_cannot_purge_another_members_private_book(
        self, client, admin, member, make_book, db
    ):
        """The ISBN check sees every row, so this is the one path that could.

        Purging it would destroy data the member never offered up, and the
        409 would confirm the book exists either way.
        """
        book = make_book(
            admin["headers"], isbn="9780743273565", title="Private", is_private=True
        )
        client.delete(f"/api/books/{book['id']}", headers=admin["headers"])

        res = client.post(
            "/api/books",
            json={"isbn": "9780743273565", "title": "Mine"},
            headers=member["headers"],
        )

        assert res.status_code == 409
        assert db.get(Book, book["id"]) is not None

    def test_a_public_trashed_book_is_shared_like_any_other(
        self, client, admin, member, make_book
    ):
        """Public books are a shared shelf, in the trash as on it."""
        book = make_book(admin["headers"], title="Shared")
        client.delete(f"/api/books/{book['id']}", headers=member["headers"])

        assert client.get("/api/books/trash", headers=member["headers"]).json()["total"] == 1
        assert (
            client.post(
                f"/api/books/{book['id']}/restore", headers=member["headers"]
            ).status_code
            == 200
        )


class TestALentBookGoingToTheTrash:
    """The loan cannot simply be left open.

    A trashed book leaves the loans list, which is deliberate and tested
    above. The loan row used to stay open anyway, and returning it 404s on a
    book nobody can see, so the borrower still had it and there was no way left
    to record it coming back.
    """

    def test_the_open_loan_is_closed(self, client, admin, member, make_book, db):
        from models import Loan

        book = make_book(admin["headers"])
        client.post(
            "/api/loans",
            json={"book_id": book["id"], "loaned_to_user_id": member["user"]["id"]},
            headers=admin["headers"],
        )

        client.delete(f"/api/books/{book['id']}", headers=admin["headers"])

        db.expire_all()
        assert (
            db.query(Loan)
            .filter(Loan.book_id == book["id"], Loan.returned_at.is_(None))
            .count()
            == 0
        )

    def test_restoring_it_does_not_reopen_the_loan(
        self, client, admin, member, make_book
    ):
        """The book comes back to the shelf, not to the borrower."""
        book = make_book(admin["headers"])
        client.post(
            "/api/loans",
            json={"book_id": book["id"], "loaned_to_user_id": member["user"]["id"]},
            headers=admin["headers"],
        )
        client.delete(f"/api/books/{book['id']}", headers=admin["headers"])

        restored = client.post(
            f"/api/books/{book['id']}/restore", headers=admin["headers"]
        ).json()

        assert restored["active_loan"] is None

    def test_it_can_be_lent_again_once_restored(
        self, client, admin, member, make_book
    ):
        book = make_book(admin["headers"])
        client.post(
            "/api/loans",
            json={"book_id": book["id"], "loaned_to_user_id": member["user"]["id"]},
            headers=admin["headers"],
        )
        client.delete(f"/api/books/{book['id']}", headers=admin["headers"])
        client.post(f"/api/books/{book['id']}/restore", headers=admin["headers"])

        res = client.post(
            "/api/loans",
            json={"book_id": book["id"], "loaned_to_user_id": member["user"]["id"]},
            headers=admin["headers"],
        )
        assert res.status_code == 201
