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
