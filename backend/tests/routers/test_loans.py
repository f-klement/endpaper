"""Tests for backend/routers/loans.py."""

import ast
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy.exc import IntegrityError

import lending
import notifications
import settings_store
from enums import SettingKey
from models import Book, Loan
from routers import loans as loans_module
from tests.conftest import _make_account
from tests.helpers import items, selects_for

#: The module tree the `ast` guards in this file read.
BACKEND = Path(__file__).resolve().parent.parent.parent


def library_mode(db, on: bool = True) -> None:
    """The switch itself, set through the store rather than the settings route.

    The route is admin only and carries its own confirmation, neither of which
    is what these tests are about: what is under test is what a **member**
    reads once the mode is on.
    """
    settings_store.set_value(db, SettingKey.LIBRARY_MODE, "true" if on else "false")


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
        # 13 rather than `list_loans`'s 11, and the two are named. This route
        # reads the in app channel's switch before it queries anything, and
        # `sees_every_loan` reads the library mode row. It was 12 until the
        # mode gained its clause; the number moved in the commit that moved
        # the code, which is the only way a stated cost stays a measurement.
        assert long_cost == 13, f"{long_cost} selects for 10 overdue loans"


class TestLibraryModeAndWhoReadsWhichLoan:
    """Library mode: a Member chases every loan, and never a private book.

    **The relaxation is on the loan's parties, not on the Book**, and the two
    halves of this class are why. `visible_to` has always admitted every non
    private Book, so the loans list was never the thing refusing anything: it
    is rooted at the Shelf, applies no lender-or-borrower arm, and has always
    answered with every loan over a book the reader may see. The refusal a
    volunteer actually hits is the overdue page, which narrows to the loans
    they lent or borrowed unless `sees_every_loan` says otherwise.

    So the mode changes the overdue page and leaves the loans list alone, and
    both are asserted here rather than one being left to be assumed.
    """

    def lend(self, client, headers, book, to_user_id, *, overdue=True) -> dict:
        due = datetime.now(UTC) + timedelta(days=-3 if overdue else 3)
        res = client.post(
            "/api/loans",
            json={
                "book_id": book["id"],
                "loaned_to_user_id": to_user_id,
                "due_at": due.replace(tzinfo=None).isoformat(),
            },
            headers=headers,
        )
        assert res.status_code == 201, res.text
        return res.json()

    def test_a_member_chases_a_loan_they_are_not_party_to(
        self, client, db, admin, member, other_user, make_book
    ):
        """User story 1, at the endpoint the banner links to."""
        library_mode(db)
        book = make_book(admin["headers"], title="Somebody else's business")
        self.lend(client, admin["headers"], book, other_user["user"]["id"])

        body = client.get("/api/loans/overdue", headers=member["headers"]).json()

        assert [row["book"]["title"] for row in body["items"]] == [
            "Somebody else's business"
        ]

    def test_with_the_mode_off_that_loan_is_still_refused(
        self, client, db, admin, member, other_user, make_book
    ):
        """The unchanged arm, asserted beside the changed one rather than
        trusted to the class two above: a relaxation that turned out to be
        unconditional would pass every other test in this file."""
        library_mode(db, False)
        book = make_book(admin["headers"], title="Somebody else's business")
        self.lend(client, admin["headers"], book, other_user["user"]["id"])

        body = client.get("/api/loans/overdue", headers=member["headers"]).json()

        assert body["total"] == 0

    def test_a_private_book_somebody_else_added_stays_out(
        self, client, db, admin, member, other_user, make_book
    ):
        """**The test the item exists to pass.** The Shelf is applied before
        the party arm and the mode does not touch it, so the relaxation cannot
        become a disclosure. Checked on both lists, because they are two
        queries and only one of them was widened."""
        library_mode(db)
        book = make_book(other_user["headers"], title="Members only", is_private=True)
        self.lend(client, other_user["headers"], book, admin["user"]["id"])

        overdue = client.get("/api/loans/overdue", headers=member["headers"]).json()
        listed = client.get("/api/loans", headers=member["headers"]).json()

        assert (overdue["total"], listed["total"]) == (0, 0)

    def test_a_member_still_reads_their_own_private_book(
        self, client, db, member, other_user, make_book
    ):
        """The other direction, and the reason the ticket's literal wording was
        not implemented. "Every Book that is not private" is a **subset** of
        what `visible_to` admits, so narrowing to it would have taken a
        member's own private books out of their own loan list."""
        library_mode(db)
        book = make_book(member["headers"], title="Mine and private", is_private=True)
        self.lend(client, member["headers"], book, other_user["user"]["id"])

        overdue = client.get("/api/loans/overdue", headers=member["headers"]).json()
        listed = client.get("/api/loans", headers=member["headers"]).json()

        assert [row["book"]["title"] for row in overdue["items"]] == ["Mine and private"]
        assert [row["book"]["title"] for row in listed["items"]] == ["Mine and private"]

    def test_the_loans_list_answers_the_same_set_in_either_mode(
        self, client, db, admin, member, other_user, make_book
    ):
        """The finding, pinned. Nothing about `list_loans` moved, and a later
        change that quietly made the mode narrow or widen it would be a screen
        disagreeing with itself rather than a failing test anywhere else."""
        book = make_book(admin["headers"], title="Housemates' business")
        self.lend(client, admin["headers"], book, other_user["user"]["id"])

        library_mode(db, False)
        off = items(client.get("/api/loans", headers=member["headers"]))
        library_mode(db, True)
        on = items(client.get("/api/loans", headers=member["headers"]))

        assert [row["id"] for row in off] == [row["id"] for row in on]
        assert len(on) == 1


