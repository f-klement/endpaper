"""Tests for backend/lending.py, the loan clock.

Three functions and one property between them: the Python rule and the SQL
rule for "overdue" must agree, because they are read on the same screen. The
badge on a loans row comes from `lending.is_overdue` and the rows on the
overdue page come from `notifications.overdue_clauses`, so a disagreement is
a page listing a loan whose own badge says it is fine.
"""

from datetime import UTC, datetime, timedelta

import pytest

import lending
import notifications
from models import Book, Loan


def now() -> datetime:
    """Naive UTC, which is what the three datetime columns hold."""
    return datetime.now(UTC).replace(tzinfo=None)


def loan(*, loaned=None, due=None, returned=None, book_id=1) -> Loan:
    """A Loan built in memory, never added to a session.

    These three functions read attributes and nothing else, so a row is not
    needed and a flush would only make the test slower and the failure less
    obvious.
    """
    return Loan(
        book_id=book_id,
        loaned_to_name="Kim",
        loaned_by_user_id=1,
        loaned_at=loaned if loaned is not None else now() - timedelta(days=1),
        due_at=due,
        returned_at=returned,
    )


class TestIsOverdue:
    def test_a_loan_past_its_date_is_overdue(self):
        moment = now()
        assert lending.is_overdue(loan(due=moment - timedelta(days=1)), moment) is True

    def test_a_loan_not_yet_due_is_not(self):
        moment = now()
        assert lending.is_overdue(loan(due=moment + timedelta(days=1)), moment) is False

    def test_a_loan_with_no_date_is_never_overdue(self):
        """Most lending here has no deadline, and a loan without one cannot be
        late for anything."""
        assert lending.is_overdue(loan(due=None), now()) is False

    def test_a_returned_loan_is_not_overdue_however_late_it_was(self):
        """The field answers "chase this", not "was this late"."""
        moment = now()
        late = loan(due=moment - timedelta(days=400), returned=moment)
        assert lending.is_overdue(late, moment) is False


class TestDaysOverdue:
    def test_it_counts_whole_days_past_the_date(self):
        moment = now()
        assert lending.days_overdue(loan(due=moment - timedelta(days=14)), moment) == 14

    def test_a_few_hours_late_is_zero_days(self):
        """0 and `is_overdue` true. The pair is what the badge reads, and the
        badge falls back to the date when this is 0."""
        moment = now()
        row = loan(due=moment - timedelta(hours=5))
        assert (lending.is_overdue(row, moment), lending.days_overdue(row, moment)) == (
            True,
            0,
        )

    def test_a_loan_that_is_not_overdue_is_zero(self):
        """**This pins the gate, not a clamp, and it was named for a clamp.**

        `days_overdue` returns 0 here because `is_overdue` is false, and it did
        so with the `max(..., 0)` it used to carry deleted: measured, that
        mutation was uncaught, which is what a clamp behind a gate that already
        excludes negative spans is. The clamp is gone and the reachable one is
        `days_out`'s, two classes below.
        """
        moment = now()
        assert lending.days_overdue(loan(due=moment + timedelta(hours=3)), moment) == 0

    def test_a_loan_with_no_date_is_zero(self):
        assert lending.days_overdue(loan(due=None), now()) == 0

    def test_a_returned_loan_is_zero_however_late_it_came_back(self):
        moment = now()
        late = loan(due=moment - timedelta(days=400), returned=moment)
        assert lending.days_overdue(late, moment) == 0


class TestDaysOut:
    def test_it_counts_whole_days_since_the_book_left(self):
        moment = now()
        assert lending.days_out(loan(loaned=moment - timedelta(days=9)), moment) == 9

    def test_it_needs_no_due_date(self):
        """The reason it exists beside `days_overdue`: most lending here has no
        deadline, so an overdue-only answer leaves the common case blank."""
        moment = now()
        assert lending.days_out(loan(loaned=moment - timedelta(days=9), due=None), moment) == 9

    def test_a_returned_loan_stops_counting_at_the_return(self):
        """A closed row that grew a day every day would make the loans history
        unreadable, and it would be a lie about a book that is back."""
        moment = now()
        row = loan(loaned=moment - timedelta(days=30), returned=moment - timedelta(days=27))
        assert lending.days_out(row, moment) == 3

    def test_a_loan_recorded_this_second_is_zero(self):
        moment = now()
        assert lending.days_out(loan(loaned=moment), moment) == 0

    def test_a_loan_dated_in_the_future_is_zero_rather_than_negative(self):
        """**The clamp that is reachable, and the one `days_overdue` is not.**

        Nothing gates this on `loaned_at` being in the past, and `loaned_at` is
        a stored column a restore, a MARC import or a hand edit can put ahead
        of the clock. `timedelta.days` floors toward negative infinity, so
        without the clamp this row reports **-1** days out for a book that has
        not left yet.
        """
        moment = now()
        assert lending.days_out(loan(loaned=moment + timedelta(hours=3)), moment) == 0


