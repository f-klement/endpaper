"""The lending desk: which Loans a reader may see, when one closes, and what a
Loan is at a given moment.

## The door

An open Loan used to be `returned_at IS NULL`, written at nine sites in five
modules, and a caller who wanted one had to know three more things nothing
owned: that closing a Loan writes a **naive UTC** stamp, that a Loan query
roots at `Shelf.seen_by(db, viewer).select(Loan).join(...)`, and which six
relations to eager load or pay an N+1 per row.

`Loans` owns all four. `Shelf` is the same arrangement one table over, and the
names are deliberately its names: a scope is chosen by a constructor, so there
is no narrowing below that can be given a different audience than the object
was built for.

**Three constructors, because there are three loan audiences**, and a door with
two makes the third a workaround somebody writes in one line:

| constructor | audience |
|---|---|
| `seen_by` | one member: the Shelf, so their own private Books and nobody else's |
| `for_a_channel` | a destination with no account: `Shelf.seen_by_the_public`, no ownership arm at all |
| `open_on` | no audience at all: Books the caller has already authorised |

`for_a_channel` is not `seen_by` with an admin's id, and the difference is not
cosmetic: `visible_to` admits the viewer's **own** private Books, so a digest
running as an admin would post that admin's private titles to a Telegram
channel. The refusal is in the query rather than in a count downstream.

**Small by ADR 0008's depth instrument, and that is a fact about size rather than about the
door.** That ratio is statements behind each public name, and this module sits below
`dependencies.py`, the floor that document's central comparison is proved against, while
`Loans` is the arrangement `Shelf` is. It is named there as the module that stops the
comparison reading as a claim about shape. Nothing follows for the door: what a caller stops
knowing is the four facts above, which is `dependencies.py`'s own argument at a ratio of the
same kind. **The figure is deliberately not written here**, because nothing here would
recompute it and a number that is copied rather than derived is what that document exists to
refuse.

## What this module does not own

**The overdue predicate**, which is `notifications.overdue_clauses`: one
spelling for every caller, and it carries a `Book.deleted_at` clause the Python
form cannot. `.overdue(now)` **calls** it and does not absorb it.

**The ordering**, which is presentation and is the caller's argument. The two
routes that page loans differ by exactly that, and a `page()` choosing one
would silently converge them.

**Who is party to a loan.** `notifications.sees_every_loan` decides whether a
member reads every overdue loan or only their own, and that arm is written
beside it. A `.overdue(now)` that carried it by default would hand every member
the admin view of who is holding what.

**Naive UTC throughout, because that is what the columns hold.** `loaned_at`,
`due_at` and `returned_at` are `DateTime` without a timezone, and every clock
in the backend reads `datetime.now(UTC).replace(tzinfo=None)` before comparing
against one. Nothing here normalises, deliberately: subtracting an aware
datetime from a naive one raises, which is the failure worth having, and the
alternative is a module that silently accepts a caller passing a clock in the
wrong frame. `close()` is where that frame stopped being a convention each
writer kept.

**Whole days, floored, and that is the unit the UI asks for.** The story is
telling a week from a year at a glance, so the interesting difference is 7
against 365 and never 6.9 against 7.1.

`timedelta.days` floors toward negative infinity, so a span that has not
happened yet is **-1** rather than 0. Only one of the two counts guards against
that and the reason is the difference between them: `days_overdue` cannot be
handed a future span, because `is_overdue` gates it and that gate is what makes
the subtraction non negative. `days_out` can, because `loaned_at` is a stored
column that a restore or a MARC import can set to a date in the future, and
nothing gates it. So the clamp is where a value can actually arrive, and not
where a reader might expect symmetry.

**`import notifications`, never `from notifications import ...`.** The two
modules import each other: `build_digest` reads the clock facts here and
`.overdue()` reads the predicate there. A plain module import binds the module
object and every attribute is read at call time, so the cycle resolves whichever
side is imported first. A `from` form on **both** sides would not, and it fails
loudly at import rather than quietly at runtime.
`tests/test_house_rules.py::TestTheLendingCycleStaysPlain` pins it.
"""

from collections.abc import Collection
from datetime import datetime
from typing import Any, Final

from sqlalchemy import func
from sqlalchemy.orm import Query, Session, joinedload
from sqlalchemy.sql.elements import UnaryExpression

