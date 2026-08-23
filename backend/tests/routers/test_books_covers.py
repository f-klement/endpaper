"""Covers on the way in, and the backfill that repairs the ones already here.

A hotlinked cover depends on the image service being up, the URL not rotting,
the pod's egress, every reader's browser and the CSP. Four of those five are
outside this app, so a cover is fetched once and served from here.

The CSV import is why the backfill exists: it never resolved a cover at all, so
a library that arrived that way rendered the placeholder on every book, and
storing covers on the way in would only ever have helped books added later.

The default in this suite is `conftest.offline_covers`, which answers "no cover
to be had", so a book created without one has none. That is the state the
backfill is for, and the tests below patch a working fetch over the top only
where they need one. The fetch itself is exercised for real, against a mocked
transport, in tests/test_covers.py.
"""

import httpx
import pytest
import respx

import covers
from config import COVERS_DIR
from tests.helpers import JPEG_BYTES


def store_locally(monkeypatch) -> list[int]:
    """Pretend every fetch works, writing the file the real one would.

    The file matters: everything downstream asks the directory rather than the
    column, so a stub that only returned a URL would leave the backfill
    correctly deciding the book still needs one.
    """
    asked: list[int] = []

    def fake(book_id, isbn, supplied, budget=None):
        asked.append(book_id)
        (COVERS_DIR / f"{book_id}.jpg").write_bytes(JPEG_BYTES)
        return f"/covers/{book_id}.jpg"

    monkeypatch.setattr(covers, "resolve_and_store", fake)
    return asked


@pytest.fixture
def covers_that_store(monkeypatch):
    return store_locally(monkeypatch)


class TestAddingABook:
    def test_the_cover_is_stored_rather_than_hotlinked(
        self, client, admin, make_book, covers_dir, covers_that_store
    ):
        book = make_book(
            admin["headers"], cover_url="https://covers.openlibrary.org/b/isbn/x-L.jpg"
        )
        assert book["cover_url"] == f"/covers/{book['id']}.jpg"

    def test_it_runs_after_the_row_exists(
        self, client, admin, make_book, covers_dir, covers_that_store
    ):
        """The file is named by the book's id, so there is nothing to name until
        the insert has happened."""
        book = make_book(admin["headers"], isbn="9780441013593")
        assert covers_that_store == [book["id"]]

    def test_a_book_no_image_service_has_keeps_no_cover(
        self, client, admin, make_book, covers_dir
    ):
        book = make_book(admin["headers"], isbn="9780441013593")
        assert book["cover_url"] is None

    def test_the_bytes_are_served_from_here(
        self, client, admin, make_book, covers_dir, covers_that_store
    ):
        book = make_book(admin["headers"], isbn="9780441013593")

        res = client.get(f"/covers/{book['id']}.jpg", headers=admin["headers"])

        assert res.status_code == 200
        assert res.headers["content-type"] == "image/jpeg"
        assert res.content == JPEG_BYTES



