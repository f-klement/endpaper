"""What one look at a file may write to its reference, and which Books hold a file.

A `DigitalReference` row is one client's account of one file at one location.
**Every write to a row's fingerprint, its confirmation and its miss flag is
here**, and so are the reads of one Book's references, the per Book ceiling on
new locations, the refusal of a location another Book holds, and the three ways
a caller asks which Books hold a file. `routers/books.py` declares the routes,
resolves the Book, commits, turns `CeilingReached` and `HeldElsewhere` into a
409, and turns a `None` from `reference_on` into a 404.

**One rule for every look at a known location, whichever path it arrives
on**: the per reference report, a re-picked folder's sweep, and a merge's
repeat of the same file all ask `_settle`. A look fills what the row is
missing and never replaces a different fingerprint, and `root_confirmed` only
rises. `docs/decisions.md` records why. A miss is one rule on every path too:
`miss`.

**`backup.restore` is the one writer outside this module**, and deliberately:
it inserts an archive's rows verbatim through Core, and a restore is not a
look at anything.
"""

from collections import defaultdict
from datetime import datetime
from typing import Any, Protocol

from sqlalchemy import func, or_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from database import hold_book_ceilings
from models import Book, DigitalReference
from schemas.digital import (
    MAX_DIGITAL_REFERENCES_PER_BOOK,
    AskedFileIn,
    DigitalReferenceIn,
    HolderOut,
    HoldersOut,
    SweepIn,
    SweepOut,
)
from shelf import Shelf


class CeilingReached(Exception):
    """A new location would put its Book past `MAX_DIGITAL_REFERENCES_PER_BOOK`.

    Raised after the transaction is rolled back, so nothing of the refused
    report is left in the session.
    """


class HeldElsewhere(Exception):
    """A new location is one another Book the member can see already holds.

    Raised before anything is written. `book_id` is that Book, the lowest id
    where several hold it, so the client can put the file where it is.
    """

    def __init__(self, book_id: int) -> None:
        super().__init__(book_id)
        self.book_id = book_id


# ── One Book's references ─────────────────────────────────────────────────────
#
# Both take a `Book`, never an id, as `custom_fields.py` does: a `Book` in hand
# has been through `dependencies` or the Shelf, so the Book's own rule is
# already applied and the query adds no second one. The rule for a row under a
# Book is in `docs/data-model.md`, under the privacy rule.


def reference_on(db: Session, book: Book, reference_id: int) -> DigitalReference | None:
    """This Book's reference with this id, or `None` when no reference of this Book has it.

    The Book is in the query beside the id, so the id of another Book's
    reference finds nothing here.
    """
    return (
        db.query(DigitalReference)
        .filter(
            DigitalReference.id == reference_id,
            DigitalReference.book_id == book.id,
        )
        .first()
    )


def references_on(db: Session, book: Book) -> list[DigitalReference]:
    """Every reference on this Book, oldest first."""
    return (
        db.query(DigitalReference)
        .filter(DigitalReference.book_id == book.id)
        .order_by(DigitalReference.id)
        .all()
    )


# ── Writes ────────────────────────────────────────────────────────────────────


class _Fingerprint(Protocol):
    """What one look recorded of a file's bytes: a sighting, a report or a row."""

    @property
    def size_bytes(self) -> int | None: ...
    @property
    def file_modified_at(self) -> datetime | None: ...
    @property
    def partial_md5(self) -> str | None: ...


def _settle(reference: DigitalReference, look: _Fingerprint, *, root_confirmed: bool) -> None:
    """Write one look at a known location onto its row: the one rule every path asks.

    **The fingerprint is written only where every stored half is unset or the
    same as the one the look saw**, so a look fills what was missing and never
    changes what another look recorded. A root is only a folder name, and two
    Members' folders can share it and a path beneath it: without this, one
    Member's look replaces the other's size, time and digest with those of a
    different file, and the holder lookup stops finding the first file by its
    own digest. A look that agrees writes its halves whole, so a row with no
    fingerprint takes the look's entire one.

    **`root_confirmed` only rises.** True says a directory pick corroborated the
    path once; a later bare filename report of the same location is a weaker
    look, not evidence that the path stopped being one.
    """
    pairs = (
        (reference.size_bytes, look.size_bytes),
        (reference.file_modified_at, look.file_modified_at),
        (reference.partial_md5, look.partial_md5),
    )
    if all(stored is None or stored == seen for stored, seen in pairs):
        reference.size_bytes = look.size_bytes
        reference.file_modified_at = look.file_modified_at
        reference.partial_md5 = look.partial_md5
    reference.root_confirmed = bool(reference.root_confirmed) or root_confirmed


