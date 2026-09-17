"""Tests for backend/lending.py, the loan clock.

Three functions and one property between them: the Python rule and the SQL
rule for "overdue" must agree, because they are read on the same screen. The
badge on a loans row comes from `lending.is_overdue` and the rows on the
overdue page come from `notifications.overdue_clauses`, so a disagreement is
a page listing a loan whose own badge says it is fine.
"""

import ast
from datetime import UTC, datetime, timedelta

import pytest

import lending
import notifications
from database import Base
from models import Book, Loan
from tests.test_house_rules import _source_modules


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


def _book_with_a_loan(
    db,
    owner_id: int,
    *,
    title: str,
    private: bool = False,
    due: datetime | None = None,
    returned: datetime | None = None,
    borrower_id: int | None = None,
) -> Loan:
    """A Book on the shelf and one Loan over it, committed."""
    book = Book(title=title, is_private=private, added_by_user_id=owner_id)
    db.add(book)
    db.flush()
    row = Loan(
        book_id=book.id,
        loaned_to_user_id=borrower_id,
        loaned_to_name=None if borrower_id else "Kim",
        loaned_by_user_id=owner_id,
        loaned_at=now() - timedelta(days=10),
        due_at=due,
        returned_at=returned,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def _statements_of(run) -> list[str]:
    """Every statement one call issues, so "one statement" is measured."""
    from sqlalchemy import event

    from database import engine

    seen: list[str] = []

    def record(conn, cursor, statement, *rest) -> None:
        seen.append(statement)

    # The listener is removed by the same object it was added with. A lambda
    # here and `seen.append` there removes nothing, and the leak is silent:
    # every later test in the worker records into a list nobody reads.
    event.listen(engine, "before_cursor_execute", record)
    try:
        run()
    finally:
        event.remove(engine, "before_cursor_execute", record)
    return seen


class TestTheAudienceIsChosenByAConstructor:
    """Three constructors, three audiences, and the difference between two of
    them is the whole reason there are three.

    `seen_by` is the Shelf, which admits the viewer's **own** private Books.
    `for_a_channel` has no viewer at all and admits no private Book from
    anybody. A door with only the first makes `Loans.seen_by(db, <an admin>)`
    the obvious way to build a digest, and that posts the admin's private
    titles to whatever the channel is.
    """

    def test_a_member_reads_a_loan_over_a_public_book_somebody_else_added(
        self, db, admin, member
    ):
        _book_with_a_loan(db, admin["user"]["id"], title="Dune")

        rows, total = lending.Loans.seen_by(db, member["user"]["id"]).page(0, 10)

        assert total == 1
        assert [row.book.title for row in rows] == ["Dune"]

    def test_a_member_does_not_read_a_loan_over_somebody_elses_private_book(
        self, db, admin, member
    ):
        _book_with_a_loan(db, admin["user"]["id"], title="Secret", private=True)

        _, total = lending.Loans.seen_by(db, member["user"]["id"]).page(0, 10)

        assert total == 0

    def test_a_member_reads_a_loan_over_their_own_private_book(self, db, admin):
        _book_with_a_loan(db, admin["user"]["id"], title="Secret", private=True)

        _, total = lending.Loans.seen_by(db, admin["user"]["id"]).page(0, 10)

        assert total == 1

    def test_a_channel_is_told_about_a_public_book(self, db, admin):
        _book_with_a_loan(db, admin["user"]["id"], title="Dune")

        rows, _ = lending.Loans.for_a_channel(db).page(0, 10)

        assert [row.book.title for row in rows] == ["Dune"]

    def test_a_channel_is_not_told_about_a_loan_over_a_trashed_book(self, db, admin):
        """The clause this constructor was rewritten to inherit.

        It was `Book.is_private.is_(False)` on a bare query, which answered
        loans over Books in the trash, and was safe only because every caller
        chained `.overdue(now)` and picked `deleted_at` up from there. Measured
        by both critic seats on 2026-09-17: with the old body in place this
        total is 1, and reverting it moved **no** behaviour test, only two
        source reading guards. That is what this arm is for.
        """
        book = Book(
            title="Gone",
            is_private=False,
            added_by_user_id=admin["user"]["id"],
            deleted_at=now(),
        )
        db.add(book)
        db.flush()
        db.add(
            Loan(
                book_id=book.id,
                loaned_to_name="Kim",
                loaned_by_user_id=admin["user"]["id"],
                loaned_at=now() - timedelta(days=10),
            )
        )
        db.commit()

        _, total = lending.Loans.for_a_channel(db).page(0, 10)

        assert total == 0

    def test_a_channel_is_not_told_about_the_private_book_of_the_member_who_added_it(
        self, db, admin
    ):
        """The one the second constructor exists for. `seen_by` answers this
        loan for that same member, because it is their own Book; a channel has
        no member, so `is_private IS false` is the whole predicate."""
        _book_with_a_loan(db, admin["user"]["id"], title="Secret", private=True)

        _, channel_total = lending.Loans.for_a_channel(db).page(0, 10)
        _, viewer_total = lending.Loans.seen_by(db, admin["user"]["id"]).page(0, 10)

        assert (channel_total, viewer_total) == (0, 1)


class TestWhatOpenMeans:
    def test_an_unreturned_loan_is_open(self, db, admin):
        _book_with_a_loan(db, admin["user"]["id"], title="Out")

        _, total = lending.Loans.seen_by(db, admin["user"]["id"]).open().page(0, 10)

        assert total == 1

    def test_a_returned_loan_is_not(self, db, admin):
        _book_with_a_loan(db, admin["user"]["id"], title="Back", returned=now())

        scope = lending.Loans.seen_by(db, admin["user"]["id"])
        _, open_total = scope.open().page(0, 10)
        _, every_total = scope.page(0, 10)

        assert (open_total, every_total) == (0, 1)

    def test_the_python_form_answers_the_same_question(self, db, admin):
        """`is_open` is what the callers holding rows read, and a second idea of
        what open means is how a merge and a query come to disagree."""
        out = _book_with_a_loan(db, admin["user"]["id"], title="Out")
        back = _book_with_a_loan(db, admin["user"]["id"], title="Back", returned=now())

        assert (lending.is_open(out), lending.is_open(back)) == (True, False)

    def test_narrowing_does_not_mutate_the_scope_it_narrowed(self, db, admin):
        """Immutable, like the Shelf: a half built scope handed to two callers
        cannot be narrowed by one of them under the other."""
        _book_with_a_loan(db, admin["user"]["id"], title="Back", returned=now())
        scope = lending.Loans.seen_by(db, admin["user"]["id"])

        scope.open()

        _, total = scope.page(0, 10)
        assert total == 1


class TestTheOpenLoanOnAPageOfBooks:
    """`open_on` is plural because its caller is a page.

    `serialisation.books_to_out` needs the open loan for every Book on a
    listing, and a singular door turns that into one SELECT per row, which is
    the N+1 that function exists to prevent.
    """

    def test_it_answers_one_loan_per_book(self, db, admin):
        first = _book_with_a_loan(db, admin["user"]["id"], title="One")
        second = _book_with_a_loan(db, admin["user"]["id"], title="Two")

        found = lending.Loans.open_on(db, [first.book_id, second.book_id])

        assert found == {first.book_id: first, second.book_id: second}

    def test_a_returned_loan_is_not_on_the_page(self, db, admin):
        back = _book_with_a_loan(db, admin["user"]["id"], title="Back", returned=now())

        assert lending.Loans.open_on(db, [back.book_id]) == {}

    def test_a_page_of_books_costs_one_statement(self, db, admin):
        ids = [
            _book_with_a_loan(db, admin["user"]["id"], title=f"Book {index}").book_id
            for index in range(5)
        ]

        statements = _statements_of(lambda: lending.Loans.open_on(db, ids))

        assert len(statements) == 1, statements

    def test_an_empty_page_costs_none(self, db):
        """The guard three call sites would otherwise each write as
        `if book_ids:`, and the reason `Reading.of` has the same one."""
        assert _statements_of(lambda: lending.Loans.open_on(db, [])) == []


class TestClosingALoan:
    def test_it_stamps_the_clock_it_was_given(self, db, admin):
        row = _book_with_a_loan(db, admin["user"]["id"], title="Out")
        moment = now()

        lending.close(row, moment)

        assert row.returned_at == moment

    def test_the_stamp_is_naive_so_the_clock_arithmetic_works(self, db, admin):
        """An aware value read back before the session expires it makes
        `days_out` subtract a naive datetime from an aware one and raise. It
        reached the disk correctly once only because SQLAlchemy's SQLite
        formatter drops the offset."""
        row = _book_with_a_loan(db, admin["user"]["id"], title="Out")

        lending.close(row, now())

        assert row.returned_at is not None
        assert row.returned_at.tzinfo is None
        assert lending.days_out(row, now()) >= 0

    def test_closing_a_loan_that_already_came_back_is_refused(self, db, admin):
        row = _book_with_a_loan(db, admin["user"]["id"], title="Out")
        first = now() - timedelta(days=3)
        lending.close(row, first)

        with pytest.raises(lending.AlreadyClosed):
            lending.close(row, now())

        assert row.returned_at == first

    def test_the_refusal_is_above_the_index_and_not_instead_of_it(self, db, admin):
        """`uq_loans_one_open_per_book` is what holds "at most one open loan per
        Book" across three code paths that once disagreed, and a friendlier
        refusal in Python is exactly the thing somebody drops it for.

        **The partial clause is asserted, not only the name.** The same index
        without its `WHERE` is unique over `book_id` alone, which forbids a
        second loan of a book **ever**: a stricter index that passes a test
        reading the name, and a library that can lend each book once.
        """
        index = next(
            candidate
            for candidate in Base.metadata.tables["loans"].indexes
            if candidate.name == "uq_loans_one_open_per_book"
        )

        assert index.unique
        assert [column.name for column in index.columns] == ["book_id"]
        assert {
            str(clause) for clause in index.dialect_kwargs.values()
        } == {"returned_at IS NULL"}


class TestTheWayOutOfTheDoorHasTheCallersItClaims:
    """`as_query` is the named exit, and the counting is what stops it growing
    quietly.

    The same arrangement `shelf.whole_table_for_uniqueness` has, and for the
    same reason: "I need the query itself" is what somebody writes just before
    filtering it on `returned_at` again. Growing this list is allowed; growing
    it without saying so here is not.
    """

    def test_only_the_two_argued_callers_reach_past_the_door(self):
        found = [
            f"{name}:{node.lineno}"
            for name, source in _source_modules().items()
            for node in ast.walk(ast.parse(source))
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "as_query"
        ]

        # Call sites, not modules: both of these are in one file, so a set of
        # module names counts nothing and a third call added beside them would
        # pass green.
        assert len(found) == 2, found
        assert {name.split(":")[0] for name in found} == {"notifications.py"}, found


def _reaches_around_the_door(source: str) -> list[str]:
    """Every construction of a `Loans` and every read of its private query.

    Two spellings of one hole. `Loans.__init__` takes any query and applies no
    predicate, so `Loans(db.query(Loan))` is a fourth audience with no argument
    behind it; `Loans.seen_by(db, viewer)._query` is the same thing reached the
    other way, and neither is reported by any other rule over this module: a
    direct construction names no `Book`, no `returned_at` and no `as_query`.

    The callee is compared on its last dotted segment, so `Loans(...)`,
    `lending.Loans(...)` and any module alias are one case. A classmethod call
    ends in the method's name and is not reported.

    **`self._query` is not reported and every other receiver is.** A class
    reading its own private attribute is the owner doing so: `shelf.py` and
    `sru.py` each hold a `_query` of their own, and of the 16 times the
    attribute is named outside `tests/` they account for 9, of the 14 reads
    among those they account for 8, and **all 16 are through `self`**.
    Reaching into one from outside is the hole, and the receiver is what tells
    them apart, rather than a list of which classes have such an attribute.
    Counted 2026-09-17 by `ast` and by `grep -ro`, which agree on the 16.
    """
    found: list[str] = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Call) and ast.unparse(node.func).split(".")[-1] == "Loans":
            found.append(f"{node.lineno}: {ast.unparse(node)}")
        if (
            isinstance(node, ast.Attribute)
            and node.attr == "_query"
            and not (isinstance(node.value, ast.Name) and node.value.id == "self")
        ):
            found.append(f"{node.lineno}: {ast.unparse(node)}")
    return found