import notifications
from models import Book, Loan
from shelf import Shelf

#: Everything a rendered loan row reads, as one plan rather than a block
#: retyped per route.
#:
#: It was written out twice in `routers/loans.py`. The two option lists were
#: character identical and the chains around them were not: one carried an
#: `order_by` and the other did not, which is why the loading is one plan here
#: and the ordering is still the caller's argument.
#:
#: Every option is here because dropping it alone was measured, over pages of 3
#: and 10 loans with a distinct adder, lender and borrower per loan. **The
#: deltas, not the absolutes**: each is one lazy load per row, so each costs the
#: page's length.
#:
#:     .joinedload(Book.added_by)   +3 and +10 on any page
#:     joinedload(Loan.loaned_to)   +3 and +10 on any page
#:     joinedload(Loan.loaned_by)   +3 and +10 on any page
#:
#: **"On any page" was re-measured 2026-09-17 and the two critic seats took it
#: independently**: deleting `joinedload(Loan.loaned_to)` alone gives 10
#: statements at three loans and 17 at ten, against a baseline of 7 at both, on
#: the loans list **and** on the `active_only=false` page, and the same +3 and
#: +10 on the overdue page against its 9. Until 2026-09-16 the last two rows
#: read "on a page holding returned loans", because a second `books_to_out`
#: pass fetched every active loan with both users joinedloaded; that pass went
#: with `LoanOut.book`, and two test docstrings went on saying otherwise until
#: this measurement.
#:
#: **The first row is the chain link, not the whole option, and the two cost
#: different amounts.** Dropping `.joinedload(Book.added_by)` and keeping
#: `joinedload(Loan.book)` lazy loads one member per loan, which is +3 and +10.
#: Dropping the entire first option lazy loads the Book as well, two per loan,
#: which is +6 and +20. Both are real; they answer different questions.
#:
#: **The three collection options are the batching a second `books_to_out` pass
#: used to supply**, and that pass went with `LoanOut.book` narrowing to
#: `BookColumns`. Without them every collection on the nested Book lazy loads
#: one SELECT per Book: measured, 13 statements for 3 loans against 34 for 10.
#:
#: What pins all of it is the pair of exact statement counts in
#: `tests/routers/test_loans.py`, measured at two page lengths on both routes,
#: rather than this comment.
RENDERED: Final[tuple[Any, ...]] = (
    joinedload(Loan.book).joinedload(Book.added_by),
    joinedload(Loan.book).selectinload(Book.tags),
    joinedload(Loan.book).selectinload(Book.classifications),
    joinedload(Loan.book).selectinload(Book.identifiers),
    joinedload(Loan.loaned_to),
    joinedload(Loan.loaned_by),
)

#: The two people a loan names, for a caller that renders the badge and not the
#: row: who has the book, and who lent it.
#:
#: Not `RENDERED`, which loads the Book too. `open_on` is asked for the loan
#: **on** a Book the caller is already holding, so joining that Book back in
#: would fetch a row it already has.
_PARTIES: Final[tuple[Any, ...]] = (
    joinedload(Loan.loaned_to),
    joinedload(Loan.loaned_by),
)


class AlreadyClosed(ValueError):
    """A loan that has already come back, closed a second time.

    Raised rather than re-stamped. A second `returned_at` would move the date
    the book came back to whenever somebody pressed the button again, and
    `days_out` would then answer a different number for a row nothing changed.
    """


