"""Tests for backend/routers/loans.py."""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.exc import IntegrityError

from models import Loan
from tests.helpers import items


@pytest.fixture
def book(client, admin, make_book) -> dict:
    return make_book(admin["headers"], title="Lendable")


@pytest.fixture
def loan(client, admin, member, book) -> dict:
    res = client.post(
        "/api/loans",
        json={"book_id": book["id"], "loaned_to_user_id": member["user"]["id"]},
        headers=admin["headers"],
    )
    assert res.status_code == 201, res.text
    return res.json()


class TestCreateLoan:
    def test_creates_a_loan(self, loan, member):
        assert loan["loaned_to"]["username"] == "member"
        assert loan["returned_at"] is None

    def test_records_who_lent_it(self, loan):
        assert loan["loaned_by"]["username"] == "admin"

    def test_embeds_the_book(self, loan, book):
        assert loan["book"]["title"] == "Lendable"

    def test_the_book_reports_its_active_loan(self, client, admin, book, loan):
        fetched = client.get(f"/api/books/{book['id']}", headers=admin["headers"]).json()
        assert fetched["active_loan"]["id"] == loan["id"]

    def test_lending_an_already_lent_book_is_409(self, client, admin, member, book, loan):
        res = client.post(
            "/api/loans",
            json={"book_id": book["id"], "loaned_to_user_id": member["user"]["id"]},
            headers=admin["headers"],
        )
        assert res.status_code == 409

    def test_unknown_book_is_404(self, client, admin, member):
        res = client.post(
            "/api/loans",
            json={"book_id": 9999, "loaned_to_user_id": member["user"]["id"]},
            headers=admin["headers"],
        )
        assert res.status_code == 404

    def test_unknown_borrower_is_404(self, client, admin, book):
        res = client.post(
            "/api/loans",
            json={"book_id": book["id"], "loaned_to_user_id": 9999},
            headers=admin["headers"],
        )
        assert res.status_code == 404

    def test_requires_authentication(self, client, book, member):
        res = client.post(
            "/api/loans",
            json={"book_id": book["id"], "loaned_to_user_id": member["user"]["id"]},
        )
        assert res.status_code == 401


class TestReturnLoan:
    def test_marks_it_returned(self, client, admin, loan):
        res = client.put(f"/api/loans/{loan['id']}/return", headers=admin["headers"])
        assert res.status_code == 200
        assert res.json()["returned_at"] is not None

    def test_the_book_no_longer_reports_an_active_loan(self, client, admin, book, loan):
        client.put(f"/api/loans/{loan['id']}/return", headers=admin["headers"])
        fetched = client.get(f"/api/books/{book['id']}", headers=admin["headers"]).json()
        assert fetched["active_loan"] is None

    def test_returning_frees_the_book_to_be_lent_again(self, client, admin, member, book, loan):
        client.put(f"/api/loans/{loan['id']}/return", headers=admin["headers"])
        res = client.post(
            "/api/loans",
            json={"book_id": book["id"], "loaned_to_user_id": member["user"]["id"]},
            headers=admin["headers"],
        )
        assert res.status_code == 201

    def test_returning_twice_is_400(self, client, admin, loan):
        client.put(f"/api/loans/{loan['id']}/return", headers=admin["headers"])
        res = client.put(f"/api/loans/{loan['id']}/return", headers=admin["headers"])
        assert res.status_code == 400

    def test_unknown_loan_is_404(self, client, admin):
        assert client.put("/api/loans/9999/return", headers=admin["headers"]).status_code == 404

    def test_anyone_signed_in_may_record_a_return(self, client, member, loan):
        """Returning a book is a shelf action, not an ownership one."""
        res = client.put(f"/api/loans/{loan['id']}/return", headers=member["headers"])
        assert res.status_code == 200


