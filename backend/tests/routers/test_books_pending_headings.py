"""A harvest's pending headings on a Book: the list, the confirm, the discard, the merge.

What raises them is the harvest, `tests/routers/test_imports_harvest.py`. Here the
rows are written straight onto a Book, so each route is read on its own.
"""

from datetime import datetime

from sqlalchemy import select

from models import Book, Classification, Harvest, PendingHeading


def harvest(db) -> int:
    run = Harvest(base_url="http://10.0.0.1/oai", metadata_prefix="marcxml")
    db.add(run)
    db.flush()
    return run.id


def with_pending(db, book_id: int, *numbers: str, scheme: str = "ddc", settled: bool = False) -> None:
    run = harvest(db)
    db.add_all(
        PendingHeading(
            book_id=book_id,
            harvest_id=run,
            scheme=scheme,
            number=number,
            settled_at=datetime(2026, 11, 21) if settled else None,
        )
        for number in numbers
    )
    db.commit()


def settled(db, book_id: int) -> list[tuple[str, bool]]:
    db.expire_all()
    rows = db.scalars(
        select(PendingHeading).where(PendingHeading.book_id == book_id).order_by(PendingHeading.id)
    )
    return [(row.number, row.settled_at is not None) for row in rows]


def headings(db, book_id: int) -> list[str]:
    db.expire_all()
    return list(db.scalars(select(Classification.number).where(Classification.book_id == book_id)))


def url(book_id: int, action: str = "") -> str:
    return f"/api/books/{book_id}/pending-headings{action}"


class TestTheList:
    def test_it_lists_the_unsettled_headings_in_the_order_raised(self, client, admin, db, make_book):
        book = make_book(admin["headers"], title="Stoner")["id"]
        with_pending(db, book, "100", settled=True)
        with_pending(db, book, "004", "510")

        res = client.get(url(book), headers=admin["headers"])

        assert res.status_code == 200
        assert [row["number"] for row in res.json()] == ["004", "510"]

    def test_a_member_is_refused_on_a_book_they_see(self, client, admin, member, db, make_book):
        book = make_book(admin["headers"], title="Stoner")["id"]
        with_pending(db, book, "004")

        for res in (
            client.get(url(book), headers=member["headers"]),
            client.post(url(book, "/confirm"), headers=member["headers"]),
            client.post(url(book, "/discard"), headers=member["headers"]),
        ):
            assert res.status_code == 403
        assert settled(db, book) == [("004", False)]

    def test_a_book_the_caller_cannot_see_answers_what_an_absent_one_does(
        self, client, admin, member, db, make_book
    ):
        private = make_book(member["headers"], title="Diary", is_private=True)["id"]

        refused = client.post(url(private, "/confirm"), headers=admin["headers"])
        absent = client.post(url(private + 5000, "/confirm"), headers=admin["headers"])

        assert refused.status_code == absent.status_code == 404
        assert refused.json() == absent.json()

    def test_a_member_on_a_book_they_cannot_see_is_told_404_before_403(
        self, client, member, other_user, db, make_book
    ):
        """The admin test above proves the visibility check, not its order: only a
        member, refused on both counts, shows which is asked first. A 403 here
        would confirm the id exists."""
        private = make_book(other_user["headers"], title="Diary", is_private=True)["id"]
        with_pending(db, private, "004")

        for method, action in (("get", ""), ("post", "/confirm"), ("post", "/discard")):
            refused = client.request(method, url(private, action), headers=member["headers"])
            absent = client.request(method, url(private + 5000, action), headers=member["headers"])

            assert refused.status_code == absent.status_code == 404, action
            assert refused.json() == absent.json()
        assert settled(db, private) == [("004", False)]


class TestTheConfirm:
    def test_it_writes_the_whole_set_and_settles_it(self, client, admin, db, make_book):
        book = make_book(admin["headers"], title="Stoner")["id"]
        with_pending(db, book, "004", "510")

        res = client.post(url(book, "/confirm"), headers=admin["headers"])

        assert res.status_code == 200, res.text
        assert [row["number"] for row in res.json()["classifications"]] == ["004", "510"]
        assert settled(db, book) == [("004", True), ("510", True)]
        assert client.get(url(book), headers=admin["headers"]).json() == []

    def test_a_heading_under_a_scheme_nobody_defined_is_dropped_and_settled(
        self, client, admin, db, make_book
    ):
        """A suggestion carries no foreign key, so a scheme deleted since the harvest
        reaches the confirm, which drops it as a catalogue's is dropped."""
        book = make_book(admin["headers"], title="Stoner")["id"]
        with_pending(db, book, "004")
        with_pending(db, book, "X1", scheme="gone")

        res = client.post(url(book, "/confirm"), headers=admin["headers"])

        assert res.status_code == 200, res.text
        assert headings(db, book) == ["004"]
        assert settled(db, book) == [("004", True), ("X1", True)]

    def test_confirming_nothing_changes_nothing(self, client, admin, db, make_book):
        book = make_book(admin["headers"], title="Stoner")["id"]

        res = client.post(url(book, "/confirm"), headers=admin["headers"])

        assert res.status_code == 200
        assert headings(db, book) == []


class TestTheDiscard:
    def test_it_settles_the_whole_set_and_writes_nothing(self, client, admin, db, make_book):
        book = make_book(admin["headers"], title="Stoner")["id"]
        with_pending(db, book, "004", "510")

        res = client.post(url(book, "/discard"), headers=admin["headers"])

        assert res.status_code == 204
        assert headings(db, book) == []
        assert settled(db, book) == [("004", True), ("510", True)]


class TestAMergeLeavesThemToTheCascade:
    def test_the_keeper_keeps_its_own_and_the_losers_go(self, client, admin, db, make_book):
        keeper = make_book(admin["headers"], title="Stoner")["id"]
        loser = make_book(admin["headers"], title="Stoner")["id"]
        with_pending(db, keeper, "004")
        with_pending(db, loser, "510")

        res = client.post(
            "/api/books/merge",
            json={"book_ids": [keeper, loser], "keep_id": keeper},
            headers=admin["headers"],
        )

        assert res.status_code == 200, res.text
        assert settled(db, keeper) == [("004", False)]
        assert db.get(Book, loser) is None
        assert settled(db, loser) == []