class Loans:
    """The loans one audience may see, narrowed but not yet read.

    Immutable: every narrowing returns a new `Loans`, so a half-built one
    cannot be handed to two callers and mutated by one of them.

    Cheap to build: it holds a query and reads nothing until a terminal method
    is called.
    """

    __slots__ = ("_query",)

    def __init__(self, query: Query[Loan]) -> None:
        # Private by convention and by the absence of any other caller: the
        # three classmethods below are the only ways in, and each of them is
        # what decides the audience. A caller that builds one of these directly
        # has already decided to write its own privacy rule.
        self._query = query

    # ── The three audiences ───────────────────────────────────────────────────

    @classmethod
    def seen_by(cls, db: Session, viewer_id: int) -> Loans:
        """The loans over Books this Member may see.

        **Rooted at the Shelf and joined outward to `loans`**, so the privacy
        predicate is on the query by construction. A loan of a Book the caller
        cannot see would otherwise disclose its title and who has it, straight
        through the loans list.

        **No party arm, deliberately.** This is every loan over a Book the
        viewer may see, housemates' included, which is what a household's loans
        list is. Narrowing to the loans a member is party to is
        `notifications.overdue_for_viewer`'s, because whether a member gets that
        narrowing is `sees_every_loan`'s decision and not a property of the
        Loan.
        """
        return cls(
            Shelf.seen_by(db, viewer_id).select(Loan).join(Loan, Loan.book_id == Book.id)
        )

    @classmethod
    def for_a_channel(cls, db: Session) -> Loans:
        """Every loan over a Book that is not private, for a reader with no account.

        **`Shelf.seen_by_the_public`, which is already exactly this audience**,
        rather than a second spelling of its predicate. That shelf is
        `deleted_at IS NULL AND is_private IS false` with **no ownership arm at
        all**, and its docstring carries the two shapes that were refused to get
        it: a sentinel viewer id, and a `visible_to` with a branch inside it.

        Written as `.filter(Book.is_private.is_(False))` on a bare
        `db.query(Loan)` until 2026-09-17, and two things were wrong with that.
        It dropped `deleted_at`, so the constructor on its own answered loans
        over trashed Books, and was safe only because every caller chained
        `.overdue(now)`, which carries that clause; a three audience door whose
        third audience is safe only in combination is not one. And it reached
        `books` through a join from a query rooted elsewhere, which cost
        `lending.py` an entry in `tests/test_shelf.py`'s `JOIN_CALLERS`, and
        that entry exempts every future join in this module rather than the one
        statement it was added for.

        **A strictly different predicate from `seen_by`, not a special case of
        it.** `visible_to(viewer)` admits the viewer's own private Books, so
        running a digest as an admin posts that admin's private titles to a
        Telegram channel or a webhook. There is no viewer to pass here at all:
        the audience is a destination, and this shelf fails safe in the other
        direction too, since a request routed through it by mistake sees less
        rather than more.

        Excluded **in the query**, so a counting mistake downstream cannot put
        a private title in a payload. What the channel is not being told is
        `notifications.count_private_overdue`, which counts without naming.
        """
        return cls(
            Shelf.seen_by_the_public(db).select(Loan).join(Loan, Loan.book_id == Book.id)
        )

    @classmethod
    def open_on(cls, db: Session, book_ids: Collection[int]) -> dict[int, Loan]:
        """The open loan on each of these Books, by book id, in one statement.

        **Plural, and that is the whole reason it is not `open_on(book)`.**
        `serialisation.books_to_out` needs the open loan for a page of Books,
        and a singular door turns the listing into the N+1 that function exists
        to prevent.

        **No viewer, because there is none to have.** Every caller has already
        resolved its Books through the Shelf or through `dependencies.py`, so
        the visibility question was answered before these ids existed. Taking
        ids rather than criteria is what stops this quietly becoming a way to
        read the table.

        **At most one row per Book, and the database is what says so.**
        `uq_loans_one_open_per_book` is a partial unique index over
        `(book_id) WHERE returned_at IS NULL`, so this mapping cannot drop a
        second open loan on the floor. `close` is a friendlier refusal above
        that index and never a replacement for it: three application code paths
        had to agree about this rule once and one of them was wrong, which is
        what `docs/decisions.md` records.

        **Zero statements for an empty set**, which is the guard three call
        sites would otherwise each write as `if book_ids:`.
        """
        ids = frozenset(book_ids)
        if not ids:
            return {}
        rows = (
            db.query(Loan)
            .options(*_PARTIES)
            .filter(Loan.book_id.in_(ids), Loan.returned_at.is_(None))
            .all()
        )
        return {row.book_id: row for row in rows}

    # ── Narrowing ─────────────────────────────────────────────────────────────

    def open(self) -> Loans:
        """The loans still out: the book has not come back.

        The one spelling of `returned_at IS NULL` a query gets. There is no
        `closed()` beside it because nothing asks for one: the loans list asks
        for every loan or for the open ones, and `active_only=false` is the
        absence of this call rather than its opposite.
        """
        return Loans(self._query.filter(Loan.returned_at.is_(None)))

    def overdue(self, now: datetime) -> Loans:
        """The loans worth chasing: open, past a deadline, over a live Book.

        `notifications.overdue_clauses`, **called** rather than copied. That
        function carries a `Book.deleted_at` clause the Python form in
        `is_overdue` cannot, and it counts its own callers; a second statement
        of the rule here is how a badge and a digest come to disagree about one
        loan.

        It implies `open()`: a returned loan is closed, whenever it came back.
        Calling both is allowed and costs a redundant clause, which is what
        `list_loans` does when it is asked for both.
        """
        return Loans(self._query.filter(*notifications.overdue_clauses(now)))

    # ── Reading ───────────────────────────────────────────────────────────────

    def with_id(self, loan_id: int) -> Loan | None:
        """One loan from this scope, or None.

        **None becomes 404, never 403**, for the reason `Shelf.first` states: a
        403 confirms the id exists, which is exactly what privacy withholds.
        A loan this audience may not see and a loan that never existed are the
        same answer here.
        """
        return self._query.filter(Loan.id == loan_id).first()

    def page(
        self, offset: int, limit: int, *order: UnaryExpression[Any]
    ) -> tuple[list[Loan], int]:
        """One page of this scope, and how many loans it was cut from.

        `offset` and `limit` rather than the `Paging` dependency, exactly as
        `Shelf.page` takes them: this module is read by `notifications.py`,
        which serves a ticker with no request behind it, and a domain module
        that imported FastAPI's dependency graph to name two integers would be
        the wrong direction.

        Counted before paging, and **from the query without the eager loading
        options**, so a `selectinload` does not issue its statement for a count
        that discards the rows. `order_by(None)` on the count because SQLite
        will not accept an ORDER BY over a bare COUNT.
        """
        total = self._query.with_entities(func.count(Loan.id)).order_by(None).scalar() or 0
        rows = (
            self._query.options(*RENDERED)
            .order_by(*order)
            .offset(offset)
            .limit(limit)
            .all()
        )
        return rows, total

    def as_query(self) -> Query[Loan]:
        """This scope as a query, for a clause this door does not own.

        **Two callers, both in `notifications.py`**, and both adding a clause
        about something other than whether the book is out:
        `overdue_for_viewer` adds the lender-or-borrower arm, and
        `due_for_reminder` adds the reminder interval. Neither is a property of
        a Loan: the first is a decision about who may read what, which
        `sees_every_loan` owns, and the second is delivery state.

        Named and counted rather than left as a bare attribute, the same
        arrangement `shelf.whole_table_for_uniqueness` has:
        `tests/test_lending.py::TestTheWayOutOfTheDoorHasTheCallersItClaims` is
        what makes a third caller a decision rather than an edit.

        It is not a hole in the privacy rule: the scope is already applied, and
        a caller can only narrow further. It **is** a way to write
        `returned_at` again, which is why the attribute rule in
        `tests/test_house_rules.py` reads every module and not only this one.
        """
        return self._query


