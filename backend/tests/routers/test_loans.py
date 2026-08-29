"""Tests for backend/routers/loans.py."""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.exc import IntegrityError

from database import engine
from models import Loan
from tests.conftest import _make_account
from tests.helpers import items


def selects_for(client, headers: dict, url: str) -> tuple[int, int]:
    """The SELECTs one request issues, and the `total` it answered with.

    The total comes back with the count so a cost met by answering with
    nothing cannot pass for a cheap page.
    """
    from sqlalchemy import event

    statements: list[str] = []

    def record(conn, cursor, statement, *rest):
        statements.append(statement)

    event.listen(engine, "before_cursor_execute", record)
    try:
        body = client.get(url, headers=headers).json()
    finally:
        event.remove(engine, "before_cursor_execute", record)
    selects = [row for row in statements if row.lstrip().upper().startswith("SELECT")]
    return len(selects), body["total"]


def lend_between_strangers(client, make_book, password_hash: str, index: int) -> dict:
    """One overdue loan whose adder, lender and borrower are three fresh accounts.

    **A cost test is only a cost test if every relationship on the page names a
    different row.** With one account adding, lending and borrowing everything,
    a dropped `joinedload` resolves out of the session's identity map and costs
    nothing at all. Measured 2026-08-29: on the fixtures these tests used to
    build, each of the four eager load options on `list_loans` and
    `list_overdue` could be deleted on its own with this whole file green, and
    one of the four was a wasted statement nobody had noticed. Three distinct
    parties per loan turn a missing option back into a lazy load per row, which
    is the only shape in which these tests assert anything.

    `_make_account` rather than the account fixtures, because a fixture is one
    account and this needs one per loan.
    """
    adder = _make_account(password_hash, f"adder{index}", is_admin=False)
    lender = _make_account(password_hash, f"lender{index}", is_admin=False)
    borrower = _make_account(password_hash, f"borrower{index}", is_admin=False)
    book = make_book(adder["headers"], title=f"Stranger {index}")
    res = client.post(
        "/api/loans",
        json={
            "book_id": book["id"],
            "loaned_to_user_id": borrower["user"]["id"],
            "due_at": (datetime.now(UTC) - timedelta(days=3))
            .replace(tzinfo=None)
            .isoformat(),
        },
        headers=lender["headers"],
    )
    assert res.status_code == 201, res.text
    return res.json()


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


