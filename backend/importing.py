"""Applying a parsed export to a Library: the half of importing that writes.

`csv_import.py` is the other half and is deliberately pure: `decode`,
`sniff_delimiter`, `build_mapping`, `parse` and the small matchers, no session
and no writes. It was extracted so it could be tested, and that was right.

What was left behind was everything the database knows about applying the
result, sitting in a route handler: the catalogue index, the matching, the
gap filling, the tag invention, the reading record and the review. **The pure
functions were extracted so they could be tested, and the failures that matter
were in the calling code left behind**, which is the same sentence
`authorship.py` was written under and the same shape.

So this module owns the application. `csv_import.py` is unchanged, still pure,
still the implementation underneath.

## The interface

    run = Import.for_member(db, member.id)
    result = run.apply(parsed, create_missing=False, apply_tags=False)

`for_member` mirrors `Shelf.seen_by` and `Authorship.seen_by`: an import reads
the catalogue as one Member sees it and writes only that Member's reading
records, so the viewer is fixed at construction rather than threaded through.

## What a caller must still know, because it cannot be moved here

**The handler stays `def`, never `async def`.** Everything below blocks:
SQLAlchemy has no async here. An `async` handler runs on the event loop, so a
running import stops the whole application answering. Measured on a 3000 row
file: `GET /api/books` went from 7ms to **14.4 seconds**, and exactly one such
request completed for the duration. FastAPI runs a `def` handler in a
threadpool instead. This module cannot enforce that, so it is said here and at
the handler.

## The rule that is not about performance

**A row whose ISBN belongs to a Book this Member cannot see is counted as
unmatched, and its title is never reported.** `recognition` answers it
`Hidden`. Creating it would raise on the unique index, and that raise is two
problems at once: it aborts the whole transaction, so a 5000 row import
silently writes nothing, and the 500 against 200 difference is a clean oracle
for "does a Book with this ISBN exist in this house", which is exactly what the
404-not-403 rule withholds. `skipped` counts it together with the rows that had
no title, because separating them out would be the oracle again by another
route.
"""

import logging
from collections.abc import Callable, Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, time
from typing import Any, Final, NewType

import annotated_types
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

import book_columns
import csv_import
import evidence
import marc
import recognition
import tags
from catalogue import Link, Record
from database import hold_book_ceilings
from enums import OwnershipStatus, ReadStatus
from errors import MetAnotherChange
from models import MAX_ONLINE_LINKS_PER_BOOK, Book, Note, OnlineLink
from reading import Reading, Records
from schemas import ImportResultOut
from schemas.book import BookCreate, admits_a_container
from shelf import Shelf

logger = logging.getLogger("endpaper.importing")

#: How many unmatched titles come back in the response, and separately how
#: many titles found in the trash and how many two Books answered.
#:
#: A 5000 book export with nothing matching would otherwise return a response
#: larger than the file that produced it.
MAX_UNMATCHED_REPORTED = 50


@dataclass
class _CatalogueIndex:
    """What a reading history import reads once rather than per row.

    Three lookups happen per row and each was its own query: the Book, this
    Member's reading status, and whether they already have a note on it. That
    is fine for one row and is 25,000 statements for a Goodreads export.
    Measured before this existed: a 5000 row file cost **25,001 statements and
    61 seconds**, and profiling put only about 15% of that in SQLite. The rest
    was SQLAlchemy compiling the same three queries five thousand times each.

    **It does not make the per row cost zero, and does not claim to.** A matched
    row still issues one `db.get`, because that is the lookup that has to return
    a live object rather than an id.

    What is measured here rather than inherited: `tests/test_importing.py`
    counts **SELECTs** and finds **one per extra matched row**. The 25,001
    figure above is the original profile and counted every statement, writes
    included, so the two are not the same unit and no total is derived from
    them here. The claim this module makes is the slope, and the slope is one.

    Which Book a row is belongs to `books`, which `recognition` builds.
    """

    books: recognition.Index
    statuses: Records
    notes: set[int]

    @classmethod
    def build(cls, db: Session, user_id: int) -> _CatalogueIndex:
        return cls(
            books=recognition.Index.build(db, user_id, recognition.Source.READING_HISTORY),
            # The Member's whole reading record rather than the matched Books':
            # which Books a 5,000 row file will match is not known until it has
            # been walked, and per row would be one SELECT per line.
            statuses=Reading.by(db, user_id).everything(),
            notes={
                book_id
                for (book_id,) in db.query(Note.book_id).filter(Note.user_id == user_id)
            },
        )


def _settle_one(
    answer: recognition.Answer,
    tally: _Tally,
    *,
    load: Callable[[int], Book],
    unmatched_title: str,
    create: Callable[[], Book],
    fill_gaps: Callable[[Book], None],
    create_missing: bool,
) -> Book | None:
    """One row, once `recognition` has answered which Book it is.

    **The branch that is about privacy rather than correctness is here and
    nowhere else.** A `Hidden` row is counted and its title is never reported.
    This module's docstring holds what creating it would cost and why `skipped`
    counts it together with the rows that had no title; it is not restated here.

    **Every importer creates through this function and has no other path to the
    database**, which is what the three hand written copies could not give: a
    fourth importer that writes the refusal itself, or forgets to, cannot add a
    Book at all. `tests/test_importing.py::TestEveryImporterCreatesThroughTheSpine`
    derives the importers from the module rather than listing them, and states
    what that derivation cannot see.

    Returns the Book a per importer tail runs on, or None when the row is
    done. **None means done, not "was not created"**: the refused row and the
    unmatched row both end here, and a caller that carried on would run its
    tail on a row this function declined to act on.

    | answer | with `create_missing` | without |
    |---|---|---|
    | `Seen` | matched, gaps filled | the same |
    | `Unknown` | created | listed unmatched |
    | `Tied` | listed as ambiguous, nothing created | the same |
    | `InTrash` | listed in the trash, nothing written | the same |
    | `Hidden` | counted, never named | listed unmatched |

    A `Seen` Book's id is recorded before it is loaded, so that a Book deleted
    since the index was read is found by `_a_vanished_match_met_another_change`
    wherever the import then fails on it, this load included.

    **`Hidden` is listed without `create_missing`, and that is not a leak.**
    The refusal is about the create: with nothing to create, the title came off
    the caller's own file and is listed exactly as an `Unknown` row is, so the
    two cannot be told apart.

    **`InTrash` writes nothing rather than purging and creating** as the add
    door does. Listing the row is the owner's ruling of 2026-10-17; not
    purging is this module's own reason: the trash view holds other Members'
    public Books too, and a bulk import that purged would destroy one. It holds
    for the CSV, OPDS and MARC importers only. The Calibre library and store
    imports run in the browser and post each Book to the add door, which
    purges the trashed holders and creates only when the caller added every
    one, and otherwise answers 409 `in_trash`, as this listing does. Its title
    is listed because the Member can already see that Book in their trash.

    What stays with each importer, because each difference has a reason:

    * **what `unmatched_title` is spelled from.** Three spellings over three
      sources, and only one of them is behavioural: `OpdsImport` refuses a
      missing title before the match because its own constructor path nulls an
      over wide one, `csv_import` has already dropped such a row, and the MARC
      caller's `or ""` is a type level belt no uploaded file reaches. Each call
      site says which it is.
    * **which columns the gap fill writes**, and every `_create` body.
    * **the tail**, and where it sits relative to the gap fill.
    """
    match answer:
        case recognition.Seen(book_id=book_id):
            # Before the load, because the load is the first place a Book
            # deleted since the index was read can fail. Not re-resolved under
            # a lock here: that is a statement and a lock on every matched row
            # of every import (`docs/decisions.md`, the deadlock 409).
            if book_id not in tally.created_ids:
                tally.loaded.add(book_id)
            book = load(book_id)
            tally.matched += 1
            fill_gaps(book)
            return book
        case recognition.Hidden() if create_missing:
            tally.unmatched_private += 1
            return None
        case recognition.InTrash():
            tally.in_trash += 1
            if len(tally.in_trash_titles) < MAX_UNMATCHED_REPORTED:
                tally.in_trash_titles.append(unmatched_title)
            return None
        case recognition.Tied():
            tally.ambiguous += 1
            if len(tally.ambiguous_titles) < MAX_UNMATCHED_REPORTED:
                tally.ambiguous_titles.append(unmatched_title)
            return None
        case recognition.Unknown() if create_missing:
            created = create()
            tally.created += 1
            tally.created_ids.add(created.id)
            return created

    if len(tally.unmatched) < MAX_UNMATCHED_REPORTED:
        tally.unmatched.append(unmatched_title)
    return None