class TestHowLongItHasBeenOut:
    """`days_out` and `days_overdue` on the serialised loan.

    Computed on the server, in `lending`, and read here through the API. The
    client is not asked to do date arithmetic, and the digest and the loans
    page cannot come to disagree about the same loan, because there is one
    function and both call it.
    """

    def lend_days_ago(self, db, admin, *, out=0, due=None, returned=None) -> Loan:
        """A loan positioned in time, written through the ORM.

        The API stamps `loaned_at` with the database's own clock and offers no
        way to backdate it, which is correct of the API and useless for
        measuring an elapsed span. So the row is written here.
        """
        moment = datetime.now(UTC).replace(tzinfo=None)
        book = Book(title="Dune", added_by_user_id=admin["user"]["id"])
        db.add(book)
        db.flush()
        loan = Loan(
            book_id=book.id,
            loaned_to_name="Kim",
            loaned_by_user_id=admin["user"]["id"],
            loaned_at=moment - timedelta(days=out),
            due_at=None if due is None else moment - timedelta(days=due),
            returned_at=None if returned is None else moment - timedelta(days=returned),
        )
        db.add(loan)
        db.commit()
        db.refresh(loan)
        return loan

    def only(self, client, headers, **params) -> dict:
        listed = items(client.get("/api/loans", params=params, headers=headers))
        assert len(listed) == 1, listed
        return listed[0]

    def test_an_open_loan_reports_the_days_since_it_left(self, client, db, admin):
        self.lend_days_ago(db, admin, out=9)
        assert self.only(client, admin["headers"])["days_out"] == 9

    def test_a_loan_with_no_deadline_still_reports_it(self, client, db, admin):
        """The common case here, and the reason `days_overdue` alone would not
        have answered the story: most lending has no due date at all."""
        self.lend_days_ago(db, admin, out=40, due=None)
        row = self.only(client, admin["headers"])
        assert (row["days_out"], row["due_at"], row["days_overdue"]) == (40, None, 0)

    def test_a_returned_loan_stops_counting_at_the_return(self, client, db, admin):
        """A closed row that grew a day every day would be a lie about a book
        that is back on the shelf."""
        self.lend_days_ago(db, admin, out=30, returned=27)
        row = self.only(client, admin["headers"], active_only="false")
        assert (row["days_out"], row["is_overdue"]) == (3, False)

    def test_an_overdue_loan_reports_how_far_past_its_date_it_is(
        self, client, db, admin
    ):
        self.lend_days_ago(db, admin, out=40, due=13)
        row = self.only(client, admin["headers"])
        assert (row["is_overdue"], row["days_overdue"], row["days_out"]) == (True, 13, 40)

    def test_it_is_the_number_the_digest_reports_for_the_same_loan(
        self, client, db, admin
    ):
        """The ticket's rule: one place, not two.

        Asserted against `notifications.build_digest`, which is the existing
        caller, rather than against a second subtraction written here. A copy
        of the arithmetic agrees with a mistake in the arithmetic.
        """
        loan = self.lend_days_ago(db, admin, out=40, due=13)
        moment = datetime.now(UTC).replace(tzinfo=None)

        served = self.only(client, admin["headers"])["days_overdue"]
        digested = notifications.build_digest([loan], moment)["loans"][0]["days_overdue"]

        assert served == digested == lending.days_overdue(loan, moment)

    def test_a_book_payload_carries_a_loan_summary_with_no_clock_facts(
        self, client, admin, book, member
    ):
        """`serialisation.loan_summary` fills the borrower and nothing dated,
        and it did so before this change: `due_at` and `is_overdue` were
        already absent there. So the two new fields read 0 on a book payload
        for the same reason, and this pins that they are consistently absent
        rather than sometimes wrong.

        Widening that summary is a separate change to a separate screen. What
        would be a defect is one of the four being filled and the others not,
        because a reader would then trust all four.
        """
        client.post(
            "/api/loans",
            json={"book_id": book["id"], "loaned_to_user_id": member["user"]["id"]},
            headers=admin["headers"],
        )

        active = client.get(f"/api/books/{book['id']}", headers=admin["headers"]).json()[
            "active_loan"
        ]

        assert (
            active["due_at"],
            active["is_overdue"],
            active["days_overdue"],
            active["days_out"],
        ) == (None, False, 0, 0)