class TestBackfill:
    def test_it_reports_the_books_it_could_not_fix(self, client, admin, make_book, covers_dir):
        make_book(admin["headers"], title="A")
        make_book(admin["headers"], title="B")

        body = client.post("/api/books/covers/backfill", headers=admin["headers"]).json()

        assert body == {
            "examined": 2,
            "stored": 0,
            "unreachable": 0,
            "still_missing": 2,
            "remaining": 0,
            "next_after_id": 0,
        }

    def test_a_cover_it_resolved_but_could_not_download_is_its_own_count(
        self, client, admin, make_book, covers_dir, monkeypatch
    ):
        """With no egress every book lands here. Folding it into either of the
        other two counts reports a clean no-op in exactly the situation this
        feature exists for."""
        remote = "https://covers.openlibrary.org/b/isbn/x-L.jpg"
        monkeypatch.setattr(
            covers,
            "resolve_and_store",
            lambda book_id, isbn, supplied, budget=None: remote,
        )
        make_book(admin["headers"], title="A")

        body = client.post("/api/books/covers/backfill", headers=admin["headers"]).json()

        assert body["unreachable"] == 1
        assert body["stored"] == 0
        assert body["still_missing"] == 0

    def test_it_stores_a_cover_for_a_book_that_had_none(
        self, client, admin, make_book, covers_dir, monkeypatch
    ):
        book = make_book(admin["headers"], title="A")
        store_locally(monkeypatch)

        body = client.post("/api/books/covers/backfill", headers=admin["headers"]).json()

        assert body["stored"] == 1
        assert body["still_missing"] == 0
        listed = client.get(f"/api/books/{book['id']}", headers=admin["headers"]).json()
        assert listed["cover_url"] == f"/covers/{book['id']}.jpg"
        assert (
            client.get(f"/covers/{book['id']}.jpg", headers=admin["headers"]).content
            == JPEG_BYTES
        )

    def test_a_cover_this_app_already_holds_is_left_out(
        self, client, admin, make_book, covers_dir, monkeypatch
    ):
        """A stored cover is a file on this volume. It is not what rots, and
        re-fetching every run would be the backfill's whole cost for nothing.
        This is also what makes the backfill safe to press twice."""
        make_book(admin["headers"], title="A")
        store_locally(monkeypatch)
        client.post("/api/books/covers/backfill", headers=admin["headers"])

        second = client.post("/api/books/covers/backfill", headers=admin["headers"]).json()

        assert second["examined"] == 0

    def test_it_never_touches_another_members_private_book(
        self, client, admin, member, make_book, covers_dir
    ):
        """`visible_to` has no admin bypass, so an admin-only backfill could
        never repair these. Each member repairs their own shelf instead."""
        make_book(member["headers"], title="Theirs", is_private=True)

        body = client.post("/api/books/covers/backfill", headers=admin["headers"]).json()

        assert body["examined"] == 0

    def test_it_needs_a_signed_in_member(self, client):
        assert client.post("/api/books/covers/backfill").status_code == 401

    def test_the_batch_is_bounded_and_the_rest_reported(
        self, client, admin, make_book, covers_dir, monkeypatch
    ):
        """The run holds an HTTP request open while it fetches, so it stops at
        a batch and says how many are left rather than timing out."""
        import routers.books as books_router

        first = make_book(admin["headers"], title="A")
        make_book(admin["headers"], title="B")
        monkeypatch.setattr(books_router, "MAX_BACKFILL_BOOKS", 1)

        body = client.post("/api/books/covers/backfill", headers=admin["headers"]).json()

        assert body["examined"] == 1
        assert body["remaining"] == 1
        assert body["next_after_id"] == first["id"]

    def test_the_second_run_carries_on_past_the_first(
        self, client, admin, make_book, covers_dir, monkeypatch
    ):
        """Without the cursor a book that cannot be fixed stays at the front of
        every run for ever, and the counter stops moving. Roughly a fifth of any
        batch is permanently unfixable, and a pod with no egress is all of it."""
        import routers.books as books_router

        make_book(admin["headers"], title="A")
        second = make_book(admin["headers"], title="B")
        monkeypatch.setattr(books_router, "MAX_BACKFILL_BOOKS", 1)

        first_run = client.post(
            "/api/books/covers/backfill", headers=admin["headers"]
        ).json()
        second_run = client.post(
            "/api/books/covers/backfill",
            params={"after_id": first_run["next_after_id"]},
            headers=admin["headers"],
        ).json()

        assert second_run["examined"] == 1
        assert second_run["remaining"] == 0
        assert second_run["next_after_id"] == 0
        assert second["id"] > first_run["next_after_id"]

    def test_a_cursor_too_large_for_the_database_is_refused_not_a_500(
        self, client, admin, covers_dir
    ):
        """Python ints have no ceiling and SQLite's do, so an unbounded `int`
        query parameter reaches the driver and raises `OverflowError`, which
        lands in the unhandled-exception handler: a bad request classed as a bug
        in our own code. Every other numeric query in this tree is bounded at
        both ends."""
        res = client.post(
            "/api/books/covers/backfill",
            params={"after_id": "9999999999999999999999"},
            headers=admin["headers"],
        )

        assert res.status_code == 422

    def test_reaching_the_end_resets_the_cursor(
        self, client, admin, make_book, covers_dir
    ):
        """So pressing again starts over and re-tries the ones that failed,
        which may since have become fixable."""
        make_book(admin["headers"], title="A")

        body = client.post("/api/books/covers/backfill", headers=admin["headers"]).json()

        assert body["remaining"] == 0
        assert body["next_after_id"] == 0

    def test_pressing_it_repeatedly_is_rate_limited(self, client, admin, make_book, covers_dir):
        """One run fetches up to a hundred images from two free public services,
        and it is the call somebody presses again while the first is running."""
        for _ in range(6):
            client.post("/api/books/covers/backfill", headers=admin["headers"])

        res = client.post("/api/books/covers/backfill", headers=admin["headers"])

        assert res.status_code == 429


def _give_a_cover(db, covers_dir, book_id: int) -> None:
    """Put a cover file behind a book and point its column at it."""
    from models import Book

    (covers_dir / f"{book_id}.jpg").write_bytes(JPEG_BYTES)
    db.query(Book).filter(Book.id == book_id).update(
        {"cover_url": f"/covers/{book_id}.jpg"}
    )
    db.commit()