class Import:
    """One parsed export, applied to the Library as one Member.

    Immutable in the sense that matters: the viewer is fixed at construction
    and no method takes another, so nothing can write one Member's reading
    record while reading another's shelf.
    """

    __slots__ = ("_db", "_member_id")

    def __init__(self, db: Session, member_id: int) -> None:
        self._db = db
        self._member_id = member_id

    @classmethod
    def for_member(cls, db: Session, member_id: int) -> Import:
        """An import run as this Member.

        Named like `Shelf.seen_by` and `Authorship.seen_by`, and for the same
        reason: everything read is what this Member may see, and everything
        personal that is written is theirs.
        """
        return cls(db, member_id)

    def apply(
        self,
        parsed: csv_import.ParsedFile,
        *,
        create_missing: bool = False,
        apply_tags: bool = False,
    ) -> ImportResultOut:
        """Apply every row, and report what happened.

        Commits once at the end. A row that cannot be acted on is counted and
        skipped rather than raising, because one bad row in a five thousand row
        export must not throw the other four thousand nine hundred away.

        Statuses are **personal**: this only ever writes the importing Member's
        own `user_books` rows. Importing your shelves does not change what
        anyone else has read, and two Members can import their own exports
        without fighting over the same Books.
        """
        index = _CatalogueIndex.build(self._db, self._member_id)
        tally = _Tally()
        # Built whether or not tags are wanted, because nothing behind it reads
        # until it is asked: the branch this replaced existed only to keep the
        # query off an import that applies no tags.
        naming = tags.Naming.for_member(
            self._db, self._member_id, budget=tags.MAX_NEW_TAGS_PER_IMPORT
        )

        with _a_vanished_match_met_another_change(self._db, self._member_id, tally):
            for row in parsed.rows:
                self._apply_one(row, index, tally, naming, create_missing, apply_tags)
            self._db.commit()

        return ImportResultOut(
            rows_read=len(parsed.rows),
            matched=tally.matched,
            created=tally.created,
            statuses_updated=tally.updated,
            # Rows whose ISBN belongs to somebody else's Private Book are
            # counted with the ones that had no title: both are rows this
            # import could not act on, and separating them out would be the
            # oracle again.
            skipped=parsed.skipped + tally.unmatched_private,
            # Passed through rather than folded into `skipped`, and the reason
            # is the reverse of the one above: a row the file itself marked as
            # gone is read off the member's own upload and says nothing about
            # what this instance holds, so it is not an oracle and does not have
            # to hide inside a wider count. See `csv_import.ParsedFile.excluded`.
            excluded=parsed.excluded,
            tags_dropped=tally.tags_dropped,
            unmatched_titles=tally.unmatched,
            in_trash=tally.in_trash,
            in_trash_titles=tally.in_trash_titles,
            ambiguous=tally.ambiguous,
            ambiguous_titles=tally.ambiguous_titles,
        )

    def _apply_one(
        self,
        row: csv_import.ImportRow,
        index: _CatalogueIndex,
        tally: _Tally,
        naming: tags.Naming,
        create_missing: bool,
        apply_tags: bool,
    ) -> None:
        """One row: match it, maybe create it, then write what is personal."""
        book = _settle_one(
            index.books.recognise(title=row.title, author=row.author, isbn=row.isbn),
            tally,
            load=lambda book_id: self._db.get_one(Book, book_id),
            unmatched_title=row.title,
            create=lambda: self._create(row, index),
            fill_gaps=lambda matched: _fill_gaps(matched, row),
            create_missing=create_missing,
        )
        if book is None:
            return

        if apply_tags and row.tags:
            tally.tags_dropped += self._apply_tags(book, row.tags, naming)

        if self._apply_reading_record(index, book_id=book.id, row=row):
            tally.updated += 1

        if row.notes:
            self._keep_review(index, book_id=book.id, text=row.notes)

    def _create(self, row: csv_import.ImportRow, index: _CatalogueIndex) -> Book:
        """Add a Book the export lists and the catalogue does not have.

        **No cover is fetched here, and that is deliberate.** Every other add
        path stores one on the way in (`routers/books._store_cover`); this one
        runs over thousands of rows inside a single request, and a fetch per
        row would be thousands of round trips holding the request open until a
        proxy gives up on it. The Books arrive without covers and
        `POST /api/books/covers/backfill` fills them in afterwards,
        concurrently and in bounded batches, which is the same work without a
        request waiting on it.
        """
        book = Book(
            title=row.title,
            author=row.author,
            isbn=row.isbn,
            publisher=row.publisher,
            year=row.year,
            page_count=row.pages,
            format=row.format,
            added_by_user_id=self._member_id,
            # An export says what someone read, not what is on the shelf.
            # Marking these OWNED would assert something nobody checked, so
            # they arrive unverified and are confirmed in bulk afterwards.
            ownership=OwnershipStatus.UNKNOWN,
        )
        self._db.add(book)
        self._db.flush()
        index.books.remember(book)
        return book

    def _apply_tags(self, book: Book, names: list[str], naming: tags.Naming) -> int:
        """Put the file's tags on the Book. How many names did not go on it.

        **Every rule this used to carry lives in `tags.py` now**, which is the
        point of that module: the fold, the ordering a case differing pair is
        resolved by, the normalisation, the truncation, both caps and, since
        the attach by name door, who a matched Tag may be handed to. This is
        the loop and nothing else, and what it must not do is reimplement any of
        them for the import's convenience.

        **The room check comes before the mint and is not the same check as
        `tags.attach`'s.** A Book already at its ceiling would otherwise spend
        the import's new tag budget on names it is then refused, so a later Book
        in the same file loses tags to one that could not carry them.

        Takes the Naming rather than a cache and a tally: the budget, the
        index and the viewer are spent and counted in one object instead of
        being threaded out of the caller and back in.

        **Four causes, one number, and the fold is the whole reason there is a
        number at all.** A name is not put on the Book when it normalises to
        nothing, when the mint budget is spent, when the Book is already at
        `MAX_TAGS_PER_BOOK`, and when the Tag it names is not this Member's to
        use. Reporting the fourth apart from the other three would answer
        "does a Tag by this name exist on a Book I cannot see" for every name
        in an upload at once, which is the channel the refusal exists to
        narrow.

        **The number counts what reached this loop, which is not what the file
        held**, and the difference is three things upstream of here:
        `csv_import.MAX_TAGS_PER_ROW` cuts a cell before it is parsed into a
        row, `_split_tags` drops a part that is only whitespace, and a row
        settled to no Book never reaches this at all. None of those is a
        refusal and none is counted; `ImportResultOut.tags_dropped` says so
        where a reader of the response meets it.

        **And the fold is a narrowing rather than a closure, stated because a
        published file must not imply otherwise.** A caller writes the file,
        so they control the first three: send one well formed name against an
        empty Book with budget to spare and the count reads the fourth
        directly. What the fold costs them is that they cannot read a batch,
        which is the same protection `tags.Naming` describes and the same
        residue.
        """
        dropped = 0
        for position, raw in enumerate(names):
            if not tags.room_on(book):
                # The rest of this row's cell goes with it, and every one of
                # those names is one the file asked for and did not get.
                # Counted off the position rather than the value, because a
                # cell may list one name twice and `list.index` would answer
                # for the first of them.
                dropped += len(names) - position
                break

            tag = naming.tag(raw)
            if tag is None:
                dropped += 1
                continue

            # False here is the ceiling, which `room_on` has already refused
            # above, so it is unreachable from this loop and the count does
            # not read it. `attach` keeps the check because it is what makes
            # the ceiling true of every writer, not only of this one.
            tags.attach(book, tag)

        return dropped

    def _keep_review(self, index: _CatalogueIndex, *, book_id: int, text: str) -> None:
        """Keep the review the export carried, as this Member's private note.

        The parser has been reading "My Review" all along and the import threw
        it away, which is the same waste the rating and the finish date used to
        be. A review is written by one Member about one Book, and `Note` is the
        row that is keyed that way, so it lands there rather than on the Book.

        **`is_private=True`, and the flag is the whole point of this line.**
        `private notes` is one of the header names a review is read from, so
        without it the column another app called private arrives under this
        Member's own name for everyone to read. `models.Note` says why
        authorship was not already the answer, and `docs/decisions.md` carries
        the owner's decision of 2026-09-06.

        **A note written here through the app is not private**, and that
        asymmetry is deliberate rather than an oversight: somebody typing into
        a shared library's note box can see the box is shared, and somebody
        handing over a CSV cannot see where each column lands.

        Skipped when this Member already has a note on the Book: an import is
        not a reason to append the same paragraph on every re-run. **So an
        earlier import's review stays as it was written, shared**, since
        nothing records that a note came from an import and this line will not
        run again for that Book. It is the Member's own note and they can
        delete it.
        """
        if book_id in index.notes:
            return
        self._db.add(
            Note(
                book_id=book_id,
                user_id=self._member_id,
                content=text[:5000],
                is_private=True,
            )
        )
        index.notes.add(book_id)

    def _apply_reading_record(
        self, index: _CatalogueIndex, *, book_id: int, row: csv_import.ImportRow
    ) -> bool:
        """Write this Member's status, rating and finish date. True if anything
        changed.

        Existing local values are never overwritten: somebody who has already
        rated a Book here has expressed a more recent opinion than an export
        taken from another service. The import fills gaps, on the same
        principle as metadata enrichment.
        """
        if row.status is None and row.rating is None and row.date_read is None:
            # Nothing personal in this row. A file that is a plain book list
            # should not leave an "unread" marker on every Book it touched.
            return False

        # **`status_of`, not `existing.status`.** A file carrying two rows for
        # one Book (a rating on the first, a status on the second) leaves the
        # first row's `open()` unflushed, and `find()` answers the second from
        # the identity map, so nothing flushes in between: `status` is still
        # None and `ReadStatus(None)` raises, taking the whole import down with
        # it. Read before `open()`, because opening is what creates that row.
        had_a_record = index.statuses.get(book_id) is not None
        current = index.statuses.status_of(book_id)
        existing = index.statuses.open(book_id)

        # A Book with no record is changed by getting one. One that had a
        # record changes only if this row names a different status.
        changed = not had_a_record or (row.status is not None and current is not row.status)

        if row.status is not None:
            existing.status = row.status

        if row.rating is not None and existing.rating is None:
            existing.rating = row.rating
            changed = True

        # Only for Books the export says were finished. A date on a
        # currently-reading row would be a finish date for a Book nobody
        # finished.
        if (
            row.status is ReadStatus.READ
            and row.date_read is not None
            and existing.finished_at is None
        ):
            existing.finished_at = datetime.combine(row.date_read, time.min)
            changed = True

        return changed