def report(
    db: Session, member_id: int, book_id: int, payload: DigitalReferenceIn
) -> DigitalReference:
    """Record one client's look at one location on this Book, uncommitted.

    The row at the location is settled by `_settle`, or created within the
    ceiling. The caller resolved `book_id` through `dependencies`, so it is a
    Book the member may write.

    Raises `HeldElsewhere` when the location is new on this Book and another
    Book the member can see holds it, and `CeilingReached` when the location is
    new and the Book is full.
    """
    at_this_location = db.query(DigitalReference).filter(
        DigitalReference.book_id == book_id,
        DigitalReference.root_label == payload.root_label,
        DigitalReference.relative_path == payload.relative_path,
    )
    existing = at_this_location.first()
    if existing is None:
        holder = _held_elsewhere(db, member_id, book_id, payload)
        if holder is not None:
            raise HeldElsewhere(holder)
        try:
            existing = DigitalReference(
                book_id=book_id,
                root_label=payload.root_label,
                relative_path=payload.relative_path,
                root_confirmed=False,
            )
            _add_within_the_ceiling(db, existing)
        except IntegrityError:
            # Another report of this location inserted it between the lookup
            # and this insert, and `uq_digital_references_location` refused
            # the second row. It is the same sighting, so it settles that
            # row; uncaught, the loser of the race answered 500.
            db.rollback()
            existing = at_this_location.first()
            if existing is None:
                raise

    _settle(existing, payload, root_confirmed=payload.root_confirmed)
    # The database's clock, not the client's, and not the client's word for when
    # it looked. This column records when this server was told.
    existing.confirmed_at = func.now()
    existing.missing_since = None
    return existing


def _held_elsewhere(
    db: Session, member_id: int, book_id: int, payload: DigitalReferenceIn
) -> int | None:
    """The lowest id Book other than this one, seen by the member, holding this location.

    **Through the Shelf, so a Book the member cannot see answers as no Book**
    and the report goes ahead: refusing on a hidden holder would confirm that
    somebody else privately holds that exact file, which the holder lookup
    already refuses to say. Trashed Books are off the Shelf too.

    By location alone. A digest held elsewhere is the same bytes at another
    path, which is a copy a Member may keep; a location belongs to one Book
    among those a Member can see.
    """
    holder: int | None = (
        Shelf.seen_by(db, member_id)
        .select(DigitalReference.book_id)
        .join(DigitalReference, DigitalReference.book_id == Book.id)
        .filter(
            DigitalReference.book_id != book_id,
            DigitalReference.root_label == payload.root_label,
            DigitalReference.relative_path == payload.relative_path,
        )
        .order_by(DigitalReference.book_id)
        .limit(1)
        .scalar()
    )
    return holder


def _add_within_the_ceiling(db: Session, reference: DigitalReference) -> None:
    """Add a new reference to its book, or raise `CeilingReached` past the ceiling.

    **The count is taken after the insert, inside the same transaction, and
    that order is the guard.** A count taken first and an insert after it is a
    gap two concurrent reports both pass, each reading the same count and each
    inserting, so a book lands past the ceiling. Counted after the insert, the
    row is already in the count, so the second of two racing writers sees the
    first. `database.hold_book_ceilings` is what makes that hold on Postgres,
    where two uncommitted inserts never see each other, and the merge takes the
    same lock for its keeper.

    Narrowed to this book, and that narrowing **is** the ceiling: without it the
    count is the whole library's and one member filling their own shelf refuses
    everybody else's next reference.
    """
    hold_book_ceilings(db, reference.book_id)
    db.add(reference)
    db.flush()
    held = (
        db.query(func.count(DigitalReference.id))
        .filter(DigitalReference.book_id == reference.book_id)
        .scalar()
    )
    if held > MAX_DIGITAL_REFERENCES_PER_BOOK:
        db.rollback()
        raise CeilingReached


def miss(reference: DigitalReference) -> bool:
    """Flag a reference as looked for and not found; whether that wrote anything.

    Once: a second miss leaves the first one's time, for the reason the
    per reference missing route gives.
    """
    if reference.missing_since is not None:
        return False
    reference.missing_since = func.now()
    return True


def forget(db: Session, reference: DigitalReference) -> None:
    """Delete a reference, because a Member said to. Uncommitted."""
    db.delete(reference)