class TestOneClockPerRequest:
    """`_now` is read once per request, and every row in the response is
    measured against that one instant.

    **Stated in `_now`'s docstring before anything checked it, and false on two
    routes of three.** `list_overdue` read a clock for its query and
    `_to_out_many` read a second for the rows, at a different instant, so a
    mutation back to a per row `lending.is_overdue(loan, _now())` was uncaught.
    Two loans lent in the same second can straddle a midnight between two such
    reads and come back a day apart.

    **Two maps, both asserted total against the router, because one was not
    enough.** The first version derived the route names from `router.routes`
    and then exercised them with seven hand written tests, which delivers "a
    route needs a figure" and not "no route goes unmeasured": measured, a route
    added to the router that reads the clock twice, with its figure added to
    `CLOCK_READS`, left this file green. A figure nothing issues a request for
    is a number in a table.

    So the requests are a map too, and the equality below is three way. That is
    the same defect C1 was raised for, in a guard written to fix C1: a
    docstring claiming the subject is covered while one syntax is.
    """

    #: Calls to `_now` per request, per route handler. Every route that
    #: serialises a loan reads the clock exactly once.
    #:
    #: `notify_overdue` is the one 0 and it is not an exemption: it hands the
    #: whole run to `notifications.run_digest`, which reads its own clock,
    #: because a digest timestamps a delivery rather than a response.
    CLOCK_READS = {
        "list_loans": 1,
        "create_loan": 1,
        "list_overdue": 1,
        "my_overdue": 1,
        "notify_overdue": 0,
        "return_loan": 1,
    }

    #: How to reach each route, so the figure above is measured rather than
    #: declared. A list per route, because one handler can be reached by more
    #: than one request shape and `list_loans` has two that take different
    #: paths through the clock: the plain listing, and `overdue_only`, which is
    #: the one that used to read a second instant for its predicate.
    REQUESTS = {
        "list_loans": [
            lambda ctx: ctx.client.get("/api/loans", headers=ctx.headers),
            lambda ctx: ctx.client.get(
                "/api/loans", params={"overdue_only": True}, headers=ctx.headers
            ),
        ],
        "create_loan": [
            lambda ctx: ctx.client.post(
                "/api/loans",
                json={"book_id": ctx.free_book_id, "loaned_to_user_id": ctx.member_id},
                headers=ctx.headers,
            )
        ],
        "list_overdue": [
            lambda ctx: ctx.client.get("/api/loans/overdue", headers=ctx.headers)
        ],
        "my_overdue": [
            lambda ctx: ctx.client.get("/api/loans/overdue/mine", headers=ctx.headers)
        ],
        "notify_overdue": [
            lambda ctx: ctx.client.post("/api/loans/overdue/notify", headers=ctx.headers)
        ],
        "return_loan": [
            lambda ctx: ctx.client.put(
                f"/api/loans/{ctx.loan_id}/return", headers=ctx.headers
            )
        ],
    }

    @pytest.fixture
    def clock(self, monkeypatch) -> list:
        """Every instant `_now` handed out, in order."""
        instants: list = []
        real = loans_module._now

        def counted():
            value = real()
            instants.append(value)
            return value

        monkeypatch.setattr(loans_module, "_now", counted)
        return instants

    @pytest.fixture
    def ctx(self, client, admin, member, make_book, loan):
        """Everything the request map needs to name a real row.

        `free_book_id` is a second book, because the one `loan` is on already
        has an open loan and a book is out with one person at a time: pointing
        `create_loan` at it answers 409 and reads no clock at all.
        """
        return SimpleNamespace(
            client=client,
            headers=admin["headers"],
            loan_id=loan["id"],
            member_id=member["user"]["id"],
            free_book_id=make_book(admin["headers"], title="Not yet lent")["id"],
        )

    def test_the_maps_cover_every_route_in_the_file(self):
        """Derived from the router in **both** directions, so a route added
        without a figure fails, and a figure with nothing issuing a request for
        it fails too. The second half is the one the first version lacked."""
        declared = {
            route.endpoint.__name__
            for route in loans_module.router.routes
            if hasattr(route, "endpoint")
        }
        assert declared == set(self.CLOCK_READS), (
            "every route in routers/loans.py needs a clock figure: "
            f"missing {sorted(declared - set(self.CLOCK_READS))}, "
            f"stale {sorted(set(self.CLOCK_READS) - declared)}"
        )
        assert declared == set(self.REQUESTS), (
            "every route needs a request that exercises it, or its figure is "
            f"a number nothing measured: missing {sorted(declared - set(self.REQUESTS))}, "
            f"stale {sorted(set(self.REQUESTS) - declared)}"
        )

    @pytest.mark.parametrize(
        ("route", "shape"),
        [
            (route, shape)
            for route, calls in REQUESTS.items()
            for shape in range(len(calls))
        ],
    )
    def test_a_request_reads_the_clock_its_figure_says(self, ctx, clock, route, shape):
        """One case per request shape, generated from the map rather than
        written out, so adding a shape adds a case."""
        response = self.REQUESTS[route][shape](ctx)

        assert response.status_code < 400, response.text
        assert len(clock) == self.CLOCK_READS[route], (
            f"{route} shape {shape} read the clock {len(clock)} times, "
            f"expected {self.CLOCK_READS[route]}: {clock}"
        )