@dataclass
class _Tally:
    """What one run has done so far.

    A value rather than six locals threaded through the row loop, which is what
    let the loop body move out of the handler at all.
    """

    matched: int = 0
    created: int = 0
    updated: int = 0
    unmatched_private: int = 0
    in_trash: int = 0
    ambiguous: int = 0
    #: Records with nothing left to file them under. Only `OpdsImport` counts
    #: these: the other two importers get the number from their parser, which
    #: has already dropped a titleless row before this class is built.
    skipped_untitled: int = 0
    #: Tag names a run tried to put on a Book and did not. Four causes and
    #: one number, argued at `Import._apply_tags`, and **not** a count of what
    #: the source held: `csv_import.MAX_TAGS_PER_ROW` cuts the cell before this
    #: loop sees it. Only the CSV importer counts these, because it is the only
    #: one that reads tags at all.
    tags_dropped: int = 0
    #: Capped at `MAX_UNMATCHED_REPORTED` by the caller, not here: this is a
    #: tally, and where the ceiling comes from is the report's business.
    unmatched: list[str] = field(default_factory=list)
    #: Capped the same way, at the same ceiling.
    in_trash_titles: list[str] = field(default_factory=list)
    #: Capped the same way, at the same ceiling.
    ambiguous_titles: list[str] = field(default_factory=list)
    #: Every `Seen` Book a row loaded. **Only those**: the index also holds
    #: Books this Member cannot see, and checking whether one of them still
    #: exists would answer, as 409 against 500, whether it was deleted.
    loaded: set[int] = field(default_factory=set)
    #: Every Book this run created. A later row naming one matches it, and it
    #: is kept out of `loaded`: a failure's rollback deletes it, so the check
    #: would find it gone and answer 409 to a failure every resend meets again.
    created_ids: set[int] = field(default_factory=set)


