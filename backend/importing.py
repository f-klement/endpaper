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
unmatched, and its title is never reported.** Creating it would raise on the
unique index, and that raise is two problems at once: it aborts the whole
transaction, so a 5000 row import silently writes nothing, and the 500 against
200 difference is a clean oracle for "does a Book with this ISBN exist in this
house", which is exactly what the 404-not-403 rule withholds. `skipped` counts
it together with the rows that had no title, because separating them out would
be the oracle again by another route.
"""

import logging
import re
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import datetime, time
from typing import Any, Final

import annotated_types
from sqlalchemy.orm import Session

import csv_import
import marc
from catalogue import Record
from classifications import add_headings, bounded_headings
from enums import OwnershipStatus, ReadStatus, TagCategory
from models import Book, Note, Tag
from reading import Reading, Records
from schemas import ImportResultOut
from schemas.book import BookCreate
from schemas.tag import MAX_TAG_NAME
from shelf import Shelf, whole_table_for_uniqueness

logger = logging.getLogger("endpaper.importing")

#: How many unmatched titles come back in the response.
#:
#: A 5000 book export with nothing matching would otherwise return a response
#: larger than the file that produced it.
MAX_UNMATCHED_REPORTED = 50


def _taken_isbns(db: Session) -> set[str]:
    """Every ISBN in the Library, whoever can see the Book carrying it.

    **One of the two named ways past a viewer, and the only one this module
    uses.** The ISBN is unique across the whole table, so an incoming row that
    collides with a Book this Member cannot see still collides. Filtering to the
    visible rows would let the import write a row the database then refuses, and
    that refusal aborts the transaction: a five thousand row file would write
    nothing at all, with a 500, because of one Private Book somebody else owns.

    **One call site, shared by both index builders.** It was two, one per
    importer, which is two ways past the viewer where the rule is one. Counted
    by `tests/test_shelf.py::test_the_named_ways_past_a_viewer_have_the_callers_they_claim`,
    so adding a third is allowed and doing it quietly is not.

    What the caller must not do with the answer is report a title from it: see
    this module's docstring. Knowing an ISBN is taken is what stops the 500;
    saying whose Book it is would be the oracle the 404-not-403 rule withholds.
    """
    return {
        isbn
        for (isbn,) in whole_table_for_uniqueness(db, Book.isbn).filter(
            Book.isbn.isnot(None)
        )
    }


@dataclass
class _CatalogueIndex:
    """The catalogue in memory, for the duration of one import.

    Three lookups happen per row and each was its own query: the Book by ISBN,
    the Book by title, and this Member's reading status. That is fine for one
    row and is 25,000 statements for a Goodreads export. Measured before this
    existed: a 5000 row file cost **25,001 statements and 61 seconds**, and
    profiling put only about 15% of that in SQLite. The rest was SQLAlchemy
    compiling the same three queries five thousand times each. The catalogue is
    a Library's, so holding two dicts of it is a few hundred kilobytes.

    **It does not make the per row cost zero, and does not claim to.** `find`
    still issues one `db.get` for a row it matched, because that is the lookup
    that has to return a live object rather than an id.

    What is measured here rather than inherited: `tests/test_importing.py`
    counts **SELECTs** and finds **one per extra matched row**. The 25,001
    figure above is the original profile and counted every statement, writes
    included, so the two are not the same unit and no total is derived from
    them here. The claim this module makes is the slope, and the slope is one.

    `taken_isbns` covers **every** Book, invisible ones included, because
    `books.isbn` is unique across the whole table for any row nobody has
    declared a copy. That is the check that keeps a row whose ISBN belongs to
    somebody else's Private Book from raising on the index and taking the whole
    import with it.

    It stays that broad now that deliberate copies suspend the unique index for
    their ISBN, and the reason has changed rather than gone away: an export
    listing a Book twice must not silently mint a second copy. A copy is
    something a person adds on purpose, one press at a time, never something a
    CSV file decides a Library holds.
    """

    by_isbn: dict[str, int]
    by_title: dict[str, int]
    taken_isbns: set[str]
    statuses: Records
    notes: set[int]

    @classmethod
    def build(cls, db: Session, user_id: int) -> _CatalogueIndex:
        visible = (
            Shelf.seen_by(db, user_id)
            .select(Book.id, Book.isbn, Book.title)
            .order_by(Book.id)
            .all()
        )
        return cls(
            # First wins, and ordered so "first" means something. Copies made
            # two visible rows able to share an ISBN, and an import row that
            # matches one must attach its status and its notes to the same copy
            # on every run, not to whichever the query happened to return.
            by_isbn=_first_wins((isbn, book_id) for book_id, isbn, _title in visible if isbn),
            # First wins, matching the old `.first()`: two editions of one
            # title collide, which is acceptable for a status and would not be
            # for anything destructive.
            by_title=_first_wins((title.lower(), book_id) for book_id, _isbn, title in visible),
            taken_isbns=_taken_isbns(db),
            # The Member's whole reading record rather than the matched Books':
            # which Books a 5,000 row file will match is not known until it has
            # been walked, and per row would be one SELECT per line.
            statuses=Reading.by(db, user_id).everything(),
            notes={
                book_id
                for (book_id,) in db.query(Note.book_id).filter(Note.user_id == user_id)
            },
        )

    def find(self, db: Session, row: csv_import.ImportRow) -> Book | None:
        """Match an exported row to a Book already in the catalogue.

        ISBN first, since it is unambiguous. The title fallback is deliberate
        and imperfect for the reason above.
        """
        book_id = None
        if row.isbn:
            book_id = self.by_isbn.get(row.isbn)
        if book_id is None:
            book_id = self.by_title.get(row.title.lower())
        return db.get(Book, book_id) if book_id is not None else None

    def isbn_is_taken(self, isbn: str | None) -> bool:
        return bool(isbn) and isbn in self.taken_isbns

    def remember(self, book: Book) -> None:
        """Keep a freshly created Book findable by later rows of the same file.

        An export listing one Book twice would otherwise create it twice, or
        raise on the ISBN index the second time.
        """
        if book.isbn:
            self.by_isbn[book.isbn] = book.id
            self.taken_isbns.add(book.isbn)
        self.by_title.setdefault(book.title.lower(), book.id)


def _first_wins(pairs: Iterable[tuple[str, int]]) -> dict[str, int]:
    result: dict[str, int] = {}
    for key, value in pairs:
        result.setdefault(key, value)
    return result


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
        tag_cache = self._tags_by_folded_name() if apply_tags else {}

        for row in parsed.rows:
            self._apply_one(row, index, tally, tag_cache, create_missing, apply_tags)

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
            unmatched_titles=tally.unmatched,
        )

    def _tags_by_folded_name(self) -> dict[str, Tag]:
        """Every Tag in the Library, keyed the way `_apply_tags` looks one up.

        **Read once here rather than queried per unseen name, and the reason is
        correctness before it is cost.** The per-name query was
        `func.lower(Tag.name) == key`, which folds in SQLite, against a `key`
        folded in Python. Those are not the same function: SQLite's `lower()`
        is ASCII only. Measured, `lower('Ästhetik')` is `'Ästhetik'` in SQLite
        and `'ästhetik'` in Python, so a stored Tag carrying a non-ASCII
        capital never matched, the import decided it was new, and the insert
        hit the binary `unique=True` on `tags.name` with a name already there.
        That raises `IntegrityError` **and takes the whole file with it**: a
        member with one German shelf name imported nothing, every time, with a
        500.

        Folding both sides in Python removes the mismatch by removing the
        second folder. It also turns one query per unseen name into one query
        per import.

        Ordered by id, and **first wins**, which is `_first_wins` a hundred lines
        above and `routers/books.create_tag` doing the same thing. Two Tags
        differing only in case are reachable on any database that met the bug
        this replaced, because the old `create_tag` created exactly that pair:
        the lookup missed and the binary index allowed both.

        Stability alone is not enough there, and that is the trap. A dict
        comprehension over the same ordering is equally stable and keeps the
        **last** key written, so the import resolved such a pair to the highest
        id while `create_tag` resolved it to the lowest. Measured on a pair at
        ids 106 and 107: the import picked 107 and the route picked 106. Both
        stable, on opposite ends, and both docstrings claimed the ordering was
        what made them agree.
        """
        folded: dict[str, Tag] = {}
        for tag in self._db.query(Tag).order_by(Tag.id).all():
            folded.setdefault(tag.name.lower(), tag)
        return folded

    def _apply_one(
        self,
        row: csv_import.ImportRow,
        index: _CatalogueIndex,
        tally: _Tally,
        tag_cache: dict[str, Tag],
        create_missing: bool,
        apply_tags: bool,
    ) -> None:
        """One row: match it, maybe create it, then write what is personal."""
        book = index.find(self._db, row)

        if book is None and create_missing and index.isbn_is_taken(row.isbn):
            # The ISBN belongs to a Book this Member cannot see, which means
            # somebody else's Private one. See this module's docstring: the
            # title is deliberately not reported.
            tally.unmatched_private += 1
            return

        if book is None and create_missing:
            book = self._create(row, index)
            tally.created += 1
        elif book is None:
            if len(tally.unmatched) < MAX_UNMATCHED_REPORTED:
                tally.unmatched.append(row.title)
            return
        else:
            tally.matched += 1
            _fill_gaps(book, row)

        if apply_tags and row.tags:
            self._apply_tags(book, row.tags, tag_cache, tally)

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
        index.remember(book)
        return book

    def _apply_tags(
        self, book: Book, names: list[str], cache: dict[str, Tag], tally: _Tally
    ) -> None:
        """Put the file's tags on the Book, inventing the new ones.

        Takes the tally rather than the count so far and a return value: the
        budget spent is read and written in one place instead of being threaded
        out of the caller and back in.

        The cache is seeded once by `_tags_by_folded_name` and there is no
        per-name query left. There used to be: a five hundred row export shares
        a handful of tags, and looking each one up per row was five hundred
        queries for the same answer.

        **Two caps, and both were measured rather than guessed.** A 12 KB file
        of 200 rows created **4032** Library wide tags and put 4000 of them on
        one Book, because the only limit was per row. Past the caps this stops
        inventing rather than failing: the Books in the file are still worth
        having.

        The name is truncated **before** the cache key. Truncating only at the
        insert made two tags sharing their first hundred characters both miss
        the cache, and the second insert violate the unique index, which took
        the whole import down. That was one instance of the class the fold
        above is the other one of.
        """
        existing_ids = {tag.id for tag in book.tags}

        for raw in names:
            if len(existing_ids) >= csv_import.MAX_TAGS_PER_BOOK:
                break

            name = raw[:MAX_TAG_NAME]
            key = name.lower()

            tag = cache.get(key)
            if tag is None:
                # Genuinely new: the cache was seeded from the whole table, so
                # a miss here is a miss in the database. See
                # `_tags_by_folded_name` for why there is no second lookup.
                if tally.new_tags >= csv_import.MAX_NEW_TAGS_PER_IMPORT:
                    continue
                tag = Tag(name=name, category=TagCategory.CUSTOM, is_predefined=False)
                self._db.add(tag)
                self._db.flush()
                tally.new_tags += 1
                cache[key] = tag

            if tag.id not in existing_ids:
                book.tags.append(tag)
                existing_ids.add(tag.id)

    def _keep_review(self, index: _CatalogueIndex, *, book_id: int, text: str) -> None:
        """Keep the review the export carried, as this Member's note.

        The parser has been reading "My Review" all along and the import threw
        it away, which is the same waste the rating and the finish date used to
        be. A review is personal, and `Note` is already per Member and per
        Book, so it lands there rather than on the Book itself.

        Skipped when this Member already has a note on the Book: an import is
        not a reason to append the same paragraph on every re-run.
        """
        if book_id in index.notes:
            return
        self._db.add(Note(book_id=book_id, user_id=self._member_id, content=text[:5000]))
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
    new_tags: int = 0
    unmatched_private: int = 0
    #: Capped at `MAX_UNMATCHED_REPORTED` by the caller, not here: this is a
    #: tally, and where the ceiling comes from is the report's business.
    unmatched: list[str] = field(default_factory=list)


def _fill_gaps(book: Book, row: csv_import.ImportRow) -> None:
    """Add what the export knows and the catalogue does not.

    Never overwrites. A Book already here was scanned from a real catalogue or
    typed by hand, and both outrank a CSV from another service, on the same
    principle as metadata enrichment.
    """
    for attribute, value in (
        ("publisher", row.publisher),
        ("year", row.year),
        ("page_count", row.pages),
        ("format", row.format),
    ):
        if value is not None and getattr(book, attribute) is None:
            setattr(book, attribute, value)


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
# `identity_key`.


#: Words a title may start with that say nothing about which book it is.
#:
#: Taken from `routers/books._ARTICLES` when `_duplicate_key` moved here, so
#: the duplicate finder and the importer agree about what "the same book" is.
_ARTICLES: Final = ("the ", "a ", "an ", "der ", "die ", "das ", "ein ", "eine ")


def identity_key(title: str | None, author: str | None) -> str:
    """Normalise a book to something two editions of it will share.

    **The one notion of "this is the same book" in the app**, and it was two
    until this function existed: `routers/books._duplicate_key` computed it for
    the duplicate finder, and `_CatalogueIndex.by_title` matched an import row
    on a lower cased title with no author in it at all.

    That second one is the reason this is here rather than left alone. A CSV
    export is somebody's reading history and a title collision costs a reading
    status attached to the wrong edition. A MARC file is another institution's
    catalogue, and a title collision **merges two different books**: every
    library holds more than one *Selected poems*, and an import that folded
    them would be discovered by a cataloguer months later with no record of
    what was lost.

    Deliberately lossy, as it has always been. Punctuation is dropped, case is
    folded, whitespace is collapsed and a leading article is removed, because
    two catalogues spell one book six ways.

    **Only the first author**, split before normalising: `normalise` strips the
    comma, so splitting afterwards finds nothing to split on and the whole
    credit list becomes the key. "Terry Pratchett" and "Terry Pratchett, Neil
    Gaiman" are the same book credited differently on two editions.
    """

    def normalise(value: str | None) -> str:
        text = (value or "").casefold().strip()
        text = re.sub(r"[^\w\s]", "", text)
        text = re.sub(r"\s+", " ", text)
        for article in _ARTICLES:
            if text.startswith(article):
                text = text[len(article) :]
                break
        return text

    first_author = (author or "").split(",")[0]
    return f"{normalise(title)}|{normalise(first_author)}"


def bounded_fields(record: Record) -> dict[str, Any]:
    """The record as this Library will store it, computed once.

    **Matching reads this, not the record, and that is a correctness fix rather
    than a tidy-up.** The identity key is built from a title and an author; the
    column holds the truncated value; `MarcIndex.by_identity` is keyed on what
    is stored. Bounding after matching therefore meant a record with a 600
    character title never matched itself: measured end to end, importing the
    same file twice created the Book twice and the preview reported
    `already_held: 0`, which is the one number that screen exists for, wrong for
    exactly the records the new guard acts on.

    So the truncation happens once, before anything looks at the values, and
    `identity_key`, `holds`, `would_refuse`, `remember` and the column all see
    one string.

    `isbn` rides along unbounded because it is bounded already:
    `metadata._marc_isbn` returns `isbn.parse`'s output or None, which is
    thirteen digits.

    **What matching on a truncated key costs, since it is the obvious
    objection.** Two records whose titles differ only past character 500, by the
    same first author, now collide: measured, two 503 character titles agreeing
    for 500 give one key. Once stored the two are byte identical in `title` and
    `author`, so creating both would produce two Books the duplicate finder
    immediately flags as one.

    **What that costs is not nothing, and the first statement of this reason
    said it was.** It said the catalogue could not represent the difference. It
    can: `isbn`, `year` and `publisher` are columns, the two records carry
    different values in them, and all three are lost, because `_fill_marc_gaps`
    fills only where the Book has nothing. Measured on two 503 character titles
    with different ISBNs: `created: 1, matched: 1`, and the second record's ISBN
    is nowhere in the database.

    So the trade is a real one and is made deliberately. What is bought is that
    matching agrees with storage, which is the whole reason this function
    exists; what is paid is the second record's identifiers on a collision that
    needs 500 identical leading characters and the same first author. The same
    silent drop happens on **every** title and author match, truncated or not,
    and is `_fill_marc_gaps`'s never-overwrite rule rather than anything this
    truncation introduced.

    A Book already on the shelf is never truncated by this, since **no write
    path a member can reach** can put more than 500 characters in that column.
    `backup.restore` is the exception and it is why that clause is qualified: it
    inserts raw rows through `table.insert()` with no schema and no clipping, so
    an admin restoring a hand edited archive can produce one. The property still
    holds, because such a row simply fails to match and the import creates a
    duplicate: fail safe rather than fail open.
    """
    fields = {
        name: within_bounds(name, getattr(record, name))
        for name in _MARC_RECORD_FIELDS
    }
    fields["isbn"] = record.isbn
    return fields


@dataclass
class MarcIndex:
    """The catalogue keyed the two ways a MARC record is matched.

    A separate index from `_CatalogueIndex` rather than two more fields on it,
    because the two importers ask different questions and the difference is not
    a detail. A CSV row is matched on ISBN then on **title alone**, which is
    right for a reading history: the worst case is a status on the wrong
    edition of a book somebody read. A MARC record is matched on ISBN then on
    **author and title together**, because the worst case there is two
    different books folded into one catalogue entry, and every library holds
    more than one *Selected poems*.

    Built from one query over what the Member can see, like `_CatalogueIndex`,
    for the same reason: the per row lookup was one statement per row and a
    catalogue transfer is thousands of rows.
    """

    by_isbn: dict[str, int]
    by_identity: dict[str, int]
    taken_isbns: set[str]

    @classmethod
    def build(cls, db: Session, user_id: int) -> MarcIndex:
        visible = (
            Shelf.seen_by(db, user_id)
            .select(Book.id, Book.isbn, Book.title, Book.author)
            .order_by(Book.id)
            .all()
        )
        return cls(
            by_isbn=_first_wins(
                (isbn, book_id) for book_id, isbn, _title, _author in visible if isbn
            ),
            by_identity=_first_wins(
                (identity_key(title, author), book_id)
                for book_id, _isbn, title, author in visible
            ),
            taken_isbns=_taken_isbns(db),
        )

    def _matched_id(self, fields: dict[str, Any]) -> int | None:
        """The id of the Book this record is about, without loading it.

        Takes `bounded_fields`, never a `Record`: see that function for what
        matching on the unbounded values cost.
        """
        isbn = fields["isbn"]
        if isbn:
            book_id = self.by_isbn.get(isbn)
            if book_id is not None:
                return book_id
        return self.by_identity.get(identity_key(fields["title"], fields["author"]))

    def holds(self, fields: dict[str, Any]) -> bool:
        """Whether this Library already has the Book this record describes.

        **A boolean, and it costs no statement**, which is why it is not
        `find(...) is not None`. `build` selects columns rather than entities, so
        nothing is in the identity map and every `db.get` below is a real query.
        The preview asks this once per record and writes nothing: measured, 50
        held records cost 50 statements through `find` and 0 through this, and
        `marc.MAX_RECORDS` puts the ceiling at 20,000 on a route that writes
        nothing.
        """
        return self._matched_id(fields) is not None

    def would_refuse(self, fields: dict[str, Any]) -> bool:
        """Whether the import will skip this record without touching a Book.

        **The preview's headline number is wrong without this.** A record whose
        ISBN belongs to a Book this Member cannot see is neither held (it is not
        in `by_isbn`, which is built from the Shelf) nor creatable (the unique
        index would refuse it), so `_apply_one` counts it and returns. A preview
        that modelled only `holds` would promise a record the import then
        refuses, and the screen's whole job is answering what the import will do.
        """
        return not self.holds(fields) and self.isbn_is_taken(fields["isbn"])

    def find(self, db: Session, fields: dict[str, Any]) -> Book | None:
        """The Book this record is about, loaded, or None.

        `holds` is the question the preview asks and this is the one the applier
        asks: it needs the object to write to. Keep them apart, or the preview
        pays for a load it throws away.
        """
        book_id = self._matched_id(fields)
        return db.get(Book, book_id) if book_id is not None else None

    def isbn_is_taken(self, isbn: str | None) -> bool:
        return bool(isbn) and isbn in self.taken_isbns

    def remember(self, book: Book) -> None:
        """Keep a freshly created Book findable by later records of the same file.

        A catalogue export listing one work twice would otherwise create it
        twice, or raise on the ISBN index the second time and take the whole
        transfer with it.
        """
        if book.isbn:
            self.by_isbn[book.isbn] = book.id
            self.taken_isbns.add(book.isbn)
        self.by_identity.setdefault(identity_key(book.title, book.author), book.id)


def within_bounds(attribute: str, value: Any) -> Any:
    """One incoming value, held to the bound the API would hold it to.

    **The MARC importer was the one writer of these columns that bounded
    nothing.** `POST /api/books` bounds through `BookCreate`; the CSV importer
    truncates in `csv_import.parse` (`title[:500]`, `author[:500]`,
    `publisher[:255]`) and bounds its numbers in `csv_import._int`. A MARC file
    is an upload, so it is exactly as untrusted as either, and a record's values
    come out of free text subfields: `245 $n` is not a number and `264 $c` is
    not a date.

    **What that cost is not an untidy row, and both halves were measured.**

    * One 3.7 MB upload of a single record stored a 3,000,000 character title,
      a 100,000 character author and a 500,000 character description, and
      `GET /api/books` then answered 3.8 MB. `Book.title` is `String(500)`;
      SQLite does not enforce a `VARCHAR` length, so the row is kept for ever
      and `title` is selected on every listing page, every search, the CSV
      export and the backup. On an engine that does enforce it the flush raises
      mid batch and the whole transfer is lost with a 500.
    * `series_index` is `ge=0, le=1000` on every API path.
      `metadata._marc_title` reads the first digit run of `245 $n` and calls
      `float()` on it, so a ten character `$n` stores `1e9`.
      `routers/books.list_series` then computes `set(range(1, max(held) + 1))`,
      which at a measured **70.5 bytes and 0.624 seconds per million elements**
      is roughly **70 GB and ten minutes**: the container is OOM killed, again
      on the next request, for every member, until somebody finds that row.
      `year` has the same shape, `le=2200` against a four digit `264 $c`, and
      `9999` is MARC's own open ended date for a continuing resource.

    **The bounds are read off the declarations, never retyped.**
    `BookCreate.model_fields` carries the `Ge`, `Le` and `MaxLen` the API
    applies and `Book.__table__` carries the column width. A literal here would
    be a second statement of both, and a list of arms is the shape this
    repository records as wrong on every first attempt: a field added to the
    importer later inherits this without anybody remembering.

    **Both widths are consulted and the smaller wins.** They disagree today:
    `language` is `max_length=16` on `BookCreate` and `String(10)` in the
    column. SQLite enforces neither, so the disagreement is invisible until a
    database that does.

    **Strings truncate, numbers are dropped.** Truncating a title keeps the
    record, which is what a batch wants. Clamping a year of `9999` to 2200 would
    assert a date nobody supplied, so an out of range number is stored as
    absent.

    **Every field the importer writes derives a bound, and one did not.**
    `description` is a `Text` column, which reports no length, and
    `BookCreate.description` carried no `max_length`, so this returned it whole
    while the sentence above said otherwise. It was not a MARC hole:
    `POST /api/books` accepted a 200,000 character description with a 201, so
    the importer was honouring a contract that had a gap in it. `DESCRIPTION_MAX`
    closes it at the declaration, which is where the guard reads, and
    `tests/test_marc.py::TestEveryColumnTheImporterWritesIsBounded` walks
    `_MARC_RECORD_FIELDS` so a field added later cannot inherit the absence
    instead of the guard.
    """
    if value is None:
        return None

    field = BookCreate.model_fields.get(attribute)
    limits = list(field.metadata) if field is not None else []

    if isinstance(value, str):
        widths = [
            width
            for width in (
                getattr(Book.__table__.c[attribute].type, "length", None),
                *(m.max_length for m in limits if isinstance(m, annotated_types.MaxLen)),
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
#: `isbn` is deliberately absent and is bounded already: `metadata._marc_isbn`
#: returns `isbn.parse`'s output or None, which is thirteen digits.
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

#: The columns a matched Book takes from an incoming record where it has none.
#:
#: **Never an overwrite**, which is `_fill_gaps`'s rule and the same one
#: metadata enrichment follows: a Book already here was catalogued by somebody
#: who had it in their hands, and an uploaded file did not.
#:
#: Wider than the CSV importer's four, because a MARC record carries more and
#: because the fields it adds are the ones a cataloguer would otherwise retype.
#: Derived from `_MARC_RECORD_FIELDS` rather than written out again: the gap
#: filler takes everything the create path writes **except the title**, which a
#: matched Book already has by definition, since the title is half of what
#: matched it.
#:
#: **`isbn` is in neither tuple, and that is what stops a 500 rather than an
#: economy.** It is written once, on the create path, and never filled in on a
#: matched Book. Adding it here would reach this shape: a record whose ISBN
#: belongs to a Book this Member cannot see, whose title and author match one
#: they can. `MarcIndex.find` matches on the identity key, so `isbn_is_taken` is
#: never consulted, and the gap filler would then write the invisible Book's
#: ISBN onto the visible one, tripping `books.isbn`'s unique index.
#:
#: **The assignment is silent, and no lazy load can surface it**, which is the
#: first thing to know because it is the first thing a reader guesses. This
#: application's sessions come from `database.SessionLocal`, which is
#: `sessionmaker(autocommit=False, autoflush=False)`, so reading
#: `book.classifications` in `add_headings` emits its SELECT without flushing
#: anything.
#:
#: **The count of that SELECT is the tell, and it needs no traceback.** Same
#: record, same collision, one argument apart:
#:
#: | session | classifications SELECTs | raises at |
#: |---|---|---|
#: | `autoflush=False`, which is this app's | 1 | the commit |
#: | `autoflush=True`, which is SQLAlchemy's default | 0 | `add_headings` |
#:
#: One means the lazy load was issued and flushed nothing. Zero means the
#: autoflush raised **before** the SELECT was reached. So a probe that reports
#: zero is measuring a session this application never constructs, which is what
#: three seats spent five rounds not noticing.
#:
#: **So it surfaces at the next explicit flush, and which one that is depends on
#: the rest of the file.** Measured through the route, both arms:
#:
#: | file | records entered | frames |
#: |---|---|---|
#: | the collider alone | `['Stoner']` | `apply > commit > flush` |
#: | the collider, then a new record | both | `_apply_one > _create > flush` |
#:
#: So a later record that has to be created surfaces the earlier record's write
#: at **its** insert, and with nothing after the collision it waits for the
#: commit.
#:
#: The conclusion never depended on which: it is one transaction, so the whole
#: transfer writes nothing and answers 500, which is the exact failure
#: `_taken_isbns` exists to prevent by another route. The incoming ISBN is
#: dropped instead, silently, and that is the cheaper loss.
#:
#: **Written down anyway, because five statements of this mechanism were made
#: across three seats and every one was wrong**, two of them in this comment. A
#: comment naming a mechanism is what the next reader trusts **instead of
#: measuring**: "at the commit" sends somebody debugging this to the end of the
#: run, and "at the autoflush" sends them to a flush this session never
#: performs.
#:
#: It was settled by one `grep` of the session factory rather than by a sixth
#: traceback. **A measurement is only evidence about the configuration it was
#: taken under**, and every round of this argument measured the symptom while
#: none of them read `database.py:18`.
#:
#: `tests/routers/test_imports_marc.py::TestAMatchedBookNeverGainsAnIsbn` pins
#: it, because nothing else would notice the tuple gaining one entry.
_MARC_GAP_FIELDS: Final = tuple(
    name for name in _MARC_RECORD_FIELDS if name != "title"
)


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
        index = MarcIndex.build(self._db, self._member_id)
        tally = _Tally()

        for record in parsed.records:
            self._apply_one(record, index, tally, create_missing)

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
        )

    def _apply_one(
        self,
        record: Record,
        index: MarcIndex,
        tally: _Tally,
        create_missing: bool,
    ) -> None:
        # Once, before anything reads a value: matching and writing have to see
        # the same strings or a truncated record cannot match itself. See
        # `bounded_fields`.
        fields = bounded_fields(record)
        book = index.find(self._db, fields)

        if book is None and create_missing and index.isbn_is_taken(fields["isbn"]):
            tally.unmatched_private += 1
            return

        if book is None and create_missing:
            book = self._create(fields, index)
            tally.created += 1
        elif book is None:
            if len(tally.unmatched) < MAX_UNMATCHED_REPORTED:
                # A title the caller supplied in their own file, so reporting it
                # discloses nothing they did not already have.
                tally.unmatched.append(fields["title"] or "")
            return
        else:
            tally.matched += 1
            _fill_marc_gaps(book, fields)

        # After the create and after the gap fill, so a matched Book gains the
        # headings it lacked as well as a new one getting all of them.
        # `bounded_headings` drops an entry the column cannot hold and
        # `add_headings` counts what the Book already carries, so neither a
        # long caption nor a repeated import can push a Book past the ceiling.
        add_headings(book, bounded_headings(record.headings), self._db)

    def _create(self, fields: dict[str, Any], index: MarcIndex) -> Book:
        """Add a Book the file catalogues and this Library does not hold.

        **`ownership=UNKNOWN`, exactly as the CSV path does it**, and the reason
        is the same one said differently: another institution's record says that
        institution holds the book, not that this one does. Confirmed in bulk
        afterwards, which is what `POST /api/books/bulk/ownership` is for.

        **No cover is fetched**, for `Import._create`'s reason: a fetch per
        record over a whole catalogue is thousands of round trips holding one
        request open. `POST /api/books/covers/backfill` does it afterwards, in
        bounded batches.
        """
        book = Book(
            # `fields` is already bounded, over one list both writers walk, so a
            # column added here cannot skip the guard by being forgotten.
            **{name: fields[name] for name in _MARC_RECORD_FIELDS},
            isbn=fields["isbn"],
            added_by_user_id=self._member_id,
            ownership=OwnershipStatus.UNKNOWN,
        )
        self._db.add(book)
        self._db.flush()
        index.remember(book)
        return book


def _fill_marc_gaps(book: Book, fields: dict[str, Any]) -> None:
    """Add what the incoming record knows and this catalogue does not.

    Never overwrites: see `_MARC_GAP_FIELDS`. Takes the bounded fields, like
    every other reader of a record here, so a matched Book cannot be given a
    value the create path would have cut.
    """
    for attribute in _MARC_GAP_FIELDS:
        value = fields[attribute]
        if value is not None and getattr(book, attribute) is None:
            setattr(book, attribute, value)
