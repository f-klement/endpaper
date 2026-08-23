"""Tests for backend/routers/stats.py."""

import pytest

from models import Tag


@pytest.fixture
def stats(client, admin):
    def _fetch(headers=None):
        res = client.get("/api/stats", headers=headers or admin["headers"])
        assert res.status_code == 200, res.text
        return res.json()

    return _fetch


class TestTotals:
    def test_empty_library_totals_zero(self, stats):
        assert stats()["total"] == 0

    def test_counts_the_books(self, admin, make_book, stats):
        for title in ("A", "B", "C"):
            make_book(admin["headers"], title=title)
        assert stats()["total"] == 3

    def test_requires_authentication(self, client):
        assert client.get("/api/stats").status_code == 401


class TestPerUser:
    def test_attributes_books_to_who_added_them(self, admin, member, make_book, stats):
        make_book(admin["headers"], title="A")
        make_book(member["headers"], title="B")
        make_book(member["headers"], title="C")
        per_user = {row["username"]: row["count"] for row in stats()["per_user"]}
        assert per_user == {"admin": 1, "member": 2}

    def test_sorted_by_count_descending(self, admin, member, make_book, stats):
        make_book(admin["headers"], title="A")
        for title in ("B", "C"):
            make_book(member["headers"], title=title)
        assert [row["username"] for row in stats()["per_user"]] == ["member", "admin"]

    def test_a_member_with_no_books_is_omitted(self, admin, member, make_book, stats):
        make_book(admin["headers"], title="A")
        assert [row["username"] for row in stats()["per_user"]] == ["admin"]


class TestByTag:
    def test_counts_books_per_tag(self, client, admin, make_book, db, stats):
        fantasy = db.query(Tag).filter(Tag.name == "Fantasy").one()
        for title in ("A", "B"):
            book = make_book(admin["headers"], title=title)
            client.post(f"/api/books/{book['id']}/tags/{fantasy.id}", headers=admin["headers"])
        by_tag = {row["name"]: row["count"] for row in stats()["by_tag"]}
        assert by_tag["Fantasy"] == 2

    def test_untagged_books_appear_in_no_tag_row(self, admin, make_book, stats):
        make_book(admin["headers"], title="Untagged")
        assert stats()["by_tag"] == []

    def test_rows_carry_their_category(self, client, admin, make_book, db, stats):
        fantasy = db.query(Tag).filter(Tag.name == "Fantasy").one()
        book = make_book(admin["headers"])
        client.post(f"/api/books/{book['id']}/tags/{fantasy.id}", headers=admin["headers"])
        assert stats()["by_tag"][0]["category"] == "genre"

    def test_a_book_with_two_tags_counts_once_under_each(
        self, client, admin, make_book, db, stats
    ):
        fantasy = db.query(Tag).filter(Tag.name == "Fantasy").one()
        adult = db.query(Tag).filter(Tag.name == "Adult").one()
        book = make_book(admin["headers"])
        for tag in (fantasy, adult):
            client.post(f"/api/books/{book['id']}/tags/{tag.id}", headers=admin["headers"])
        by_tag = {row["name"]: row["count"] for row in stats()["by_tag"]}
        assert by_tag == {"Fantasy": 1, "Adult": 1}


class TestByCollection:
    def test_counts_books_per_collection(self, client, admin, make_book, stats):
        shelf = client.post(
            "/api/collections", json={"name": "Ebooks"}, headers=admin["headers"]
        ).json()
        for title in ("A", "B"):
            book = make_book(admin["headers"], title=title)
            client.patch(
                f"/api/books/{book['id']}/collection",
                json={"collection_id": shelf["id"]},
                headers=admin["headers"],
            )

        assert stats()["by_collection"] == [{"name": "Ebooks", "count": 2}]

    def test_an_empty_collection_has_no_row(self, client, admin, stats):
        client.post("/api/collections", json={"name": "Ebooks"}, headers=admin["headers"])
        assert stats()["by_collection"] == []

    def test_unfiled_books_are_not_a_bucket(self, admin, make_book, stats):
        """`total` minus the sum of these is how many there are, and a nameless
        row here would need a name to render."""
        make_book(admin["headers"], title="Loose")

        assert stats()["by_collection"] == []
        assert stats()["total"] == 1

    def test_another_members_private_book_is_not_counted(
        self, client, admin, member, make_book, stats
    ):
        """A shelf label everybody can read must not report how many private
        books somebody has put on it."""
        shelf = client.post(
            "/api/collections", json={"name": "Ebooks"}, headers=admin["headers"]
        ).json()
        hidden = make_book(admin["headers"], title="Secret", is_private=True)
        client.patch(
            f"/api/books/{hidden['id']}/collection",
            json={"collection_id": shelf["id"]},
            headers=admin["headers"],
        )

        assert stats(member["headers"])["by_collection"] == []