#: What an import raises on a matched Book that another transaction deleted
#: after the index was read, by where it meets the gone row: the load, or the
#: refresh after `hold_book_ceilings` in the MARC tail, raises
#: `InvalidRequestError`; a gap fill's UPDATE at the flush raises
#: `StaleDataError`; a child row's INSERT raises a foreign key violation.
#: **Every `SQLAlchemyError` rather than those three**, because the last one's
#: type is the driver's choice: pg8000 raises `IntegrityError` for 23505 alone
#: and `ProgrammingError` for 23503, so a list naming `IntegrityError` let the
#: violation through as a 500. **Never `Exception`**: a privacy refusal in
#: `shelf.py` is a `ValueError` or a `TypeError`, which a resend raises again.
_MEETING_A_GONE_ROW: Final = SQLAlchemyError


@contextmanager
def _a_vanished_match_met_another_change(
    db: Session, member_id: int, tally: _Tally
) -> Iterator[None]:
    """Raise `errors.MetAnotherChange` where the import failed on a matched
    Book that is gone, and anything else unchanged.

    **Around the row loop and the commit together.** The session does not
    autoflush, so a default CSV import writes nothing until its commit, and a
    Book deleted after its row was loaded fails there rather than in the loop.

    **Decided by whether a loaded Book is gone, not by the exception**: an
    unrelated failure raises the same types, a deadlock among them, and is
    raised unchanged unless a loaded Book is gone. The check is one SELECT,
    after the rollback, and only on the failure path: an import that meets no
    race issues nothing more. A loaded Book that has since become invisible
    reads as gone, and the resend then sees it as `Hidden`.

    An unrelated failure in the same import as a vanished match answers 409,
    and the resend, whose index no longer names the gone Book, meets it as a
    500 unless a Book it loaded vanishes too. A Book the import created is
    never checked (`_Tally.created_ids`), so it cannot make that 500 a 409.
    """
    try:
        yield
    except _MEETING_A_GONE_ROW as error:
        # First: on Postgres the failure aborted the transaction, so nothing
        # can be read in it, and the import commits nowhere else.
        db.rollback()
        if tally.loaded and _any_gone(db, member_id, tally.loaded):
            raise MetAnotherChange from error
        raise


def _any_gone(db: Session, member_id: int, book_ids: set[int]) -> bool:
    """Whether any of these Books is no longer on this Member's shelf."""
    present = Shelf.seen_by(db, member_id).where(Book.id.in_(book_ids)).count()
    return present < len(book_ids)


def _fill_gaps(book: Book, row: csv_import.ImportRow) -> None:
    """Add what the export knows and the catalogue does not.

    Never overwrites. A Book already here was scanned from a real catalogue or
    typed by hand, and both outrank a CSV from another service, on the same
    principle as metadata enrichment. What counts as a gap is `evidence`'s.
    """
    evidence.fill_gaps(
        book,
        {
            "publisher": row.publisher,
            "year": row.year,
            "page_count": row.pages,
            "format": row.format,
        },
    )


# ── MARC ──────────────────────────────────────────────────────────────────────
#
# A second reader on the same application. `csv_import.py` reads a service's
# export of somebody's shelf; `marc.py` reads a library's export of its
# catalogue. They meet here because everything below the parse is the same
# question: is this book already held, and if not, is it wanted.
#
# Three things differ, and each one is why this is not `apply` with a flag.
#
# **A MARC record carries a catalogue, not a reading history.** There is no
# status, no rating, no date read and no review, so nothing personal is
# written at all: a MARC import touches no `user_books` row. That is the whole
# reason the two paths do not share `_apply_one`, which exists to write them.
#
# **It carries classifications**, which a CSV never does. That is the field a
# cataloguer least wants to retype and the one this whole ticket turns on.
#
# **It matches on author and title together, never on title alone.** See
# `identity.work_key`, and `recognition.Source.CATALOGUE` for the ladder.


#: A `Record` this Library has already held to its own bounds: what every
#: importer below reads, and what matching keys on.
#:
#: **A `NewType` rather than a second dataclass**, so the column names and their
#: types stay declared once, on `Record`. It is identity at runtime, so nothing
#: is copied and there is no third table of column names to drift against
#: `_MARC_RECORD_FIELDS` and the two ceiling tables.
#:
#: **What it buys is a signature that cannot take an unbounded record.** Without
#: it, "matching reads the bounded view, never the raw record" is a docstring
#: sentence with nothing behind it: handing the raw record to `recognise_stored`
#: behaves identically on every reachable path, because `within_bounds` is the
#: identity there, so no behavioural test could ever observe the mistake.
#:
#: **The type checker and the guard refuse different things, and only the guard
#: reaches a write site.** Measured: `mypy` refuses a plain `Record` where a
#: `Stored` is wanted, which is the whole of what the name buys, and it accepts
#: `Stored(record)` over a raw one, because a `NewType` call is a cast. **Neither
#: create path is checked at the write either, and the reason is the constructor
#: rather than how the kwargs are spelled**: `Book.__init__` is `(self, **kwargs)`,
#: contributed by SQLAlchemy's instrumentation, and the only mypy plugin configured
#: here is pydantic's, so `Book(cover_url=...)` is accepted whatever the value.
#: `OpdsImport._create` names its three fields outright and is no more checked than
#: the walk beside it. So what refuses a column this importer must not write is
#: `tests/test_importing.py::TestTheImporterReachesNoColumnOffItsOwnTuple`,
#: and what keeps the cast to one site is its arm on the mint. **That arm reads
#: this module only**, so a raw record laundered through `Stored` elsewhere
#: satisfies every signature below and is invisible to both instruments.
Stored = NewType("Stored", Record)