class TestListLoans:
    def test_defaults_to_active_only(self, client, admin, loan):
        client.put(f"/api/loans/{loan['id']}/return", headers=admin["headers"])
        assert items(client.get("/api/loans", headers=admin["headers"])) == []

    def test_active_only_false_includes_returned_loans(self, client, admin, loan):
        client.put(f"/api/loans/{loan['id']}/return", headers=admin["headers"])
        listed = items(
            client.get("/api/loans", params={"active_only": "false"}, headers=admin["headers"])
        )
        assert len(listed) == 1

    def test_lists_an_active_loan(self, client, admin, loan):
        listed = items(client.get("/api/loans", headers=admin["headers"]))
        assert [item["id"] for item in listed] == [loan["id"]]

    def test_newest_first(self, client, admin, member, make_book):
        """Regression: loans created in the same second used to tie, because
        SQLite's CURRENT_TIMESTAMP has only second resolution. The query
        breaks the tie on id."""
        ids = []
        for title in ("First", "Second"):
            book = make_book(admin["headers"], title=title)
            ids.append(
                client.post(
                    "/api/loans",
                    json={"book_id": book["id"], "loaned_to_user_id": member["user"]["id"]},
                    headers=admin["headers"],
                ).json()["id"]
            )
        listed = items(client.get("/api/loans", headers=admin["headers"]))
        assert [item["id"] for item in listed] == list(reversed(ids))

    def test_requires_authentication(self, client):
        assert client.get("/api/loans").status_code == 401


class TestDueDates:
    """A loan with no due date is still a loan.

    Most family lending has no deadline, so the field is optional. It exists so
    that an open loan can be called overdue by something other than a person
    remembering, which is the only reason to record a loan at all.
    """

    def past(self) -> str:
        return (datetime.now(UTC) - timedelta(days=3)).replace(tzinfo=None).isoformat()

    def future(self) -> str:
        return (datetime.now(UTC) + timedelta(days=7)).replace(tzinfo=None).isoformat()

    def lend(self, client, admin, member, book, due_at=None):
        payload = {"book_id": book["id"], "loaned_to_user_id": member["user"]["id"]}
        if due_at is not None:
            payload["due_at"] = due_at
        return client.post("/api/loans", json=payload, headers=admin["headers"])

    def test_a_loan_needs_no_due_date(self, client, admin, member, make_book):
        book = make_book(admin["headers"])

        res = self.lend(client, admin, member, book)

        assert res.status_code == 201
        assert res.json()["due_at"] is None
        assert res.json()["is_overdue"] is False

    def test_records_a_due_date(self, client, admin, member, make_book):
        book = make_book(admin["headers"])

        res = self.lend(client, admin, member, book, self.future())

        assert res.json()["due_at"] is not None
        assert res.json()["is_overdue"] is False

    def test_a_passed_deadline_is_overdue(self, client, admin, member, make_book):
        book = make_book(admin["headers"])

        res = self.lend(client, admin, member, book, self.past())

        assert res.json()["is_overdue"] is True

    def test_a_returned_loan_is_never_overdue(self, client, admin, member, make_book):
        """The field answers "chase this", not "was this late"."""
        book = make_book(admin["headers"])
        loan = self.lend(client, admin, member, book, self.past()).json()

        returned = client.put(f"/api/loans/{loan['id']}/return", headers=admin["headers"])

        assert returned.json()["is_overdue"] is False

    def test_overdue_only_filters_the_listing(self, client, admin, member, make_book):
        late = make_book(admin["headers"], title="Late")
        fine = make_book(admin["headers"], title="Fine")
        self.lend(client, admin, member, late, self.past())
        self.lend(client, admin, member, fine, self.future())

        res = client.get(
            "/api/loans", params={"overdue_only": True}, headers=admin["headers"]
        )

        assert [item["book"]["title"] for item in res.json()["items"]] == ["Late"]

    def test_overdue_only_reports_an_honest_total(self, client, admin, member, make_book):
        """Filtered in SQL rather than by discarding rows after serialising, or
        `total` and the paging would describe a different set than `items`."""
        late = make_book(admin["headers"], title="Late")
        fine = make_book(admin["headers"], title="Fine")
        self.lend(client, admin, member, late, self.past())
        self.lend(client, admin, member, fine, self.future())

        res = client.get(
            "/api/loans", params={"overdue_only": True}, headers=admin["headers"]
        )

        assert res.json()["total"] == 1

    def test_overdue_only_excludes_a_loan_with_no_deadline(
        self, client, admin, member, make_book
    ):
        book = make_book(admin["headers"])
        self.lend(client, admin, member, book)

        res = client.get(
            "/api/loans", params={"overdue_only": True}, headers=admin["headers"]
        )

        assert res.json()["total"] == 0

    def test_overdue_only_excludes_a_returned_loan(self, client, admin, member, make_book):
        book = make_book(admin["headers"])
        loan = self.lend(client, admin, member, book, self.past()).json()
        client.put(f"/api/loans/{loan['id']}/return", headers=admin["headers"])

        res = client.get(
            "/api/loans",
            params={"overdue_only": True, "active_only": False},
            headers=admin["headers"],
        )

        assert res.json()["total"] == 0