class TestByMonth:
    def test_groups_books_into_a_year_month_bucket(self, admin, make_book, stats):
        make_book(admin["headers"], title="A")
        by_month = stats()["by_month"]
        assert len(by_month) == 1
        assert by_month[0]["count"] == 1

    def test_the_bucket_key_is_yyyy_mm(self, admin, make_book, stats):
        import re

        make_book(admin["headers"], title="A")
        assert re.fullmatch(r"\d{4}-\d{2}", stats()["by_month"][0]["month"])

    def test_empty_library_has_no_buckets(self, stats):
        assert stats()["by_month"] == []


class TestPrivacyIsRespected:
    def test_another_user_s_private_book_is_not_counted(self, admin, member, make_book, stats):
        make_book(admin["headers"], title="Secret", is_private=True)
        assert stats(member["headers"])["total"] == 0

    def test_the_owner_s_own_private_book_is_counted(self, admin, make_book, stats):
        make_book(admin["headers"], title="Secret", is_private=True)
        assert stats()["total"] == 1

    def test_private_books_are_excluded_from_per_user(self, admin, member, make_book, stats):
        make_book(admin["headers"], title="Secret", is_private=True)
        assert stats(member["headers"])["per_user"] == []

    def test_private_books_are_excluded_from_by_tag(
        self, client, admin, member, make_book, db, stats
    ):
        fantasy = db.query(Tag).filter(Tag.name == "Fantasy").one()
        book = make_book(admin["headers"], title="Secret", is_private=True)
        client.post(f"/api/books/{book['id']}/tags/{fantasy.id}", headers=admin["headers"])
        assert stats(member["headers"])["by_tag"] == []

    def test_private_books_are_excluded_from_by_month(self, admin, member, make_book, stats):
        make_book(admin["headers"], title="Secret", is_private=True)
        assert stats(member["headers"])["by_month"] == []


class TestReadingStats:
    """Finished-per-month and the rating average, both personal.

    Every other series here is a fact about the shelf. These two are facts
    about a reader, so they must not aggregate across members.
    """

    def stats(self, client, headers) -> dict:
        return client.get("/api/stats", headers=headers).json()

    def test_a_finished_book_appears_in_the_month_series(self, client, admin, make_book):
        book = make_book(admin["headers"])
        client.put(
            f"/api/books/{book['id']}/status", json={"status": "read"}, headers=admin["headers"]
        )

        series = self.stats(client, admin["headers"])["finished_by_month"]

        assert sum(row["count"] for row in series) == 1

    def test_an_unfinished_book_does_not(self, client, admin, make_book):
        book = make_book(admin["headers"])
        client.put(
            f"/api/books/{book['id']}/status", json={"status": "reading"}, headers=admin["headers"]
        )

        assert self.stats(client, admin["headers"])["finished_by_month"] == []

    def test_the_series_is_personal(self, client, admin, member, make_book):
        book = make_book(admin["headers"])
        client.put(
            f"/api/books/{book['id']}/status", json={"status": "read"}, headers=admin["headers"]
        )

        assert self.stats(client, member["headers"])["finished_by_month"] == []

    def test_another_members_private_book_is_never_counted(
        self, client, admin, member, make_book
    ):
        """Not even as an anonymous number: the privacy predicate applies here
        like everywhere else."""
        private = make_book(admin["headers"], is_private=True)
        client.put(
            f"/api/books/{private['id']}/status", json={"status": "read"}, headers=admin["headers"]
        )

        assert self.stats(client, member["headers"])["finished_by_month"] == []

    def test_reports_the_average_rating(self, client, admin, make_book):
        for rating in (2, 4):
            book = make_book(admin["headers"], title=f"Book {rating}")
            client.patch(
                f"/api/books/{book['id']}/rating",
                json={"rating": rating},
                headers=admin["headers"],
            )

        body = self.stats(client, admin["headers"])

        assert body["average_rating"] == 3.0
        assert body["rated_count"] == 2

    def test_no_ratings_means_no_average(self, client, admin, make_book):
        # Zero would be a rating nobody gave.
        make_book(admin["headers"])

        body = self.stats(client, admin["headers"])

        assert body["average_rating"] is None
        assert body["rated_count"] == 0

    def test_the_average_is_personal(self, client, admin, member, make_book):
        book = make_book(admin["headers"])
        client.patch(
            f"/api/books/{book['id']}/rating", json={"rating": 5}, headers=admin["headers"]
        )

        assert self.stats(client, member["headers"])["average_rating"] is None