class TestLendingABookMarkedNeverLent:
    """Refused once, then allowed. Neither silent nor forbidden: the reasoning
    is on `create_loan` and in docs/decisions.md."""

    @pytest.fixture
    def never_lent(self, client, admin, make_book) -> dict:
        book = make_book(admin["headers"], title="Signed first edition")
        res = client.patch(
            f"/api/books/{book['id']}",
            json={"lending": "never"},
            headers=admin["headers"],
        )
        assert res.status_code == 200, res.text
        return book

    def lend(self, client, admin, member, book, **extra):
        return client.post(
            "/api/loans",
            json={
                "book_id": book["id"],
                "loaned_to_user_id": member["user"]["id"],
                **extra,
            },
            headers=admin["headers"],
        )

    def test_the_first_attempt_is_refused(self, client, admin, member, never_lent):
        assert self.lend(client, admin, member, never_lent).status_code == 409

    def test_the_refusal_says_why_in_a_form_the_client_can_branch_on(
        self, client, admin, member, never_lent
    ):
        """A code beside the sentence, because this 409 and the already-lent
        one mean different things and only one of them can be acknowledged."""
        detail = self.lend(client, admin, member, never_lent).json()["detail"]
        assert detail["code"] == "not_lendable"

    def test_nothing_was_recorded_by_the_refusal(self, client, admin, member, never_lent):
        self.lend(client, admin, member, never_lent)
        fetched = client.get(
            f"/api/books/{never_lent['id']}", headers=admin["headers"]
        ).json()
        assert fetched["active_loan"] is None

    def test_acknowledging_it_lends_the_book(self, client, admin, member, never_lent):
        res = self.lend(
            client, admin, member, never_lent, acknowledge_not_lendable=True
        )
        assert res.status_code == 201
        assert res.json()["loaned_to"]["username"] == "member"

    def test_the_acknowledgement_is_not_remembered(
        self, client, admin, member, never_lent
    ):
        """It is about one request, not about the book. A library that lent
        this once has not changed its mind about lending it in general."""
        loan = self.lend(
            client, admin, member, never_lent, acknowledge_not_lendable=True
        ).json()
        client.put(f"/api/loans/{loan['id']}/return", headers=admin["headers"])

        assert self.lend(client, admin, member, never_lent).status_code == 409

    def test_the_book_still_says_it_is_never_lent(
        self, client, admin, member, never_lent
    ):
        self.lend(client, admin, member, never_lent, acknowledge_not_lendable=True)
        fetched = client.get(
            f"/api/books/{never_lent['id']}", headers=admin["headers"]
        ).json()
        assert fetched["lending"] == "never"

    def test_the_other_two_values_are_not_checked_at_all(
        self, client, admin, member, make_book
    ):
        """`in_use` is "come back later", which is a conversation rather than a
        rule, and `happy` is a yes."""
        for value in ("in_use", "happy"):
            book = make_book(admin["headers"], title=f"Book {value}")
            client.patch(
                f"/api/books/{book['id']}",
                json={"lending": value},
                headers=admin["headers"],
            )
            assert self.lend(client, admin, member, book).status_code == 201

    def test_an_unanswered_book_lends_without_a_prompt(
        self, client, admin, member, book
    ):
        assert self.lend(client, admin, member, book).status_code == 201

    def test_an_acknowledgement_does_not_override_the_already_lent_409(
        self, client, admin, member, never_lent
    ):
        """The two refusals are unrelated, and only one of them has a way past
        it. A book that is out is out."""
        self.lend(client, admin, member, never_lent, acknowledge_not_lendable=True)

        res = self.lend(
            client, admin, member, never_lent, acknowledge_not_lendable=True
        )

        assert res.status_code == 409
        assert res.json()["detail"] == "Book is already loaned out"


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

    Most library lending has no deadline, so the field is optional. It exists so
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

    def test_a_page_of_loans_costs_the_same_whatever_its_length(
        self, client, admin, make_book, _password_hash
    ):
        """It was 53 statements for 25 loans: the N+1 the docs say was fixed.

        **Two lengths, not a ceiling.** This asserted `<= 12` and a smaller
        count is a weaker inequality, so it went on passing with an option
        deleted and the count down at 11. What is claimed is that the cost is
        constant in the number of loans, which two measurements decide and one
        cannot.

        The equality on the number is exact for the same reason: a constant
        statement added **or removed** is then noticed rather than absorbed.
        Moving it is allowed when the change is deliberate and measured.

        What it pins, measured 2026-08-29 by deleting each option alone:
        `joinedload(Loan.book).joinedload(Book.added_by)`. Dropping the
        `.joinedload(Book.added_by)` link alone is +3 and +10, one member per
        loan; dropping the whole option takes the Book with it and is +6 and
        +20. The figures answer different mutations, so both are stated.
        `Loan.loaned_to` and `Loan.loaned_by` are free on an active page and
        are pinned by the returned page below instead.
        """
        for index in range(3):
            lend_between_strangers(client, make_book, _password_hash, index)
        short_cost, short_total = selects_for(client, admin["headers"], "/api/loans")

        for index in range(3, 10):
            lend_between_strangers(client, make_book, _password_hash, index)
        long_cost, long_total = selects_for(client, admin["headers"], "/api/loans")

        # The rows really were built, so a cost met by returning nothing cannot
        # pass, and the two runs really do differ in length.
        assert (short_total, long_total) == (3, 10)

        assert short_cost == long_cost, (
            f"{short_cost} selects for 3 loans and {long_cost} for 10: "
            "the cost moves with the page, which is the N+1 this exists to catch"
        )
        # What makes up the constant is stated once, in
        # `serialisation.books_to_out`, and deliberately not enumerated here:
        # this repository has restated that breakdown wrongly twice, both times
        # by editing prose rather than measuring.
        assert long_cost == 11, f"{long_cost} selects for 10 loans"

    def test_a_page_of_returned_loans_costs_the_same_whatever_its_length(
        self, client, admin, make_book, _password_hash
    ):
        """`active_only=false` is the page `Loan.loaned_to` and `Loan.loaned_by`
        are eager loaded for, and the only page on which they are observable.

        `books_to_out` fetches the page's **active** loans with both users
        joinedloaded, so on the default page those two options are satisfied by
        somebody else's query and deleting either changes nothing at all. A
        returned loan is in no such fetch. Measured 2026-08-29 on this page:
        deleting either alone costs +3 at three loans and +10 at ten.
        """
        for index in range(10):
            row = lend_between_strangers(client, make_book, _password_hash, index)
            client.put(f"/api/loans/{row['id']}/return", headers=admin["headers"])
            if index == 2:
                short_cost, short_total = selects_for(
                    client, admin["headers"], "/api/loans?active_only=false"
                )
        long_cost, long_total = selects_for(
            client, admin["headers"], "/api/loans?active_only=false"
        )

        assert (short_total, long_total) == (3, 10)

        assert short_cost == long_cost, (
            f"{short_cost} selects for 3 returned loans and {long_cost} for 10: "
            "the cost moves with the page, which is the N+1 this exists to catch"
        )
        assert long_cost == 11, f"{long_cost} selects for 10 returned loans"


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