class TestTheNestedBook:
    """`LoanOut.book` is a `BookOut`, and it was built without its context.

    A bare `model_validate` filled the two fields that are computed per
    request, `my_status` and `active_loan`, with their defaults, so every book
    on the loans page reported itself unread and not lent out, on a page whose
    entire subject is books that are lent out.
    """

    def test_the_reader_s_own_status_is_reported(
        self, client, admin, member, make_book
    ):
        book = make_book(admin["headers"], title="Dune")
        client.put(
            f"/api/books/{book['id']}/status",
            json={"status": "read"},
            headers=admin["headers"],
        )
        client.post(
            "/api/loans",
            json={"book_id": book["id"], "loaned_to_user_id": member["user"]["id"]},
            headers=admin["headers"],
        )

        [loan] = client.get("/api/loans", headers=admin["headers"]).json()["items"]

        assert loan["book"]["my_status"] == "read"

    def test_the_book_knows_it_is_lent_out(self, client, admin, member, make_book):
        book = make_book(admin["headers"])
        client.post(
            "/api/loans",
            json={"book_id": book["id"], "loaned_to_user_id": member["user"]["id"]},
            headers=admin["headers"],
        )

        [loan] = client.get("/api/loans", headers=admin["headers"]).json()["items"]

        assert loan["book"]["active_loan"] is not None

    def test_a_page_of_loans_costs_a_bounded_number_of_queries(
        self, client, admin, member, make_book
    ):
        """It was 53 statements for 25 loans: the N+1 the docs say was fixed."""
        from sqlalchemy import event

        from database import engine

        for index in range(10):
            book = make_book(admin["headers"], title=f"Book {index}")
            client.post(
                "/api/loans",
                json={"book_id": book["id"], "loaned_to_user_id": member["user"]["id"]},
                headers=admin["headers"],
            )

        statements: list[str] = []

        def record(conn, cursor, statement, *rest):
            statements.append(statement)

        event.listen(engine, "before_cursor_execute", record)
        try:
            client.get("/api/loans", headers=admin["headers"])
        finally:
            event.remove(engine, "before_cursor_execute", record)

        selects = [s for s in statements if s.lstrip().upper().startswith("SELECT")]
        # Constant in the number of loans, not linear: the count, the page, the
        # tag load, the two per-request book queries, and the caller's account.
        # Nine rather than eight since serialisation.books_to_out repopulates
        # the tag collection for the whole page, which replaced one lazy load
        # per book with one query for all of them.
        assert len(selects) <= 9, f"{len(selects)} selects for 10 loans"


class TestOneOpenLoanPerBook:
    """The application enforces this in three places. The database enforces it
    once, so a fourth place cannot get it wrong."""

    def test_the_database_refuses_a_second_open_loan(self, client, admin, member, make_book, db):
        book = make_book(admin["headers"])
        res = client.post(
            "/api/loans",
            json={"book_id": book["id"], "loaned_to_user_id": member["user"]["id"]},
            headers=admin["headers"],
        )
        assert res.status_code == 201, res.text

        db.add(
            Loan(
                book_id=book["id"],
                loaned_to_user_id=admin["user"]["id"],
                loaned_by_user_id=admin["user"]["id"],
            )
        )

        with pytest.raises(IntegrityError):
            db.commit()

    def test_a_returned_loan_does_not_block_the_next_one(
        self, client, admin, member, make_book
    ):
        """Partial, not plain: a book lent, returned and lent again is two rows
        with the same book_id, and that is the normal case."""
        book = make_book(admin["headers"])
        payload = {"book_id": book["id"], "loaned_to_user_id": member["user"]["id"]}
        loan = client.post("/api/loans", json=payload, headers=admin["headers"]).json()
        client.put(f"/api/loans/{loan['id']}/return", headers=admin["headers"])

        again = client.post("/api/loans", json=payload, headers=admin["headers"])

        assert again.status_code == 201