class TestOnlyTheDeskBuildsAScope:
    """A `Loans` is built by a constructor that chose an audience, or not at all.

    Held by "no other caller" and by nothing else until 2026-09-17, which is the
    `stated` rung. `Loans(db.query(Loan))` compiles, reads like every other
    construction in the tree, and answers every loan in the library with every
    private Book included, while `TestTheShelfIsTheOnlyWayIn`,
    `TestOnlyTheLendingDeskNamesReturnedAt` and the `as_query` count all stay
    green: measured on a three loan library, three titles against the two that
    member may see.

    **What this cannot see**: a scope built inside `lending.py`, which is where
    the constructors are and where a fourth would be added; a query reached
    through `vars(scope)` or `getattr(scope, "_query")`, which is the string
    shape every rule of this kind shares; and a `self._query` read, which is
    what makes the second arm cheap enough to have.
    """

    def test_nothing_outside_the_desk_builds_a_scope_or_opens_its_query(self):
        offences = [
            f"{name}:{site}"
            for name, source in _source_modules().items()
            if name != "lending.py"
            for site in _reaches_around_the_door(source)
        ]
        assert offences == [], (
            f"{offences} build a `Loans` or read its query directly. A scope "
            "carries the audience its constructor chose; one built from a bare "
            "query carries none, and `Loans.seen_by`, `Loans.for_a_channel` and "
            "`Loans.open_on` are the three audiences there are."
        )

    @pytest.mark.parametrize(
        "spelling",
        [
            "scope = Loans(db.query(Loan))\n",
            "scope = lending.Loans(db.query(Loan))\n",
            "rows = Loans.seen_by(db, viewer)._query.all()\n",
            "rows = scope._query.all()\n",
        ],
        ids=[
            "constructed",
            "constructed through the module",
            "the private query off a call",
            "the private query off a local",
        ],
    )
    def test_reaching_around_the_door_is_reported(self, spelling):
        """The diagonal, one mutation each. A sample carrying two spellings
        passes with either arm deleted and never says which arm caught it."""
        assert _reaches_around_the_door(spelling) != []

    def test_a_constructor_is_not_a_construction(self):
        """The other side. A rule that reported `Loans.seen_by(...)` would be
        one somebody deletes, since it would report every correct caller."""
        assert _reaches_around_the_door("scope = Loans.seen_by(db, viewer)\n") == []
        assert _reaches_around_the_door("rows = Loans.open_on(db, ids)\n") == []
        # The receiver arm, which is what keeps `shelf.py` and `sru.py` off the
        # list without either of them being named anywhere.
        assert _reaches_around_the_door("rows = self._query.all()\n") == []