class TestOverdueNotify:
    """`POST /api/loans/overdue/notify`: the digest, run by hand.

    The behaviour it drives is pinned in `tests/test_notifications.py`. What is
    here is the route: who may call it, and that "overdue" is not read as a
    loan id.
    """

    def test_a_member_may_not_run_it(self, client, member):
        assert client.post("/api/loans/overdue/notify", headers=member["headers"]).status_code == 403

    def test_it_needs_a_token(self, client):
        assert client.post("/api/loans/overdue/notify").status_code == 401

    def test_it_reports_that_nothing_is_configured(self, client, admin):
        body = client.post("/api/loans/overdue/notify", headers=admin["headers"]).json()
        assert body["sent"] is False
        assert body["loans"] == 0

    def test_the_literal_path_is_not_read_as_a_loan_id(self, client, admin):
        """The route-order rule. A 422 here would mean `overdue` had been
        matched against `{loan_id}`."""
        res = client.post("/api/loans/overdue/notify", headers=admin["headers"])
        assert res.status_code == 200


class TestMyOverdue:
    """`GET /api/loans/overdue/mine`: the in app reminder (#86).

    Who sees what is pinned in `tests/test_notifications.py`, on
    `overdue_for_viewer`. What is here is the route: that it needs a session and
    not an admin, that the toggle reaches it, and that `overdue` is not read as
    a loan id.
    """

    def past(self) -> str:
        return (datetime.now(UTC) - timedelta(days=3)).replace(tzinfo=None).isoformat()

    def lend(self, client, admin, member, book):
        return client.post(
            "/api/loans",
            json={
                "book_id": book["id"],
                "loaned_to_user_id": member["user"]["id"],
                "due_at": self.past(),
            },
            headers=admin["headers"],
        )

    def test_it_needs_a_token(self, client):
        assert client.get("/api/loans/overdue/mine").status_code == 401

    def test_a_member_may_read_their_own(self, client, admin, member, make_book):
        """Not admin only, and that is the point: it is the channel a household
        with no mailbox, no bot and no receiver still has."""
        book = make_book(admin["headers"])
        self.lend(client, admin, member, book)

        body = client.get("/api/loans/overdue/mine", headers=member["headers"]).json()

        assert body == {"enabled": True, "count": 1}

    def test_it_is_on_without_anybody_configuring_anything(self, client, member):
        """A fresh install, nothing set up. Every other channel answers nothing
        here, which is the complaint #86 was filed about."""
        body = client.get("/api/loans/overdue/mine", headers=member["headers"]).json()
        assert body["enabled"] is True

    def test_switching_it_off_reports_nothing_rather_than_a_count(
        self, client, admin, member, make_book
    ):
        """A household that turned the banner off should see no banner, and the
        page should not have to read the admin-only settings record to find
        that out."""
        book = make_book(admin["headers"])
        self.lend(client, admin, member, book)
        client.put(
            "/api/settings",
            json={"overdue_in_app_enabled": False},
            headers=admin["headers"],
        )

        body = client.get("/api/loans/overdue/mine", headers=member["headers"]).json()

        assert body == {"enabled": False, "count": 0}

    def test_the_literal_path_is_not_read_as_a_loan_id(self, client, member):
        """The route-order rule. A 422 here would mean `overdue` had been
        matched against a path parameter."""
        assert client.get("/api/loans/overdue/mine", headers=member["headers"]).status_code == 200