class TestTheDirectoryDoesNotDriftFromTheDatabase:
    """Files are what a database row does not carry with it, which is the
    standing cost of holding covers on disk. These are the three places it is
    paid."""

    def test_purging_a_book_deletes_its_cover(
        self, client, admin, make_book, covers_dir, monkeypatch
    ):
        """A cover whose book is gone is dead bytes no query will ever find, and
        SQLite reuses an id, so the next book to take it would inherit this."""
        store_locally(monkeypatch)
        book = make_book(admin["headers"], title="A")
        client.post("/api/books/covers/backfill", headers=admin["headers"])
        assert covers.stored_ids() == {book["id"]}

        client.delete(f"/api/books/{book['id']}", headers=admin["headers"])
        client.delete(
            f"/api/books/{book['id']}/permanent", headers=admin["headers"]
        )

        assert covers.stored_ids() == set()

    def test_emptying_the_trash_deletes_them_too(
        self, client, admin, make_book, covers_dir, monkeypatch
    ):
        store_locally(monkeypatch)
        book = make_book(admin["headers"], title="A")
        client.post("/api/books/covers/backfill", headers=admin["headers"])
        client.delete(f"/api/books/{book['id']}", headers=admin["headers"])

        client.delete("/api/books/trash", headers=admin["headers"])

        assert covers.stored_ids() == set()

    def test_trashing_a_book_keeps_its_cover(
        self, client, admin, make_book, covers_dir, monkeypatch
    ):
        """A trashed book can be restored, and restoring one to a placeholder
        would be a delete that half happened."""
        store_locally(monkeypatch)
        book = make_book(admin["headers"], title="A")
        client.post("/api/books/covers/backfill", headers=admin["headers"])

        client.delete(f"/api/books/{book['id']}", headers=admin["headers"])

        assert covers.stored_ids() == {book["id"]}

    def test_merging_moves_the_cover_it_kept(
        self, client, admin, make_book, covers_dir, db
    ):
        """The keeper can absorb the loser's `cover_url`, which names a file
        about to be deleted with the loser."""
        keeper = make_book(admin["headers"], title="Dune")
        loser = make_book(admin["headers"], title="Dune")
        _give_a_cover(db, covers_dir, loser["id"])

        res = client.post(
            "/api/books/merge",
            json={"book_ids": [keeper["id"], loser["id"]], "keep_id": keeper["id"]},
            headers=admin["headers"],
        )

        assert res.status_code == 200, res.text
        assert covers.stored_ids() == {keeper["id"]}
        assert res.json()["cover_url"] == f"/covers/{keeper['id']}.jpg"

    def test_a_failed_adoption_keeps_the_bytes_and_the_row_honest(
        self, client, admin, make_book, covers_dir, db, monkeypatch
    ):
        """A merge moves the kept cover after it commits, so the move can fail
        on its own with the row already saved.

        `replace_image` is atomic and re-raises having removed only its own
        temporary file, so the loser's cover is still there. Sweeping the
        loser's id anyway destroys the only copy: a hand-uploaded cover has no
        remote source, so the backfill cannot put it back. And the row must not
        be left claiming a cover the move never produced.
        """
        keeper = make_book(admin["headers"], title="Dune")
        loser = make_book(admin["headers"], title="Dune")
        _give_a_cover(db, covers_dir, loser["id"])

        def full_disk(directory, base, extension, data):
            raise OSError(28, "No space left on device")

        monkeypatch.setattr(covers, "replace_image", full_disk)

        res = client.post(
            "/api/books/merge",
            json={"book_ids": [keeper["id"], loser["id"]], "keep_id": keeper["id"]},
            headers=admin["headers"],
        )

        assert res.status_code == 200, res.text
        assert covers.stored_ids() == {loser["id"]}
        assert res.json()["cover_url"] is None

    def test_merging_deletes_a_cover_it_did_not_keep(
        self, client, admin, make_book, covers_dir, db
    ):
        keeper = make_book(admin["headers"], title="Dune")
        loser = make_book(admin["headers"], title="Dune")
        _give_a_cover(db, covers_dir, keeper["id"])
        _give_a_cover(db, covers_dir, loser["id"])

        client.post(
            "/api/books/merge",
            json={"book_ids": [keeper["id"], loser["id"]], "keep_id": keeper["id"]},
            headers=admin["headers"],
        )

        assert covers.stored_ids() == {keeper["id"]}

    def test_the_backfill_re_fetches_a_cover_url_with_no_file_behind_it(
        self, client, admin, make_book, covers_dir, monkeypatch
    ):
        """Trusting the column here is what would let a book claim a cover it
        does not have, for good."""
        store_locally(monkeypatch)
        book = make_book(admin["headers"], title="A")
        client.post("/api/books/covers/backfill", headers=admin["headers"])
        (covers_dir / f"{book['id']}.jpg").unlink()

        body = client.post(
            "/api/books/covers/backfill", headers=admin["headers"]
        ).json()

        assert body["examined"] == 1
        assert body["stored"] == 1
        assert covers.stored_ids() == {book["id"]}