def stored_record(record: Record) -> Stored:
    """The record as this Library will store it, computed once.

    **Matching reads this, not the record**, which is a correctness fix rather
    than an optimisation: matching on the incoming value and storing the bounded
    one means the key a duplicate is looked up by is not the key that was stored,
    so the same record imported twice can fail to find itself. `Stored` is what
    makes that a signature rather than a sentence.

    **The `within_bounds` call no longer bounds anything, and is kept as belt.**
    Every producer builds its record through `Record.__init__`, so
    `catalogue.Record.__post_init__` has already held every scalar to
    `_TEXT_CEILINGS` or `_NUMBER_RANGES`, and the upload path has truncated the
    cut set in `Record.from_upload` before that. Measured over 86 (field, value,
    constructor) cases, values at each bound, one past it and far past it,
    through both constructors: this function differed from the record's own
    fields in 0 of them. It is weaker than the sample suggests: for all ten
    names the `catalogue` ceiling **equals** `min(column width, BookCreate
    MaxLen)` and each range equals the `Ge` and `Le`, so `within_bounds` is the
    identity over its whole reachable domain and no test driving a record end to
    end can tell it from `return value`.

    **What would make the second bound reachable**, stated so the belt is
    checkable rather than assumed: a `Record` that never ran `__post_init__`.
    That is an `object.__setattr__` outside `catalogue.py`'s own droppers, or a
    record built through `__new__`, `copy` or unpickling. Nothing does either
    today, **and that bypass is what observes this call**:
    `tests/test_importing.py::TestTheSecondBoundHasOneConstructibleBypass`
    pushes each of these columns past each side of its bound after construction,
    a ceiling and, where the bound is a range, a floor, and asserts the value
    that comes back rather than that something changed. Deleting that test leaves
    this line with nothing that would notice it stopping, which is the state this
    docstring described until 2026-09-19.

    **It answers the record itself where the belt altered nothing**, which is
    every reachable path, and that is a behaviour decision rather than a saving.
    `Record.with_scalars` re-runs `__post_init__`, whose droppers cover the **whole**
    record including `isbn`, which `_MARC_RECORD_FIELDS` excludes and which
    therefore reaches its column unbounded by this function. Rebuilding
    unconditionally turns a 40 character ISBN set past the constructor from
    verbatim into `None`: measured, and **nothing in the suite distinguishes the
    two answers**, which is what makes the unconditional spelling tempting and
    wrong to take here.

    **So an over wide ISBN on that bypass reaches its column when the belt altered
    nothing else, and comes back `None` when it altered anything**, because the
    rebuild re-runs the droppers over the whole record. Measured on the one
    constructible bypass, with a 550 character title and again with an out of range
    year: a field this function never walks answers differently depending on an
    unrelated neighbour. That conditionality is the sharper argument for a bound
    that drops rather than cuts, since a value whose fate depends on another column
    is worse than one that is consistently wrong.

    **It stays open on purpose, and it is mechanically closable**, which an earlier
    version of this paragraph denied: `isbn` could join `_MARC_RECORD_FIELDS`,
    `_gap_fields` would
    still drop it because `book_columns.WORK_DETAIL` holds neither it nor `title`,
    and the belt would cut rather than null it because its ceiling equals the
    column's. **The objection is the value, not the mechanism.**
    `catalogue._KEPT_WHOLE_ON_UPLOAD` already records that a cut ISBN is a
    different identifier, and this column is unique across the whole table and is
    this importer's primary match key, so a truncation invents a key that can
    collide with a row no catalogue ever named. Measured: a 40 character value
    cuts to 20 characters that `isbn.parse` refuses. Closing it therefore wants a
    bound that drops rather than cuts, and
    `tests/routers/test_imports_marc.py::TestAMatchedBookNeverGainsAnIsbn` carries
    an arm reading today's tuple that would have to be changed deliberately.

    **Where the belt did alter something, two bounds compose, and that is why
    the tables have to agree per name.** The rebuild re-runs `_drop_unstorable`,
    which **nulls** an over wide string where `within_bounds` **cuts** one. So a
    truncation survives the rebuild only while `min(column width, BookCreate
    MaxLen)` is no wider than `catalogue._TEXT_CEILINGS`, and a range survives
    only while the `Ge` and `Le` sit inside `catalogue._NUMBER_RANGES`. That
    equality was prose while this function returned a dict and never re-entered
    the constructor. It is load bearing now, so it has arms:
    `tests/test_importing.py::TestBothBoundsAgreeOnEveryName`.

    **Which is why this is not where a new column gets its bound.** The
    ceilings live in `catalogue.py` and
    `tests/test_marc.py::TestEveryColumnTheImporterWritesIsBounded` asserts that
    every name in `_MARC_RECORD_FIELDS` has an entry in one of its two tables.
    """
    rebound: dict[str, Any] = {}
    for name in _MARC_RECORD_FIELDS:
        value = getattr(record, name)
        held = within_bounds(name, value)
        if held != value:
            rebound[name] = held
    return Stored(record.with_scalars(**rebound) if rebound else record)


def recognise_stored(index: recognition.Index, stored: Stored) -> recognition.Answer:
    """Which Book a bounded record is.

    Takes a `Stored`, never a plain `Record`: see `stored_record` for what
    matching on the unbounded values cost. The MARC import and its preview
    both ask through here, so the two screens cannot disagree about a record.
    `or ""` is `MarcImport._apply_one`'s belt, said there.
    """
    return index.recognise(title=stored.title or "", author=stored.author, isbn=stored.isbn)


def within_bounds(attribute: str, value: Any) -> Any:
    """One incoming value, held to the bound the API would hold it to.

    **The MARC importer was the one writer of these columns that bounded
    nothing**, and an import is the widest door into this database: a record
    arrives from another institution, not from a form this app rendered.

    **What an unbounded number costs was measured**: 70.5 bytes and 0.624 seconds
    per million elements, so a stored `1e9` is roughly 70 GB and ten minutes, per
    member, per request, until somebody finds the row.

    **The bounds are read off the declarations, never retyped**, so a column and
    the schema in front of it cannot drift apart here.

    **Both widths are consulted and the smaller wins.** SQLite ignores VARCHAR
    width, so a disagreement refuses nothing and is invisible; reading both is a
    second opinion rather than a safety net.

    **Strings truncate, numbers are dropped.** Truncating a title keeps a usable
    record; truncating a number invents a different one.

    **A `MaxLen` on a container field is a count of entries, not a width, and is
    ignored here.** `BookCreate.categories` is `list[CategoryField]` with
    `MaxLen(32)` for the number of subjects, while the column is `Text` and states
    no width, so reading that 32 as a width cut a joined subject string to 32
    characters. Measured, before this guard: `within_bounds("categories", "x" * 200)`
    returned 32 characters. Not reachable today, because `_MARC_RECORD_FIELDS`
    excludes the column, and that tuple's own docstring invites additions.
    `schemas.book.admits_a_container` is the one home for the question.
    """
    if value is None:
        return None

    field = BookCreate.model_fields.get(attribute)
    limits = list(field.metadata) if field is not None else []
    counts_entries = field is not None and admits_a_container(field.annotation)

    if isinstance(value, str):
        widths = [
            width
            for width in (
                getattr(Book.__table__.c[attribute].type, "length", None),
                *(
                    m.max_length
                    for m in limits
                    if isinstance(m, annotated_types.MaxLen) and not counts_entries
                ),
            )
            if width is not None
        ]
        return value[: min(widths)] if widths else value

    for limit in limits:
        if isinstance(limit, annotated_types.Ge) and value < limit.ge:
            return None
        if isinstance(limit, annotated_types.Le) and value > limit.le:
            return None
    return value


