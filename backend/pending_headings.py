"""A harvest's headings, held on the Book until an admin confirms or discards them.

ADR 0006 lets a heading reach a Book only through a door a Member's choice
opened. Naming a repository once confirms no record, so a harvest raises its
record's headings here (`raise_on`), and an admin settles a Book's whole set at
once, as selecting a picker row confirms a whole record: `confirm` writes them
through `evidence.confirm_harvested_headings`, `discard` drops them.

**A settled row is kept, either way**, so the next harvest of the same record
does not raise it again. A heading the record newly carries is raised; one the
Book already carries as a `Classification` never is.

**Nothing here queries.** Every read is a relationship off a Book the caller
resolved: `dependencies.book_for_admin` for the routes, the harvest's own match
for `raise_on`. The privacy rule is applied before a Book reaches this module.
"""

import logging
from collections.abc import Iterable
from datetime import UTC, datetime

from pydantic import ValidationError
from sqlalchemy.orm import Session

import evidence
from catalogue import Heading
from classifications import bounded_headings
from logvalues import clipped
from models import Book, Harvest, PendingHeading
from schemas.classification import MAX_CLASSIFICATIONS_PER_BOOK, ClassificationIn

logger = logging.getLogger("endpaper.pending_headings")


def _key(scheme: str, number: str) -> tuple[str, str]:
    """The pair the unique index is on, as `classifications._key` spells it."""
    return str(scheme), number


def raise_on(book: Book, headings: Iterable[Heading], run: Harvest) -> int:
    """Raise the record's headings on `book` as suggestions, returning how many.

    Called only for a Book the record is: one `run` created, or one an earlier
    run of the same repository created from the same record. A Book matched by
    ISBN or by author and title is some other record's, and gets none.

    `bounded_headings` drops an entry the columns cannot hold, as it does for a
    file. A heading the Book carries, or that is already raised in any state,
    is skipped.

    **The room is the ceiling less what the Book carries and what waits**, so
    every suggestion raised fits at the confirm. Counting only the waiting rows
    would raise up to eight on a Book already at the ceiling, and the confirm
    would drop every one. A heading left out for lack of room is neither raised nor
    remembered, so a later run raises it once there is room. It also bounds the
    waiting set, so a repository changing its headings on every run cannot grow
    it between two settlements.

    **The room counts a key once**, as the union of the carried and the waiting
    keys: a member may add the very heading that waits, and the confirm then
    fills it in rather than taking a slot. Summing the two lengths would hold
    back a heading the record newly carries by one slot until a settlement.
    """
    carried = {_key(row.scheme, row.number) for row in book.classifications}
    waiting = {_key(row.scheme, row.number) for row in pending_on(book)}
    room = MAX_CLASSIFICATIONS_PER_BOOK - len(carried | waiting)
    held = carried | {_key(row.scheme, row.number) for row in book.pending_headings}
    raised = 0
    for heading in bounded_headings(headings):
        key = _key(heading.scheme, heading.number)
        if raised >= room:
            break
        if key in held:
            continue
        held.add(key)
        book.pending_headings.append(
            PendingHeading(
                harvest_id=run.id,
                scheme=key[0],
                number=heading.number,
                label=heading.label,
                kind=heading.kind,
            )
        )
        raised += 1
    return raised


def pending_on(book: Book) -> list[PendingHeading]:
    """The suggestions on `book` nobody has settled, in the order raised."""
    return [row for row in book.pending_headings if row.settled_at is None]


def confirm(book: Book, db: Session) -> list[str]:
    """Write `book`'s whole pending set as headings, returning the numbers changed.

    **Read back through `ClassificationIn`**, because `backup.restore` inserts
    these rows through Core, where no schema ran: a row the schema refuses is
    dropped and logged, as a catalogue's unusable entry is. `add_headings` then
    drops one whose scheme has gone and one past the ceiling. Every row is
    settled, written or dropped, so the set is gone from the Book either way.

    **A drop at the ceiling is reachable only after the raise.** `raise_on`
    leaves room for every row it raises, so the ceiling bites here only when a
    member or a merge gave the Book headings in between. The admin sees it in
    the Book the confirm answers, and `add_headings` logs it.
    """
    rows = pending_on(book)
    changed = evidence.confirm_harvested_headings(book, _as_headings(rows), db)
    _settle(rows)
    return changed


def discard(book: Book) -> int:
    """Settle `book`'s whole pending set without writing it, returning how many."""
    rows = pending_on(book)
    _settle(rows)
    return len(rows)


def _as_headings(rows: Iterable[PendingHeading]) -> list[ClassificationIn]:
    """`confirm`'s rows as the schema a heading writer takes, less any it refuses."""
    headings: list[ClassificationIn] = []
    for row in rows:
        try:
            headings.append(
                ClassificationIn(scheme=row.scheme, number=row.number, label=row.label, kind=row.kind)
            )
        except ValidationError:
            logger.info("Discarded an unusable pending heading: %s", clipped(row.number))
    return headings


def _settle(rows: Iterable[PendingHeading]) -> None:
    """Mark each row settled now, naive UTC as every stored time here is."""
    now = datetime.now(UTC).replace(tzinfo=None)
    for row in rows:
        row.settled_at = now