def close(loan: Loan, now: datetime) -> None:
    """Record that this book came back, at a clock the caller read.

    **The naive UTC frame lives here.** `return_loan` wrote an aware
    `datetime.now(UTC)` into a `DateTime` with no timezone once: it reached the
    disk as the right instant only because SQLAlchemy's SQLite formatter drops
    the offset, and read back naive only because `expire_on_commit` refetched
    it. Anything touching the attribute before that refetch, which is what
    `days_out` does, subtracts a naive datetime from an aware one and raises.
    The whole suite stayed green over that line, so the frame needed an owner
    rather than a test of its effect.

    **`now` is the caller's, and that is not an economy.** A page is serialised
    against the instant its query was filtered with, and a loan closed here is
    stamped with the instant its response reports, so `days_out` on the row
    that comes back counts to the return rather than to a clock read a moment
    later.

    **Refuses a loan that has already come back**, rather than moving the date.
    That refusal is above `uq_loans_one_open_per_book` and never instead of it:
    the index is what makes "at most one open loan per Book" true across three
    code paths that once disagreed, and this only makes the second attempt say
    so in a sentence a person can read.

    Does not commit: the caller does, once. `_trash` closes a loan per Book in
    a bulk delete of 500, and a commit here made that 1001 statements.
    """
    if not is_open(loan):
        raise AlreadyClosed(
            f"loan {loan.id} came back at {loan.returned_at}, so closing it "
            "again would move the date the book was returned"
        )
    loan.returned_at = now