#: Every column `MarcImport` writes out of a record, and the single list both
#: writers walk.
#:
#: **One tuple rather than a keyword list in `_create` and a second in
#: `_fill_marc_gaps`**, because a guard applied to one writer and not the one
#: beside it is the shape this repository keeps finding. A column added here is
#: bounded on both paths or on neither.
#:
#: `isbn` is deliberately absent and is bounded already: `marc_fields.Fields.isbn`
#: returns `isbn.parse`'s output or None, which is thirteen digits.
#:
#: **`categories` is deliberately absent too, and it is an exclusion rather than an
#: omission.** A MARC record **does** carry uncontrolled subject labels:
#: `marc_fields.Fields.controlled_subjects` answers two lists and `marc.py` puts the
#: plain `$a` on `Record.subjects`. This importer **discards** them, writing only
#: `record.headings`, at `MarcImport._apply_one`. So the exclusion is a decision
#: about what an import writes and not a claim about what a record holds, which an
#: earlier version of this note got backwards.
#:
#: The same labels do reach `books.categories` on the **lookup** path, where
#: `Record.subject_labels` feeds `catalogue.Record.as_match`. Stated because an
#: exclusion and an omission read identically at this site, and `POST /api/books`
#: now writes that column, so the next reader would otherwise have to guess.
_MARC_RECORD_FIELDS: Final = (
    "title",
    "subtitle",
    "author",
    "publisher",
    "year",
    "description",
    "language",
    "page_count",
    "series_name",
    "series_index",
)


def _gap_fields(written: Sequence[str]) -> tuple[str, ...]:
    """Of the columns the create path writes, the ones a gap filler may write.

    A function rather than the filter inline, so a test can drive it against a
    tuple it builds: with the names as they stand this filter and `!= "title"`
    return the same nine, and the difference between them only appears on an
    argument this module does not currently produce.

    **It drops silently, which is the trap.** A name added above that is not a
    work fact, a shelving location off `852 $c` being the plausible one, is
    written when a record creates a Book and skipped when one matches an
    existing Book, with both writers still walking one list.
    `tests/test_marc.py::TestEveryColumnTheImporterWritesIsBounded` refuses that
    tuple where it holds a name `book_columns.WORK_FACTS` does not.
    """
    return tuple(name for name in written if name in book_columns.WORK_DETAIL)


#: The columns a matched Book takes from an incoming record.
#:
#: **Fill the gaps, never overwrite.** An import may add what a row is missing
#: and may not replace what somebody here already wrote, because the person who
#: typed a value knows more about this copy than a stranger's record does.
#:
#: **What the create path writes, narrowed to what any gap filler may write**,
#: rather than to everything but the title. The two the narrowing drops are
#: `book_columns.WORK_IDENTITY`: `title`, which a matched Book has by definition
#: since it is half of what matched it, and `isbn`, which is unique and whose
#: failure `tests/routers/test_imports_marc.py::TestAMatchedBookNeverGainsAnIsbn`
#: names. Naming `title` alone refuses one of the two and passes the other the
#: day it is added above; asking which columns a gap filler may write refuses
#: both, and refuses the next one without an arm.
#:
#: The column by column reasoning, and what each one costs if it is wrong, is in
#: `docs/decisions.md`.
_MARC_GAP_FIELDS: Final = _gap_fields(_MARC_RECORD_FIELDS)


class MarcImport:
    """One parsed MARC file, applied to the Library as one Member.

    Separate from `Import` rather than a mode on it, and the reason is the
    absence rather than the presence: **a MARC import writes nothing personal.**
    A catalogue record carries no reading status, no rating, no date read and
    no review, so there is no `user_books` row to write and no
    `Reading.by(member)` call anywhere below. Folding this into `Import.apply`
    would have meant threading "and skip everything that makes this an import
    of somebody's shelf" through the one method whose job is writing exactly
    that.

    The viewer is still fixed at construction, for `Import`'s reason: what is
    read is what this Member may see, and a created Book is attributed to them.
    """

    __slots__ = ("_db", "_member_id")

    def __init__(self, db: Session, member_id: int) -> None:
        self._db = db
        self._member_id = member_id

    @classmethod
    def for_member(cls, db: Session, member_id: int) -> MarcImport:
        return cls(db, member_id)

    def apply(
        self, parsed: marc.ParsedMarc, *, create_missing: bool = True
    ) -> ImportResultOut:
        """Apply every record, and report what happened.

        **`create_missing` defaults to true here and to false on the CSV
        path**, which looks like an inconsistency and is the two files meaning
        different things. A Goodreads export is a reading history, so most of
        its rows are books the household does not own and creating them by
        default would fill the shelf with books nobody has. A MARC file is a
        catalogue somebody is transferring, and importing it without adding the
        records is importing nothing.

        Commits once at the end. One record that cannot be acted on is counted
        and skipped: a catalogue export is the product of years and is not
        uniformly clean, and failing the transfer on record 412 of 5,000 gives
        the cataloguer nothing to act on.
        """
        index = recognition.Index.build(
            self._db, self._member_id, recognition.Source.CATALOGUE
        )
        tally = _Tally()

        with _a_vanished_match_met_another_change(self._db, self._member_id, tally):
            for record, links in parsed.entries():
                self._apply_one(record, index, tally, create_missing, links)
            self._db.commit()

        return ImportResultOut(
            rows_read=len(parsed.records),
            matched=tally.matched,
            created=tally.created,
            # Nothing personal is written, so nothing personal changed. Reported
            # as zero rather than omitted, because the field is on the shared
            # result model and a client that hid it for one importer would have
            # to know which one it was looking at.
            statuses_updated=0,
            # Records with no title, plus records whose ISBN belongs to a Book
            # this Member cannot see. Counted together for `Import.apply`'s
            # reason: separating them would be an oracle for "does a Book with
            # this ISBN exist in this house", which the 404-not-403 rule
            # withholds.
            skipped=parsed.skipped + tally.unmatched_private,
            unmatched_titles=tally.unmatched,
            in_trash=tally.in_trash,
            in_trash_titles=tally.in_trash_titles,
            ambiguous=tally.ambiguous,
            ambiguous_titles=tally.ambiguous_titles,
        )

    def _apply_one(
        self,
        record: Record,
        index: recognition.Index,
        tally: _Tally,
        create_missing: bool,
        links: Sequence[Link],
    ) -> None:
        # Once, before anything reads a value: matching and writing have to see
        # the same strings or a truncated record cannot match itself. See
        # `stored_record`.
        stored = stored_record(record)
        book = _settle_one(
            recognise_stored(index, stored),
            tally,
            load=lambda book_id: self._db.get_one(Book, book_id),
            # A title the caller supplied in their own file, so reporting it
            # discloses nothing they did not already have.
            #
            # **`or ""` is a type level belt and no uploaded file reaches it.**
            # `marc.py` builds through `Record.from_upload`, and `title` is in
            # `catalogue._CUT_ON_UPLOAD`, so an over wide one is cut to the
            # column's width and the unstorable pass then finds it in bounds. A
            # ten thousand character title arrives here as a five hundred
            # character string, and a record with no `245 $a` never becomes a
            # Record at all: `marc.read` counts it in `ParsedMarc.skipped`.
            # **The type checker now requires it**, where it did not while
            # this value arrived out of a `dict[str, Any]`: `Record.title` is
            # declared `str | None` and `unmatched_title` is `str`. So removing
            # it is a mypy error rather than a silent change, and this comment
            # is no longer the only thing holding it in place. What the comment
            # is still for is the half a type cannot say: which file shapes
            # reach the `None` side, and that none of them does.
            #
            # **`OpdsImport._apply_one` is the contrast, not the source.** That
            # path builds through the plain constructor, where the unstorable
            # pass does null an over wide title, which is why its refusal is
            # behavioural where this belt is not. `from_upload` is the single
            # fact the two paths do not share, and a reason carried across it
            # is wrong in exactly this way: this comment said the column had
            # dropped the title, which is the OPDS sentence.
            unmatched_title=stored.title or "",
            create=lambda: self._create(stored, index),
            fill_gaps=lambda matched: _fill_marc_gaps(matched, stored),
            create_missing=create_missing,
        )
        if book is None:
            return

        # After the create and after the gap fill, so a matched Book gains the
        # headings it lacked as well as a new one getting all of them.
        evidence.confirm_file_headings(book, record.headings, self._db)
        _keep_links(book, links, self._db)

    def _create(self, stored: Stored, index: recognition.Index) -> Book:
        """Add a Book the file catalogues and this Library does not hold.

        **`ownership=UNKNOWN`, exactly as the CSV path does it**, and the reason
        is the same one said differently: another institution's record says that
        institution holds the book, not that this one does. Confirmed in bulk
        afterwards, which is what `POST /api/books/bulk` with `SET_OWNERSHIP`
        is for.

        **No cover is fetched**, for `Import._create`'s reason: a fetch per
        record over a whole catalogue is thousands of round trips holding one
        request open. `POST /api/books/covers/backfill` does it afterwards, in
        bounded batches.
        """
        book = Book(
            # Already bounded, over one list both writers walk, so a column
            # added here cannot skip the guard by being forgotten.
            #
            # **This line is not type checked and must not be described as
            # such**, and the reason is `Book.__init__`, which is
            # `(self, **kwargs)` from SQLAlchemy's instrumentation: spelling the
            # columns out as keywords would be no more checked than this walk.
            # What bounds which columns a record can reach from here is the tuple
            # and the `ast` pass over this module that reads it, named at `Stored`.
            **{name: getattr(stored, name) for name in _MARC_RECORD_FIELDS},
            isbn=stored.isbn,
            added_by_user_id=self._member_id,
            ownership=OwnershipStatus.UNKNOWN,
        )
        self._db.add(book)
        self._db.flush()
        index.remember(book)
        return book


