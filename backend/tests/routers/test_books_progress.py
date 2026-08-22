"""Reading progress: the log, its units, and who may see it.

Three endpoints under `routers/books.py`, plus the three `my_progress_*` fields
`serialisation.books_to_out` puts on every book payload. What most of this file
pins is the two rules that are easy to get wrong later: exactly one unit per
entry, and a log that is personal even on a shared shelf.
"""

import pytest


@pytest.fixture
def record(client):
    """Post a position and return the created entry."""

    def _record(headers, book_id, **payload):
        res = client.post(
            f"/api/books/{book_id}/progress", json=payload, headers=headers
        )
        assert res.status_code == 201, res.text
        return res.json()

    return _record


def history(client, headers, book_id):
    res = client.get(f"/api/books/{book_id}/progress", headers=headers)
    assert res.status_code == 200, res.text
    return res.json()


class TestRecordingAPosition:
    def test_records_a_page(self, admin, make_book, record):
        book = make_book(admin["headers"])
        entry = record(admin["headers"], book["id"], page=42)
        assert entry["page"] == 42
        assert entry["percent"] is None

    def test_records_a_percent_for_a_book_with_no_pages(self, admin, make_book, record):
        """An audiobook has no page to be on."""
        book = make_book(admin["headers"])
        entry = record(admin["headers"], book["id"], percent=40)
        assert entry["percent"] == 40
        assert entry["page"] is None

    def test_records_how_long_the_sitting_was(self, admin, make_book, record):
        book = make_book(admin["headers"])
        assert record(admin["headers"], book["id"], page=10, minutes=25)["minutes"] == 25

    def test_refuses_both_units_at_once(self, client, admin, make_book):
        """Carrying both would need a rule for which one wins."""
        book = make_book(admin["headers"])
        res = client.post(
            f"/api/books/{book['id']}/progress",
            json={"page": 10, "percent": 20},
            headers=admin["headers"],
        )
        assert res.status_code == 422

    def test_refuses_neither_unit(self, client, admin, make_book):
        book = make_book(admin["headers"])
        res = client.post(
            f"/api/books/{book['id']}/progress",
            json={"minutes": 30},
            headers=admin["headers"],
        )
        assert res.status_code == 422

    def test_refuses_page_zero(self, client, admin, make_book):
        book = make_book(admin["headers"])
        res = client.post(
            f"/api/books/{book['id']}/progress",
            json={"page": 0},
            headers=admin["headers"],
        )
        assert res.status_code == 422

    def test_refuses_a_percent_over_a_hundred(self, client, admin, make_book):
        book = make_book(admin["headers"])
        res = client.post(
            f"/api/books/{book['id']}/progress",
            json={"percent": 140},
            headers=admin["headers"],
        )
        assert res.status_code == 422

    def test_the_database_refuses_both_units_too(self, db, admin, make_book):
        """The CHECK constraint, not only the schema.

        A restore inserts through Core and never sees a Pydantic model, which
        is the writer this constraint exists because you cannot rely on.
        """
        from sqlalchemy.exc import IntegrityError

        from models import ReadingProgress

        book = make_book(admin["headers"])
        db.add(
            ReadingProgress(
                user_id=admin["user"]["id"], book_id=book["id"], page=10, percent=20
            )
        )
        with pytest.raises(IntegrityError):
            db.commit()
        db.rollback()

    def test_a_book_the_caller_cannot_see_is_404(self, client, admin, member, make_book):
        book = make_book(admin["headers"], is_private=True)
        res = client.post(
            f"/api/books/{book['id']}/progress",
            json={"page": 5},
            headers=member["headers"],
        )
        assert res.status_code == 404