class TestAMemberCannotChooseWhereTheServerConnects:
    """`cover_url` is member input on `BookCreate`, and adding a book makes the
    server fetch it. Without a host check that is an authenticated caller
    pointing the pod at any address it likes.

    These bypass the `offline_covers` autouse fixture on purpose: it stubs
    `resolve_and_store` out, so a test that left it in place would pass without
    exercising the path at all.
    """

    @pytest.fixture(autouse=True)
    def real_fetches(self, monkeypatch):
        from tests.conftest import REAL_RESOLVE_AND_STORE

        monkeypatch.setattr(covers, "resolve_and_store", REAL_RESOLVE_AND_STORE)

    def test_a_supplied_url_on_an_unlisted_host_is_never_requested(
        self, client, admin, covers_dir
    ):
        """respx fails the test on any unmocked request, and nothing is mocked."""
        with respx.mock:
            res = client.post(
                "/api/books",
                json={"title": "Dune", "cover_url": "https://evil.test/x.jpg"},
                headers=admin["headers"],
            )

        assert res.status_code == 201
        # Still stored as a hotlink: `storable` governs what a browser may be
        # pointed at and has to keep admitting any https URL, because that is
        # the fallback when a download fails. What it must not do is make this
        # server connect to it.
        assert res.json()["cover_url"] == "https://evil.test/x.jpg"
        assert covers.stored_ids() == set()

    def test_a_redirect_into_private_space_is_refused_rather_than_followed(
        self, client, admin, covers_dir
    ):
        with respx.mock(assert_all_called=False) as mock:
            mock.get(url__startswith="https://covers.openlibrary.org/").mock(
                return_value=httpx.Response(
                    302, headers={"location": "http://10.0.0.1/x.jpg"}
                )
            )
            mock.get(url__startswith="https://portal.dnb.de/").mock(
                return_value=httpx.Response(404)
            )
            res = client.post(
                "/api/books",
                json={
                    "title": "Dune",
                    "cover_url": "https://covers.openlibrary.org/b/isbn/x-L.jpg",
                },
                headers=admin["headers"],
            )

        assert res.status_code == 201
        assert covers.stored_ids() == set()


class TestACoverFailureNeverFailsTheRequest:
    """`_create_book` commits the row before the cover work runs, so a raise
    there is a 500 on an add that in fact saved the book. In the backfill it
    would be one poisoned row taking the run down for every member.

    Kept in `covers.resolve_and_store` rather than at each call site: it is the
    single entry point both paths use, and a guard per caller is a guard the
    next caller forgets.
    """

    @pytest.fixture(autouse=True)
    def a_cover_path_that_explodes(self, monkeypatch):
        def boom(*args, **kwargs):
            raise RuntimeError("something nobody predicted")

        monkeypatch.setattr(covers, "store", boom)
        monkeypatch.setattr(covers, "resolve", boom)
        from tests.conftest import REAL_RESOLVE_AND_STORE

        monkeypatch.setattr(covers, "resolve_and_store", REAL_RESOLVE_AND_STORE)

    def test_the_book_is_still_added(self, client, admin, covers_dir):
        res = client.post(
            "/api/books",
            json={
                "title": "Dune",
                "cover_url": "https://covers.openlibrary.org/b/isbn/x-L.jpg",
            },
            headers=admin["headers"],
        )

        assert res.status_code == 201
        assert res.json()["title"] == "Dune"

    def test_the_backfill_still_answers(self, client, admin, make_book, covers_dir):
        make_book(admin["headers"], title="A", isbn="9780441013593")

        res = client.post("/api/books/covers/backfill", headers=admin["headers"])

        assert res.status_code == 200
        assert res.json()["still_missing"] == 1

    def test_one_poisoned_book_does_not_take_the_run_down(
        self, client, admin, make_book, covers_dir, db
    ):
        """A member could store `https://books.google.com:99999/x.jpg`, which
        `storable` admits because it only tests the scheme."""
        from models import Book

        make_book(admin["headers"], title="Poison")
        db.query(Book).update({"cover_url": "https://books.google.com:99999/x.jpg"})
        db.commit()
        make_book(admin["headers"], title="Fine")

        res = client.post("/api/books/covers/backfill", headers=admin["headers"])

        assert res.status_code == 200
        assert res.json()["examined"] == 2