class TestLendingToSomeoneWithoutAnAccount:
    """The people most likely to keep a book are the ones who will never have
    an account here. `loaned_to_name` is a free-text borrower; exactly one of
    it and `loaned_to_user_id` is set, in the schema and in the database.
    """

    def test_a_name_is_accepted_instead_of_a_member(self, client, admin, book):
        res = client.post(
            "/api/loans",
            json={"book_id": book["id"], "loaned_to_name": "the neighbour"},
            headers=admin["headers"],
        )
        assert res.status_code == 201, res.text
        assert res.json()["loaned_to_name"] == "the neighbour"

    def test_the_member_fields_are_empty_for_an_external(self, client, admin, book):
        body = client.post(
            "/api/loans",
            json={"book_id": book["id"], "loaned_to_name": "the neighbour"},
            headers=admin["headers"],
        ).json()
        assert body["loaned_to"] is None
        assert body["loaned_to_user_id"] is None

    def test_naming_both_is_422(self, client, admin, member, book):
        res = client.post(
            "/api/loans",
            json={
                "book_id": book["id"],
                "loaned_to_user_id": member["user"]["id"],
                "loaned_to_name": "the neighbour",
            },
            headers=admin["headers"],
        )
        assert res.status_code == 422

    def test_naming_neither_is_422(self, client, admin, book):
        res = client.post(
            "/api/loans", json={"book_id": book["id"]}, headers=admin["headers"]
        )
        assert res.status_code == 422

    def test_a_whitespace_name_is_422(self, client, admin, book):
        """It satisfies IS NOT NULL and identifies nobody."""
        res = client.post(
            "/api/loans",
            json={"book_id": book["id"], "loaned_to_name": "   "},
            headers=admin["headers"],
        )
        assert res.status_code == 422

    def test_a_name_is_trimmed(self, client, admin, book):
        body = client.post(
            "/api/loans",
            json={"book_id": book["id"], "loaned_to_name": "  Ada  "},
            headers=admin["headers"],
        ).json()
        assert body["loaned_to_name"] == "Ada"

    def test_an_overlong_name_is_422(self, client, admin, book):
        res = client.post(
            "/api/loans",
            json={"book_id": book["id"], "loaned_to_name": "x" * 121},
            headers=admin["headers"],
        )
        assert res.status_code == 422

    def test_it_still_counts_as_the_book_being_out(self, client, admin, book):
        client.post(
            "/api/loans",
            json={"book_id": book["id"], "loaned_to_name": "the neighbour"},
            headers=admin["headers"],
        )
        fetched = client.get(f"/api/books/{book['id']}", headers=admin["headers"]).json()
        assert fetched["active_loan"]["loaned_to_name"] == "the neighbour"

    def test_lending_it_again_is_still_409(self, client, admin, member, book):
        client.post(
            "/api/loans",
            json={"book_id": book["id"], "loaned_to_name": "the neighbour"},
            headers=admin["headers"],
        )
        res = client.post(
            "/api/loans",
            json={"book_id": book["id"], "loaned_to_user_id": member["user"]["id"]},
            headers=admin["headers"],
        )
        assert res.status_code == 409

    def test_it_can_be_returned(self, client, admin, book):
        loan_id = client.post(
            "/api/loans",
            json={"book_id": book["id"], "loaned_to_name": "the neighbour"},
            headers=admin["headers"],
        ).json()["id"]

        res = client.put(f"/api/loans/{loan_id}/return", headers=admin["headers"])
        assert res.status_code == 200
        assert res.json()["returned_at"] is not None

    def test_it_appears_in_the_loans_list(self, client, admin, book):
        client.post(
            "/api/loans",
            json={"book_id": book["id"], "loaned_to_name": "the neighbour"},
            headers=admin["headers"],
        )
        rows = items(client.get("/api/loans", headers=admin["headers"]))
        assert [row["loaned_to_name"] for row in rows] == ["the neighbour"]

    def test_an_external_loan_of_an_invisible_book_stays_hidden(
        self, client, admin, member, make_book
    ):
        """The borrower being external changes nothing about the privacy rule."""
        private = make_book(admin["headers"], title="A diary", is_private=True)
        client.post(
            "/api/loans",
            json={"book_id": private["id"], "loaned_to_name": "the neighbour"},
            headers=admin["headers"],
        )
        assert items(client.get("/api/loans", headers=member["headers"])) == []