class TestEveryClockInThisFileGoesThroughNow:
    """`_now` is the only place this module reads the wall clock.

    **The rule exists because one site wrote the wrong kind of value and
    nothing could have caught it.** `return_loan` set `returned_at` to an
    **aware** `datetime.now(UTC)` while the column and every comparison in this
    file are naive UTC. It reached the disk correctly only because SQLAlchemy's
    SQLite formatter drops the offset, and read back correctly only because
    `expire_on_commit` refetched the row before anything touched the attribute:
    right by ordering, not by construction. Reverting that line leaves the
    whole suite green, measured, so the fix needed a guard of its own rather
    than a test of its effect.

    **The first version caught one shape of five and said it caught the file.**
    It walked only `FunctionDef` and `AsyncFunctionDef` and matched only `now`,
    so a module level `_BOOT = datetime.now(UTC)` was invisible to it and
    `datetime.utcnow()` and `datetime.today()` both passed. Two of those three
    matter more than the others: a module level clock is read once per process
    and would freeze every comparison in the file at import time, and
    `datetime.today()` is naive **local** time, which is the wrong frame class
    this guard exists over arriving from the other side, and which mypy accepts
    because its type is right. Ruff's selected rules here do not include `DTZ`,
    so nothing else covers either.

    **`time.time()` is out of reach and is named rather than chased.** It
    returns a float, so mypy refuses it anywhere a `datetime` is wanted, which
    is every use this file has for a clock. A guard arm for it would be an arm
    against a shape the type checker already refuses.

    `ast` rather than a text search, so a docstring naming `datetime.now`
    cannot move the answer.
    """

    #: The three spellings that produce a `datetime` from the wall clock.
    #: `today` is here because it is naive **local** time: right type, wrong
    #: frame, and invisible to mypy.
    CLOCK_CALLS = {"now", "utcnow", "today"}

    #: Where a call sits when it is not inside a function at all.
    MODULE_LEVEL = "<module level>"

    def _readers(self, tree: ast.Module) -> set[str]:
        """Which functions read the wall clock, module level included.

        Recursive rather than `ast.walk`, because the answer is *which*
        function a call sits in and `walk` throws the nesting away. The first
        version worked around that by walking each function separately, which
        is what made every call outside one invisible.
        """
        found: set[str] = set()

        def visit(node: ast.AST, owner: str) -> None:
            for child in ast.iter_child_nodes(node):
                if (
                    isinstance(child, ast.Call)
                    and isinstance(child.func, ast.Attribute)
                    and child.func.attr in self.CLOCK_CALLS
                ):
                    found.add(owner)
                inner = (
                    child.name
                    if isinstance(child, ast.FunctionDef | ast.AsyncFunctionDef)
                    else owner
                )
                visit(child, inner)

        visit(tree, self.MODULE_LEVEL)
        return found

    def test_no_handler_reads_the_wall_clock_directly(self):
        tree = ast.parse((BACKEND / "routers" / "loans.py").read_text())
        readers = self._readers(tree)

        assert readers == {"_now"}, (
            "routers/loans.py reads the wall clock outside `_now`, in "
            f"{sorted(readers - {'_now'})}. One site wrote an aware datetime "
            "into a naive column that way, and the suite stayed green."
        )
