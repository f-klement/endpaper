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
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import datetime, time

from sqlalchemy.orm import Session

import csv_import
from enums import OwnershipStatus, ReadStatus, TagCategory
from models import Book, Note, Tag
from reading import Reading, Records
from schemas import ImportResultOut
from schemas.tag import MAX_TAG_NAME
from shelf import Shelf, whole_table_for_uniqueness

logger = logging.getLogger("endpaper.importing")

#: How many unmatched titles come back in the response.
#:
#: A 5000 book export with nothing matching would otherwise return a response
#: larger than the file that produced it.
MAX_UNMATCHED_REPORTED = 50


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
            # `whole_table_for_uniqueness`: the ISBN is unique across the whole
            # table, so an import row that collides with a Book this Member
            # cannot see still collides. Filtering here would let the import
            # write a row the database then refuses, turning a reported
            # conflict into a 500.
            taken_isbns={
                isbn
                for (isbn,) in whole_table_for_uniqueness(db, Book.isbn).filter(
                    Book.isbn.isnot(None)
                )
            },
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