def _links_to_add(stored: Sequence[OnlineLink], links: Sequence[Link]) -> list[Link]:
    """The links `_keep_links` appends to `stored` as loaded, one per new URL.

    **The one place that says whether a row is added**: the check before the lock
    reads whether this is empty, and the append loop writes only what it
    returns, so the two cannot disagree about a row. A URL already stored, a
    repeat within `links` and one past the per Book cap are not in it.
    """
    held = {row.url for row in stored}
    room = MAX_ONLINE_LINKS_PER_BOOK - len(stored)
    adds: list[Link] = []
    for link in links:
        if len(adds) >= room:
            break
        if link.url not in held:
            held.add(link.url)
            adds.append(link)
    return adds


def _keep_links(book: Book, links: Sequence[Link], db: Session) -> None:
    """Add the record's online links the Book lacks, up to the per Book cap.

    A matched Book gains them as a new one does, as with the headings: a link
    is catalogue evidence, not a value a member typed over. Never fetched.

    **Counted under `database.hold_book_ceilings`**, the lock a merge takes for
    its keeper: a matched Book is one a merge can be carrying links onto, and
    counted beside it the Book lands past the cap. So its links are re-read
    after the lock, flushed first so the ones an earlier record in this import
    added are among them.

    **Only when the loaded links show one this call would add**, for the
    heading writer's reason (`classifications.add_headings`): the lock holds the
    Book against every edit until this import's one commit. Stale, the check
    only makes this call add less, and every append below follows the lock.
    """
    if not _links_to_add(book.online_links, links):
        return
    hold_book_ceilings(db, book.id)
    db.flush()
    db.refresh(book, ["online_links"])
    for link in _links_to_add(book.online_links, links):
        book.online_links.append(
            OnlineLink(url=link.url, label=link.label, relation=link.relation)
        )


def _fill_marc_gaps(book: Book, stored: Stored) -> None:
    """Add what the incoming record knows and this catalogue does not.

    Never overwrites: see `_MARC_GAP_FIELDS`. Takes a `Stored`, like every other
    reader of a record here, so a matched Book cannot be given a value the create
    path would have cut. What counts as a gap is `evidence`'s.
    """
    evidence.fill_gaps(
        book, {attribute: getattr(stored, attribute) for attribute in _MARC_GAP_FIELDS}
    )


# ── OPDS ──────────────────────────────────────────────────────────────────────
#
# A third reader on the same application, and the one whose records carry least.
# `csv_import.py` reads a service's export of somebody's shelf, `marc.py` reads
# a library's export of its catalogue, and `opds.py` reads a member's own
# server. What that server serves, measured across seven of them, is a title and
# an author and nothing else: no identifier of any kind.
#
# So this importer asserts one thing the other two cannot and reads two fields
# the other two also read. **The assertion is ownership.** A Goodreads export
# says what somebody read and a MARC file says what another institution holds;
# a member's own library server says what that member has. That is the whole
# value of the route, and it is why `_create` below arrives at OWNED where
# `MarcImport._create` arrives at UNKNOWN.
#
# **The matching rule is the CSV importer's and not the MARC one's**, by the
# owner's instruction of 2026-09-05: `recognition.Source.READING_HISTORY`, ISBN
# where one exists, then the title. Do not invent a third.


#: The columns an OPDS record can fill on a Book it matched.
#:
#: **One name long, and the shortness is the measurement rather than an
#: oversight.** `_MARC_GAP_FIELDS` has nine because a MARC record carries nine;
#: an OPDS entry carries a title, which is never a gap because it is what
#: matched, an author, and an ISBN, which `_fill_opds_gaps` does not write
#: because `books.isbn` is unique across the whole table and filling it can
#: raise on a row this member cannot see. Ownership is filled and is not here,
#: because it is not a nullable column: see `_fill_opds_gaps`.
_OPDS_GAP_FIELDS: Final = ("author",)