class TestListOverdue:
    """`GET /api/loans/overdue`: the list behind the banner (#102).

    Who may read which loan is pinned in `tests/test_notifications.py`, on
    `overdue_for_viewer`. What is here is the route: that it uses that rule
    rather than the loans list's wider one, that the in app switch reaches it,
    and that `overdue` is not read as a loan id.
    """

    def past(self) -> str:
        return (datetime.now(UTC) - timedelta(days=3)).replace(tzinfo=None).isoformat()

    def lend(self, client, headers, book, to_user_id):
        res = client.post(
            "/api/loans",
            json={
                "book_id": book["id"],
                "loaned_to_user_id": to_user_id,
                "due_at": self.past(),
            },
            headers=headers,
        )
        assert res.status_code == 201, res.text
        return res.json()

    def test_it_needs_a_token(self, client):
        assert client.get("/api/loans/overdue").status_code == 401

    def test_the_literal_path_is_not_read_as_a_loan_id(self, client, member):
        """The route-order rule. A 422 here would mean `overdue` had been
        matched against a path parameter."""
        assert client.get("/api/loans/overdue", headers=member["headers"]).status_code == 200

    def test_it_lists_the_loan_a_member_borrowed(self, client, admin, member, make_book):
        book = make_book(admin["headers"], title="Lent out")
        self.lend(client, admin["headers"], book, member["user"]["id"])

        body = client.get("/api/loans/overdue", headers=member["headers"]).json()

        assert body["total"] == 1
        assert [row["book"]["title"] for row in body["items"]] == ["Lent out"]
        assert body["items"][0]["is_overdue"] is True

    def test_a_loan_that_is_not_yet_due_is_absent(self, client, admin, member, make_book):
        book = make_book(admin["headers"], title="Still fine")
        soon = (datetime.now(UTC) + timedelta(days=3)).replace(tzinfo=None).isoformat()
        client.post(
            "/api/loans",
            json={
                "book_id": book["id"],
                "loaned_to_user_id": member["user"]["id"],
                "due_at": soon,
            },
            headers=admin["headers"],
        )

        body = client.get("/api/loans/overdue", headers=member["headers"]).json()

        assert body["total"] == 0

    def test_a_member_does_not_read_a_loan_they_are_not_party_to(
        self, client, admin, member, other_user, make_book
    ):
        """The whole reason this is a new endpoint rather than
        `overdue_only=true` on the loans list. That one is rooted at the Shelf
        and stops there, so it answers with this row; this one applies
        `sees_every_loan` and does not."""
        book = make_book(admin["headers"], title="Somebody else's business")
        self.lend(client, admin["headers"], book, other_user["user"]["id"])

        overdue = client.get("/api/loans/overdue", headers=member["headers"]).json()
        wider = client.get(
            "/api/loans", params={"overdue_only": True}, headers=member["headers"]
        ).json()

        assert overdue["total"] == 0
        assert wider["total"] == 1

    def test_an_admin_reads_every_overdue_loan_on_their_shelf(
        self, client, admin, member, other_user, make_book
    ):
        book = make_book(admin["headers"], title="Staff can see this")
        self.lend(client, admin["headers"], book, other_user["user"]["id"])
        # Lent by the admin, so `loaned_by` alone would have matched. Re-lend
        # through the member so neither party is the admin.
        second = make_book(member["headers"], title="Neither party is the admin")
        self.lend(client, member["headers"], second, other_user["user"]["id"])

        body = client.get("/api/loans/overdue", headers=admin["headers"]).json()

        assert sorted(row["book"]["title"] for row in body["items"]) == [
            "Neither party is the admin",
            "Staff can see this",
        ]

    def test_a_private_book_somebody_else_added_never_appears(
        self, client, admin, member, other_user, make_book
    ):
        """The Shelf, not the loan clauses, is what stops this. An admin is not
        a superuser over another member's private books anywhere else in this
        app and is not made one here."""
        book = make_book(member["headers"], title="Members only", is_private=True)
        self.lend(client, member["headers"], book, other_user["user"]["id"])

        body = client.get("/api/loans/overdue", headers=admin["headers"]).json()

        assert body["total"] == 0

    def test_switching_the_in_app_channel_off_empties_it(
        self, client, admin, member, make_book
    ):
        """The setting is spelled "show overdue loans in the app", and this page
        is what it shows."""
        book = make_book(admin["headers"], title="Hidden by the switch")
        self.lend(client, admin["headers"], book, member["user"]["id"])
        client.put(
            "/api/settings",
            json={"overdue_in_app_enabled": False},
            headers=admin["headers"],
        )

        body = client.get("/api/loans/overdue", headers=member["headers"]).json()

        assert body == {"items": [], "total": 0, "page": 1, "page_size": 50}

    def test_the_loans_list_is_not_affected_by_that_switch(
        self, client, admin, member, make_book
    ):
        """A loan list is not the reminder channel. Switching the channel off
        must not hide a household's loans from the loans page."""
        book = make_book(admin["headers"], title="Still on the loans page")
        self.lend(client, admin["headers"], book, member["user"]["id"])
        client.put(
            "/api/settings",
            json={"overdue_in_app_enabled": False},
            headers=admin["headers"],
        )

        body = client.get(
            "/api/loans", params={"overdue_only": True}, headers=member["headers"]
        ).json()

        assert body["total"] == 1

    def test_the_most_overdue_comes_first(self, client, admin, member, make_book):
        """`overdue_for_viewer` orders by `due_at`, and the page is read from
        the top: the book somebody has had longest is the one to chase."""
        older = make_book(admin["headers"], title="Older")
        newer = make_book(admin["headers"], title="Newer")
        for book, days in ((newer, 2), (older, 40)):
            client.post(
                "/api/loans",
                json={
                    "book_id": book["id"],
                    "loaned_to_user_id": member["user"]["id"],
                    "due_at": (datetime.now(UTC) - timedelta(days=days))
                    .replace(tzinfo=None)
                    .isoformat(),
                },
                headers=admin["headers"],
            )

        body = client.get("/api/loans/overdue", headers=member["headers"]).json()

        assert [row["book"]["title"] for row in body["items"]] == ["Older", "Newer"]

    def test_a_returned_loan_is_gone_however_late_it_was(
        self, client, admin, member, make_book
    ):
        book = make_book(admin["headers"], title="Came back")
        loan = self.lend(client, admin["headers"], book, member["user"]["id"])
        client.put(f"/api/loans/{loan['id']}/return", headers=member["headers"])

        body = client.get("/api/loans/overdue", headers=member["headers"]).json()

        assert body["total"] == 0

    def test_the_overdue_page_costs_the_same_whatever_its_length(
        self, client, admin, make_book, _password_hash
    ):
        """The eager loads were copied from `list_loans`; this is the test that
        makes them mean something.

        `overdue_for_viewer` deliberately carries no eager loading, because its
        other caller wants a count and no ORM objects. So every join this route
        needs it adds itself, and a route that adds them by copying is a route
        that can be edited back to an N+1 with nothing failing.

        **Measured twice rather than compared with a written down number.** A
        ceiling is the weaker half of the property: a smaller count is a weaker
        inequality, so a bound can stop guarding without ever failing, and this
        repository has recorded exactly that. What is actually being claimed is
        that the cost is **constant in the number of loans**, which two
        measurements at two lengths decide and one measurement cannot.

        **Every party is a different account, and that is what makes it a
        test.** This built its page with one admin adding, lending and
        borrowing everything, so a deleted `joinedload` resolved out of the
        session's identity map: measured 2026-08-29, all four options could be
        deleted one at a time with the file green, and one of them was a
        wasted statement. `lend_between_strangers` is where the reasoning sits.

        **What it pins**: `joinedload(Loan.book).joinedload(Book.added_by)`, at
        +3 and +10 with the `Book.added_by` link deleted, +6 and +20 with the
        whole option deleted. `Loan.loaned_to` and `Loan.loaned_by` cost
        nothing here whatever the page, because this route returns unreturned
        loans only and `books_to_out` fetches exactly those with both users
        joinedloaded. Nothing pins them and nothing can: see the comment beside
        them in the route.

        The number is exact rather than a ceiling so that a constant statement
        added **or removed** is noticed. It is one higher than `list_loans` and
        the one is named: this route reads `overdue_in_app_enabled` first.

        The viewer is an admin because the borrowers are strangers to each
        other: `sees_every_loan` is what puts them all on one page. Who may
        read which loan is pinned in `tests/test_notifications.py`.
        """
        for index in range(3):
            lend_between_strangers(client, make_book, _password_hash, index)
        short_cost, short_total = selects_for(
            client, admin["headers"], "/api/loans/overdue"
        )

        for index in range(3, 10):
            lend_between_strangers(client, make_book, _password_hash, index)
        long_cost, long_total = selects_for(
            client, admin["headers"], "/api/loans/overdue"
        )

        # The rows really were built, so a cost met by returning nothing cannot
        # pass, and the two runs really do differ in length.
        assert (short_total, long_total) == (3, 10)

        assert short_cost == long_cost, (
            f"{short_cost} selects for 3 loans and {long_cost} for 10: "
            "the cost moves with the page, which is the N+1 this exists to catch"
        )
        # 12 rather than `list_loans`'s 11: this route reads the in app
        # channel's switch before it queries anything.
        assert long_cost == 12, f"{long_cost} selects for 10 overdue loans"