class TestTheStatusFollows:
    def test_recording_progress_promotes_an_unread_book(self, client, admin, make_book, record):
        """The same fact the status button asserts, from the other direction."""
        book = make_book(admin["headers"])
        record(admin["headers"], book["id"], page=12)

        fetched = client.get(f"/api/books/{book['id']}", headers=admin["headers"]).json()
        assert fetched["my_status"] == "reading"
        assert fetched["my_started_at"] is not None

    def test_it_promotes_a_book_only_wanted(self, client, admin, make_book, record):
        book = make_book(admin["headers"])
        client.put(
            f"/api/books/{book['id']}/status",
            json={"status": "want_to_read"},
            headers=admin["headers"],
        )
        record(admin["headers"], book["id"], page=12)

        fetched = client.get(f"/api/books/{book['id']}", headers=admin["headers"]).json()
        assert fetched["my_status"] == "reading"

    def test_it_never_marks_a_book_read(self, client, admin, make_book, record):
        """`page_count` is a provider's number and is off by one often enough
        that the last page is not a finish signal."""
        book = make_book(admin["headers"], page_count=200)
        record(admin["headers"], book["id"], page=200)

        fetched = client.get(f"/api/books/{book['id']}", headers=admin["headers"]).json()
        assert fetched["my_status"] == "reading"
        assert fetched["my_finished_at"] is None

    def test_it_does_not_reopen_a_finished_book(self, client, admin, make_book, record):
        """A re-read is a real thing, and the log records it without the status
        claiming the book is unfinished again."""
        book = make_book(admin["headers"])
        client.put(
            f"/api/books/{book['id']}/status",
            json={"status": "read"},
            headers=admin["headers"],
        )
        record(admin["headers"], book["id"], page=30)

        fetched = client.get(f"/api/books/{book['id']}", headers=admin["headers"]).json()
        assert fetched["my_status"] == "read"
        assert fetched["my_finished_at"] is not None

    def test_marking_a_book_unread_keeps_its_progress(self, client, admin, make_book, record):
        """Deliberately unlike `started_at`, which is derived and is cleared."""
        book = make_book(admin["headers"])
        record(admin["headers"], book["id"], page=30)

        client.put(
            f"/api/books/{book['id']}/status",
            json={"status": "unread"},
            headers=admin["headers"],
        )

        assert len(history(client, admin["headers"], book["id"])) == 1


class TestTheHistory:
    def test_newest_first(self, client, admin, make_book, record):
        book = make_book(admin["headers"])
        record(admin["headers"], book["id"], page=10)
        record(admin["headers"], book["id"], page=90)

        assert [row["page"] for row in history(client, admin["headers"], book["id"])] == [
            90,
            10,
        ]

    def test_a_member_never_sees_another_members_progress(
        self, client, admin, member, make_book, record
    ):
        """A shared shelf does not mean a shared reading diary."""
        book = make_book(admin["headers"])
        record(admin["headers"], book["id"], page=77)

        assert history(client, member["headers"], book["id"]) == []

    def test_the_book_payload_carries_only_the_callers_own(
        self, client, admin, member, make_book, record
    ):
        book = make_book(admin["headers"])
        record(admin["headers"], book["id"], page=77)

        seen = client.get(f"/api/books/{book['id']}", headers=member["headers"]).json()
        assert seen["my_progress_page"] is None
        assert seen["my_progress_recorded_at"] is None

    def test_a_book_the_caller_cannot_see_is_404(self, client, admin, member, make_book):
        book = make_book(admin["headers"], is_private=True)
        assert (
            client.get(f"/api/books/{book['id']}/progress", headers=member["headers"]).status_code
            == 404
        )