class OpdsImport:
    """One walk of one OPDS feed, applied to the Library as one Member.

    Separate from `MarcImport` for the reason that separates that one from
    `Import`, said about a different column: **the two do not agree about
    ownership, and they must not.** A MARC file is another institution's
    catalogue and its records arrive UNKNOWN, to be confirmed by a person. An
    OPDS feed is the member's own server and its entries are the closest thing
    this application has to evidence of possession.

    The viewer is fixed at construction, as in both other importers: what is
    read is what this Member may see, and a created Book is attributed to them.

    **Nothing personal is written.** A feed carries no reading status, no rating
    and no review, so there is no `user_books` row here and no `Reading.by` call.
    """

    __slots__ = ("_db", "_member_id")

    def __init__(self, db: Session, member_id: int) -> None:
        self._db = db
        self._member_id = member_id

    @classmethod
    def for_member(cls, db: Session, member_id: int) -> OpdsImport:
        return cls(db, member_id)

    def apply(
        self, records: Sequence[Record], *, create_missing: bool = True
    ) -> ImportResultOut:
        """Apply every record the walk found, and report what happened.

        **`create_missing` defaults to true, as on the MARC path and against the
        CSV one**, and the reason is what the source means. A reading history is
        mostly books the household does not own, so creating them by default
        would fill the shelf with books nobody has. A member's own library
        server lists what they have, and a sync that adds none of it has synced
        nothing.

        Commits once at the end. One entry that cannot be acted on is counted
        and skipped: a library of thousands is not uniformly clean, and failing
        the sync on entry 412 gives nobody anything to act on.
        """
        # The CSV importer's ladder, by the owner's instruction of 2026-09-05.
        index = recognition.Index.build(
            self._db, self._member_id, recognition.Source.READING_HISTORY
        )
        tally = _Tally()

        with _a_vanished_match_met_another_change(self._db, self._member_id, tally):
            for record in records:
                self._apply_one(record, index, tally, create_missing)
            self._db.commit()

        return ImportResultOut(
            rows_read=len(records),
            matched=tally.matched,
            created=tally.created,
            # Nothing personal is written, so nothing personal changed. Reported
            # as zero rather than omitted, for `MarcImport.apply`'s reason: the
            # field is on the shared result model.
            statuses_updated=0,
            # Entries with no title, plus entries whose ISBN belongs to a Book
            # this Member cannot see. Counted together for `Import.apply`'s
            # reason: separating them would be an oracle for "does a Book with
            # this ISBN exist in this house", which the 404-not-403 rule
            # withholds.
            skipped=tally.unmatched_private + tally.skipped_untitled,
            unmatched_titles=tally.unmatched,
            in_trash=tally.in_trash,
            in_trash_titles=tally.in_trash_titles,
            ambiguous=tally.ambiguous,
            ambiguous_titles=tally.ambiguous_titles,
        )

    def _apply_one(
        self,
        record: Record,
        index: recognition.Index,
        tally: _Tally,
        create_missing: bool,
    ) -> None:
        # Bounded once, before anything reads a value, for `stored_record`'s
        # reason: matching on the incoming value and storing the bounded one
        # means the same feed synced twice can fail to find itself.
        stored = stored_record(record)
        title = stored.title
        if not title:
            # **What reaches here is a record whose title `catalogue.Record`
            # dropped**, not one `within_bounds` truncated: `_drop_unstorable`
            # in `Record.__post_init__` sets a scalar the column cannot hold to
            # None rather than cutting it, because half a title is an assertion
            # nobody made. `opds.entry_record` refuses an entry whose `<title>`
            # is missing or blank, so that is not this arm either.
            #
            # Without it an empty title reaches `recognise` and keys as the
            # empty string, which is what every other untitled row keys as, so
            # the entry would be matched against every untitled Book here.
            # The stated reason here was `within_bounds` truncating to `""`,
            # which it cannot do: a critic read the mechanism rather than the
            # comment. It then said the matcher would raise `AttributeError`,
            # which stopped being true when the title predicate stopped
            # reaching for a method on its argument. **A guard justified by a
            # crash outlives the crash**, and what it is really worth is above:
            # silence, not a traceback. Stated without naming what the
            # predicate does with a missing title, because its signature does
            # not accept one and this arm is what keeps that true.
            tally.skipped_untitled += 1
            return

        # The return is dropped because this importer has no tail. It is the
        # one of the three with nothing to run after the branch, and that is
        # the whole of the difference.
        _settle_one(
            index.recognise(title=title, author=stored.author, isbn=stored.isbn),
            tally,
            load=lambda book_id: self._db.get_one(Book, book_id),
            # A title from the member's own server, so reporting it back to
            # that member discloses nothing they did not already have. Known
            # non-empty: the arm above returned on anything else.
            unmatched_title=title,
            create=lambda: self._create(stored, index),
            fill_gaps=lambda matched: _fill_opds_gaps(matched, stored),
            create_missing=create_missing,
        )

    def _create(self, stored: Stored, index: recognition.Index) -> Book:
        """Add a Book the member's server lists and this Library does not hold.

        **`ownership=OWNED`, where both other importers arrive at UNKNOWN**, and
        the difference is whose catalogue is speaking. A Goodreads export is a
        reading history and a MARC file is another institution's holdings;
        neither is evidence that this household has the book. A member's own
        library server is exactly that evidence, and an import that arrived
        UNKNOWN would make the one thing this route can establish something a
        person has to confirm by hand for every book they own.

        **No cover is fetched**, for `MarcImport._create`'s reason: a fetch per
        record over a whole library is thousands of round trips holding one
        request open. `POST /api/books/covers/backfill` does it afterwards.
        """
        book = Book(
            title=stored.title,
            author=stored.author,
            isbn=stored.isbn,
            added_by_user_id=self._member_id,
            ownership=OwnershipStatus.OWNED,
        )
        self._db.add(book)
        self._db.flush()
        index.remember(book)
        return book


def _fill_opds_gaps(book: Book, stored: Stored) -> None:
    """Add what the member's server knows and this catalogue does not.

    **Never overwrites, and ownership is the one that needed a rule.** The other
    columns are filled where `evidence.is_empty`; `books.ownership` is never empty,
    so "the gap" has to be named, and it is `UNKNOWN`, which is the value
    `enums.OwnershipStatus` documents as "nobody has answered the question". A
    Book somebody set to NOT_OWNED is left alone: they answered, and a feed does
    not overrule a person.

    The ISBN is deliberately not filled even when it is a gap. `books.isbn` is
    unique across the whole table for any row nobody has declared a copy, so
    writing one onto a matched Book can raise on a row this Member cannot see,
    and that raise aborts the transaction and costs the whole sync. The record
    that carried it matched on its title, which is the weaker key, so this is
    also the case where the ISBN is least likely to be about the same book.
    """
    evidence.fill_gaps(
        book, {attribute: getattr(stored, attribute) for attribute in _OPDS_GAP_FIELDS}
    )
    if book.ownership == OwnershipStatus.UNKNOWN:
        book.ownership = OwnershipStatus.OWNED