class TestTheSqlRuleAndThePythonRuleAgree:
    """`notifications.overdue_clauses` and `lending.is_overdue` are the same
    sentence in two languages, and only one of them can be read off a row in
    hand.

    Compared as **sets of loan ids**, not as counts: two rules can select the
    same number of different rows. The fixture deliberately holds one loan for
    each arm either rule branches on, so a rule that dropped a clause would
    change the set rather than only its size.

    `Book.deleted_at` is the one clause the Python form does not carry and
    cannot: it is a fact about the book, and `is_overdue` is handed a loan. The
    trashed book is in the fixture anyway, and it is the reason this test
    compares against the query restricted to books on the shelf rather than
    against the whole table.

    **Three of the four clauses are pinned and the fourth cannot be**, and that
    is a diagonal rather than a claim: each clause was deleted in turn against
    `288bf6b` and the failing test named, not a count taken.

    | clause deleted | verdict |
    |---|---|
    | `Loan.returned_at.is_(None)` | caught, `test_the_two_select_the_same_loans` |
    | `Loan.due_at < now` | caught, the same test |
    | `Book.deleted_at.is_(None)` | caught, that test **and** the trashed one below |
    | `Loan.due_at.isnot(None)` | **uncaught**, 17 passed |

    No fixture can catch the fourth. SQL's `NULL < :now` evaluates to NULL
    rather than to true, so `Loan.due_at < now` already excludes every row that
    clause was written to exclude. It is redundant in SQL and kept as the
    sentence a reader needs, which makes it documentation this test can read
    and not a predicate it can test.
    """

    @pytest.fixture
    def moment(self) -> datetime:
        return now()

    @pytest.fixture
    def loans(self, db, admin, moment) -> dict[str, Loan]:
        owner = admin["user"]["id"]
        rows: dict[str, Loan] = {}
        for name, private, deleted in (
            ("overdue", False, False),
            ("not yet due", False, False),
            ("no deadline", False, False),
            ("returned", False, False),
            ("trashed book", False, True),
        ):
            book = Book(
                title=name,
                is_private=private,
                added_by_user_id=owner,
                deleted_at=moment if deleted else None,
            )
            db.add(book)
            db.flush()
            due = {
                "overdue": moment - timedelta(days=2),
                "not yet due": moment + timedelta(days=2),
                "no deadline": None,
                "returned": moment - timedelta(days=2),
                "trashed book": moment - timedelta(days=2),
            }[name]
            row = Loan(
                book_id=book.id,
                loaned_to_name="Kim",
                loaned_by_user_id=owner,
                loaned_at=moment - timedelta(days=10),
                due_at=due,
                returned_at=moment if name == "returned" else None,
            )
            db.add(row)
            rows[name] = row
        db.commit()
        for row in rows.values():
            db.refresh(row)
        return rows

    def test_the_two_select_the_same_loans(self, db, loans, moment):
        selected = {
            row.id
            for row in db.query(Loan)
            .join(Book, Loan.book_id == Book.id)
            .filter(*notifications.overdue_clauses(moment))
        }
        judged = {
            row.id
            for name, row in loans.items()
            if name != "trashed book" and lending.is_overdue(row, moment)
        }

        assert selected == judged
        # The fixture really did exercise both answers, so a rule that selected
        # nothing at all cannot pass by agreeing with a rule that judged
        # nothing at all.
        assert selected == {loans["overdue"].id}

    def test_the_trashed_book_is_the_one_clause_only_the_query_has(
        self, db, loans, moment
    ):
        """Stated in `overdue_clauses`' docstring, and this is what makes the
        sentence checkable. The Python rule calls this loan overdue, because it
        is; the query refuses it, because the book is in the trash."""
        assert lending.is_overdue(loans["trashed book"], moment) is True
        selected = {
            row.id
            for row in db.query(Loan)
            .join(Book, Loan.book_id == Book.id)
            .filter(*notifications.overdue_clauses(moment))
        }
        assert loans["trashed book"].id not in selected


class TestTheDigestReadsTheSameFunction:
    """The ticket's rule: computed in one place, not a second time.

    Asserted through `build_digest` rather than against a copy of the
    arithmetic, because a copy agrees with a mistake.
    """

    def test_the_digest_entry_carries_the_shared_value(self, db, admin):
        moment = now()
        book = Book(title="Dune", added_by_user_id=admin["user"]["id"])
        db.add(book)
        db.flush()
        row = Loan(
            book_id=book.id,
            loaned_to_name="Kim",
            loaned_by_user_id=admin["user"]["id"],
            loaned_at=moment - timedelta(days=40),
            due_at=moment - timedelta(days=13),
        )
        db.add(row)
        db.commit()
        db.refresh(row)

        digest = notifications.build_digest([row], moment)

        assert digest["loans"][0]["days_overdue"] == lending.days_overdue(row, moment) == 13
