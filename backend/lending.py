"""The loan clock: what a Loan is at a given moment, in whole days.

Three facts, and each of them used to be computed at its point of use or not at
all. `is_overdue` was inline in `routers/loans._to_out`, `days_overdue` was
inline in `notifications.build_digest`, and "how long has this been out" was
nowhere, so the loans page showed a lending date and left the arithmetic to the
reader. They are here together because they are the same rule read three ways,
and two of them can disagree: a `days_overdue` with its own idea of what
overdue means would put a positive number on a row the badge above it calls
fine.

**Naive UTC throughout, because that is what the columns hold.** `loaned_at`,
`due_at` and `returned_at` are `DateTime` without a timezone, and every clock
in the backend reads `datetime.now(UTC).replace(tzinfo=None)` before comparing
against one. Nothing here normalises, deliberately: subtracting an aware
datetime from a naive one raises, which is the failure worth having, and the
alternative is a module that silently accepts a caller passing a clock in the
wrong frame.

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
"""

from datetime import datetime

from models import Loan


def is_overdue(loan: Loan, now: datetime) -> bool:
    """Whether this loan is worth chasing, which is not the same as "was late".

    A returned loan is never overdue, however late it came back. The field
    answers "chase this", and a book back on the shelf is not a book to chase.

    Computed rather than stored, because a stored flag would be wrong from the
    moment the deadline passed until something happened to write to the row,
    which for a forgotten loan is exactly never.

    **There are two other forms of this rule and both are reached from here.**
    `notifications.overdue_clauses` is the SQL form, and it is what
    `routers/loans.list_loans` filters `overdue_only` with rather than a third
    copy. The two must agree: `tests/test_lending.py` asserts that every loan
    that query selects is one this function calls overdue, and that no loan it
    rejects is, over the three of its four clauses that a set comparison can
    reach.
    """
    return (
        loan.returned_at is None
        and loan.due_at is not None
        and loan.due_at < now
    )


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
    end = loan.returned_at if loan.returned_at is not None else now
    return max((end - loan.loaned_at).days, 0)