class TestPagesByMonth:
    """Pages read per month, from the deltas between recorded positions.

    Page-tracked books only. A percent cannot be added to a page count, so an
    audiobook contributes nothing here rather than a converted figure that
    would add up with the others while meaning something else.
    """

    def record(self, client, headers, book_id, **payload):
        res = client.post(f"/api/books/{book_id}/progress", json=payload, headers=headers)
        assert res.status_code == 201, res.text

    def test_no_progress_means_no_series(self, admin, make_book, stats):
        make_book(admin["headers"])
        assert stats()["pages_by_month"] == []

    def test_the_first_entry_counts_in_full(self, client, admin, make_book, stats):
        """Reaching page 80 means eighty pages were read."""
        book = make_book(admin["headers"])
        self.record(client, admin["headers"], book["id"], page=80)

        assert [row["count"] for row in stats()["pages_by_month"]] == [80]

    def test_later_entries_count_the_difference(self, client, admin, make_book, stats):
        book = make_book(admin["headers"])
        self.record(client, admin["headers"], book["id"], page=80)
        self.record(client, admin["headers"], book["id"], page=140)

        assert [row["count"] for row in stats()["pages_by_month"]] == [140]

    def test_a_backwards_step_counts_nothing(self, client, admin, make_book, stats):
        """A correction of a typo must not be able to inflate the figure."""
        book = make_book(admin["headers"])
        self.record(client, admin["headers"], book["id"], page=400)
        self.record(client, admin["headers"], book["id"], page=40)

        assert [row["count"] for row in stats()["pages_by_month"]] == [400]

    def test_two_books_are_counted_separately(self, client, admin, make_book, stats):
        """The previous row means the previous entry on *this* book."""
        first = make_book(admin["headers"], title="A")
        second = make_book(admin["headers"], title="B")
        self.record(client, admin["headers"], first["id"], page=100)
        self.record(client, admin["headers"], second["id"], page=30)

        assert [row["count"] for row in stats()["pages_by_month"]] == [130]

    def test_a_percent_entry_is_excluded(self, client, admin, make_book, stats):
        book = make_book(admin["headers"])
        self.record(client, admin["headers"], book["id"], percent=40)

        assert stats()["pages_by_month"] == []

    def test_it_is_personal(self, client, admin, member, make_book, stats):
        book = make_book(admin["headers"])
        self.record(client, admin["headers"], book["id"], page=80)

        assert stats(member["headers"])["pages_by_month"] == []

    def test_a_trashed_book_drops_out(self, client, admin, make_book, stats):
        """`visible_to` carries the trashed check as well as the privacy one,
        and this aggregation applies it like every other. The rows are the
        caller's own, so nothing but the predicate can exclude them."""
        book = make_book(admin["headers"])
        self.record(client, admin["headers"], book["id"], page=80)
        assert [row["count"] for row in stats()["pages_by_month"]] == [80]

        client.delete(f"/api/books/{book['id']}", headers=admin["headers"])

        assert stats()["pages_by_month"] == []