def is_open(loan: Loan) -> bool:
    """Whether this book is still out, read off a row already in hand.

    The Python form of `Loans.open()`, and it exists for the callers that have
    the rows rather than the query: the merge holds loans it has just repointed
    and cannot re-query, because the repointing is not flushed.

    **Nothing outside this module spells the column**, which is the rule
    `tests/test_house_rules.py::TestOnlyTheLendingDeskNamesReturnedAt` holds.
    Its blind spot is stated there and it is this shape: an `ast` pass over an
    attribute cannot tell this function's read from a filter somebody wrote by
    hand, so the rule is that the attribute is not named at all outside here.
    """
    return loan.returned_at is None


def is_overdue(loan: Loan, now: datetime) -> bool:
    """Whether this loan is worth chasing, which is not the same as "was late".

    A returned loan is never overdue, however late it came back. The field
    answers "chase this", and a book back on the shelf is not a book to chase.

    Computed rather than stored, because a stored flag would be wrong from the
    moment the deadline passed until something happened to write to the row,
    which for a forgotten loan is exactly never.

    **There are two other forms of this rule and both are reached from here.**
    `notifications.overdue_clauses` is the SQL form, and it is what
    `Loans.overdue` filters with rather than a third copy. The two must agree:
    `tests/test_lending.py` asserts that every loan that query selects is one
    this function calls overdue, and that no loan it rejects is, over the three
    of its four clauses that a set comparison can reach.
    """
    return is_open(loan) and loan.due_at is not None and loan.due_at < now


def days_overdue(loan: Loan, now: datetime) -> int:
    """How many whole days past its deadline, or 0 when there is no deadline.

    **0 rather than None, and `is_overdue` is what disambiguates it.** A loan
    that went overdue two hours ago is 0 days overdue and a loan with no
    `due_at` at all is also 0, which reads as ambiguous until you notice that
    the only caller that renders a number checks `is_overdue` first. A nullable
    field would have pushed that same check into every caller and into the
    generated client's types.

    `build_digest` has always answered 0 for a loan with no `due_at`, and the
    clause this adds cannot move its output: it is handed unreturned overdue
    loans only, so the returned arm is not reachable from there.

    **No clamp, deliberately, and `days_out` has one.** The gate above is what
    makes the subtraction non negative: `is_overdue` is `due_at < now`, so the
    span is positive whenever this line runs at all. A `max(..., 0)` here was
    unreachable code justified by a real trap belonging to the function below,
    and a test named for the clamp passed with the clamp deleted, because what
    it pinned was the gate.
    """
    if not is_overdue(loan, now) or loan.due_at is None:
        return 0
    return (now - loan.due_at).days


def days_out(loan: Loan, now: datetime) -> int:
    """How long the book has been away, in whole days.

    **It stops at the return, rather than running forever.** A loan that came
    back in three days is three days out and stays three days out. Measuring a
    closed loan against `now` would make every row in the history grow a day
    every day, which is what the value would mean if it were ever rendered.

    **No screen renders it on a closed row today.** `LoanRow` hides the line on
    a returned loan and shows the date it came back instead, so this arm is a
    property of the number rather than of anything on screen. Said plainly
    because the first version of this docstring described the loans list
    showing it, which was never true.

    Independent of `due_at`, which is the point of having it beside
    `days_overdue`: most lending here has no deadline at all, so an
    overdue-only answer leaves the common case with nothing to read.

    **The clamp is reachable and `days_overdue`'s was not.** Nothing gates this
    on `loaned_at` being in the past, and `loaned_at` is a stored column: a
    restore, a MARC import or a hand edit can put it in the future, and
    `timedelta.days` would then answer **-1** for a book that has not left yet.
    Pinned by `tests/test_lending.py`, which writes exactly that row.
    """
    # The column rather than `is_open`, which would be the same question asked
    # in a form mypy cannot see through: the narrowing here is what makes the
    # subtraction type check, and a call returning `bool` narrows nothing.
    end = loan.returned_at if loan.returned_at is not None else now
    return max((end - loan.loaned_at).days, 0)