def sweep(db: Session, member_id: int, payload: SweepIn) -> SweepOut:
    """Write what a re-picked folder found under its root, uncommitted.

    Each reference is resolved through `Shelf.seen_by` the member and
    `payload.root_label`, so a reference on a Book the member cannot see, or
    under another root, is not written and appears in neither list.
    """
    sightings = {sighting.reference_id: sighting for sighting in payload.seen}
    asked = set(sightings) | set(payload.missing)
    rows = (
        Shelf.seen_by(db, member_id)
        .select(DigitalReference)
        .join(DigitalReference, DigitalReference.book_id == Book.id)
        .filter(
            DigitalReference.id.in_(asked),
            DigitalReference.root_label == payload.root_label,
        )
        .all()
    )

    seen: list[int] = []
    missing: list[int] = []
    for reference in sorted(rows, key=lambda row: row.id):
        sighting = sightings.get(reference.id)
        if sighting is not None:
            # A sighting wins over a miss naming the same id: something looked
            # and found it, which is the only evidence against a miss. A pick
            # is a directory, so the path under it is corroborated.
            _settle(reference, sighting, root_confirmed=True)
            reference.confirmed_at = func.now()
            reference.missing_since = None
            seen.append(reference.id)
        else:
            miss(reference)
            missing.append(reference.id)
    return SweepOut(seen=seen, missing=missing)


def absorb(survivor: DigitalReference, losing: DigitalReference) -> None:
    """A merge's repeat of the same file gives the survivor what `_settle` admits.

    The loser's row is one more look at the location, so it is settled by the
    rule every look is: a survivor with no fingerprint takes the loser's whole
    one, size, time and digest together, and a survivor whose fingerprint
    differs keeps its own. Nothing regenerates a digest on the server: it is
    computed in a browser holding the file, so dropping the loser's would leave
    the file unrecognised by its bytes until somebody picks it again.
    """
    _settle(survivor, losing, root_confirmed=losing.root_confirmed)


# ── Which Books hold a file ───────────────────────────────────────────────────


def holders(db: Session, member_id: int, files: list[AskedFileIn]) -> list[HoldersOut]:
    """Which Books the member can see hold each file, one answer per file in order.

    A reference matching the file's location **or** its digest is a holder,
    and one matching both is one holder. One statement for the whole list,
    narrowed on the path alone: a path and a root pair in SQL only by row value
    comparisons whose spelling differs between the two engines, so the root is
    compared here on the rows it returns.
    """
    asked_paths = {file.relative_path for file in files if file.relative_path is not None}
    asked_digests = {file.partial_md5 for file in files if file.partial_md5 is not None}
    held = (
        Shelf.seen_by(db, member_id)
        .select(
            DigitalReference.id,
            DigitalReference.book_id,
            DigitalReference.root_label,
            DigitalReference.relative_path,
            DigitalReference.partial_md5,
            Book.format,
        )
        .join(DigitalReference, DigitalReference.book_id == Book.id)
        .filter(
            or_(
                DigitalReference.relative_path.in_(asked_paths),
                DigitalReference.partial_md5.in_(asked_digests),
            )
        )
        .all()
    )

    by_location: dict[tuple[str, str], list[Any]] = defaultdict(list)
    by_digest: dict[str, list[Any]] = defaultdict(list)
    for row in held:
        by_location[(row.root_label, row.relative_path)].append(row)
        if row.partial_md5 is not None:
            by_digest[row.partial_md5].append(row)

    answers: list[HoldersOut] = []
    for file in files:
        located = (
            by_location.get((file.root_label, file.relative_path), [])
            if file.root_label is not None and file.relative_path is not None
            else []
        )
        digested = by_digest.get(file.partial_md5, []) if file.partial_md5 else []
        at = {row.id for row in located}
        carrying = {row.id for row in digested}
        # A reference matching on both keys is one holder, not two.
        rows = sorted(
            {row.id: row for row in [*located, *digested]}.values(),
            key=lambda row: (row.book_id, row.id),
        )
        answers.append(
            HoldersOut(
                holders=[
                    HolderOut(
                        book_id=row.book_id,
                        reference_id=row.id,
                        format=row.format,
                        same_location=row.id in at,
                        same_partial_md5=row.id in carrying,
                    )
                    for row in rows
                ]
            )
        )
    return answers


def books_carrying(db: Session, member_id: int, digest: str, *, limit: int) -> set[int]:
    """The ids of up to `limit` Books the member can see that carry this digest
    on a reference.

    The batched `holders` question asked for one digest and answered by Book.
    A caller deciding whether exactly one Book holds the file asks for two.
    """
    return {
        book_id
        for (book_id,) in Shelf.seen_by(db, member_id)
        .select(DigitalReference.book_id)
        .join(DigitalReference, DigitalReference.book_id == Book.id)
        .filter(DigitalReference.partial_md5 == digest)
        .distinct()
        .limit(limit)
        .all()
    }


def carries(book: Book, digest: str) -> bool:
    """Whether this Book holds a file with this digest on one of its references.

    Read off the Book's own references, so the caller's resolution of the Book
    is the whole of the scope.
    """
    return any(reference.partial_md5 == digest for reference in book.digital_references)