class TestTheBookPayload:
    def test_carries_the_newest_position(self, client, admin, make_book, record):
        book = make_book(admin["headers"], page_count=200)
        record(admin["headers"], book["id"], page=10)
        record(admin["headers"], book["id"], page=100)

        fetched = client.get(f"/api/books/{book['id']}", headers=admin["headers"]).json()
        assert fetched["my_progress_page"] == 100
        assert fetched["my_progress_percent"] == 50

    def test_a_page_with_no_page_count_derives_no_percent(
        self, client, admin, make_book, record
    ):
        book = make_book(admin["headers"])
        record(admin["headers"], book["id"], page=100)

        fetched = client.get(f"/api/books/{book['id']}", headers=admin["headers"]).json()
        assert fetched["my_progress_page"] == 100
        assert fetched["my_progress_percent"] is None

    def test_a_recorded_percent_is_used_as_is(self, client, admin, make_book, record):
        book = make_book(admin["headers"])
        record(admin["headers"], book["id"], percent=40)

        fetched = client.get(f"/api/books/{book['id']}", headers=admin["headers"]).json()
        assert fetched["my_progress_percent"] == 40

    def test_a_page_past_the_page_count_clamps_to_a_hundred(
        self, client, admin, make_book, record
    ):
        """Provider page counts are off by one often enough that the last page
        computes past 100."""
        book = make_book(admin["headers"], page_count=100)
        record(admin["headers"], book["id"], page=103)

        fetched = client.get(f"/api/books/{book['id']}", headers=admin["headers"]).json()
        assert fetched["my_progress_percent"] == 100

    def test_a_book_with_no_progress_carries_nulls(self, client, admin, make_book):
        book = make_book(admin["headers"])
        fetched = client.get(f"/api/books/{book['id']}", headers=admin["headers"]).json()
        assert fetched["my_progress_page"] is None
        assert fetched["my_progress_percent"] is None

    def test_the_listing_fills_it_in_too(self, client, admin, make_book, record):
        book = make_book(admin["headers"], page_count=100)
        record(admin["headers"], book["id"], page=25)

        listed = client.get("/api/books", headers=admin["headers"]).json()["items"]
        assert listed[0]["my_progress_percent"] == 25


class TestDeletingAnEntry:
    def test_removes_it(self, client, admin, make_book, record):
        book = make_book(admin["headers"])
        entry = record(admin["headers"], book["id"], page=10)

        res = client.delete(
            f"/api/books/{book['id']}/progress/{entry['id']}", headers=admin["headers"]
        )

        assert res.status_code == 204
        assert history(client, admin["headers"], book["id"]) == []

    def test_another_members_entry_is_404_not_403(
        self, client, admin, member, make_book, record
    ):
        """A 403 would confirm the entry exists."""
        book = make_book(admin["headers"])
        entry = record(admin["headers"], book["id"], page=10)

        res = client.delete(
            f"/api/books/{book['id']}/progress/{entry['id']}", headers=member["headers"]
        )

        assert res.status_code == 404
        assert len(history(client, admin["headers"], book["id"])) == 1

    def test_an_entry_from_another_book_is_404(self, client, admin, make_book, record):
        """The ids must agree, so an entry cannot be reached through a book the
        caller happens to have access to."""
        first = make_book(admin["headers"], title="First")
        second = make_book(admin["headers"], title="Second")
        entry = record(admin["headers"], first["id"], page=10)

        res = client.delete(
            f"/api/books/{second['id']}/progress/{entry['id']}", headers=admin["headers"]
        )

        assert res.status_code == 404

    def test_it_leaves_the_status_alone(self, client, admin, make_book, record):
        """Removing a mistyped page is not a claim about having started."""
        book = make_book(admin["headers"])
        entry = record(admin["headers"], book["id"], page=10)

        client.delete(
            f"/api/books/{book['id']}/progress/{entry['id']}", headers=admin["headers"]
        )

        fetched = client.get(f"/api/books/{book['id']}", headers=admin["headers"]).json()
        assert fetched["my_status"] == "reading"


class TestMerging:
    def test_progress_moves_to_the_surviving_book(self, client, admin, make_book, record):
        """Left behind, it would be cascade-deleted with the loser, throwing
        away reading history the merge was never asked to touch."""
        keeper = make_book(admin["headers"], title="Dune", author="Frank Herbert")
        loser = make_book(admin["headers"], title="Dune.", author="Frank Herbert")
        record(admin["headers"], loser["id"], page=64)

        res = client.post(
            "/api/books/merge",
            json={"book_ids": [keeper["id"], loser["id"]], "keep_id": keeper["id"]},
            headers=admin["headers"],
        )

        assert res.status_code == 200
        assert [row["page"] for row in history(client, admin["headers"], keeper["id"])] == [64]
