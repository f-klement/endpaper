"""Bulk import from other services.

Always from a file rather than an API. Goodreads retired theirs in December
2020, LibraryThing never had a general one, and asking somebody for their
password to a service we do not control is not a thing to build. An export is
the route that exists everywhere, and the only one that does not ask for a
credential.

The parser reads whatever the file turns out to be: see `backend/csv_import.py`
for how the columns are guessed and which services were used to write the
guess list.
"""

import logging
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime, time
from typing import Annotated

from fastapi import APIRouter, File, HTTPException, Query, UploadFile
from sqlalchemy import func

import csv_import
from config import MAX_UPLOAD_BYTES
from dependencies import CurrentUser, DbSession
from enums import OwnershipStatus, ReadStatus, TagCategory
from models import Book, Note, Tag, UserBook
from ratelimit import import_limiter
from schemas import ImportPreviewOut, ImportPreviewRow, ImportResultOut
from schemas.tag import MAX_TAG_NAME
from shelf import Shelf, whole_table_for_uniqueness

logger = logging.getLogger("endpaper.imports")

router = APIRouter(prefix="/api/imports", tags=["imports"])


MAX_UNMATCHED_REPORTED = 50


def _read_upload(file: UploadFile) -> bytes:
    """The uploaded bytes, read synchronously.

    `UploadFile.file` is the underlying blocking file object. Reading it here
    rather than awaiting `file.read()` is what lets both handlers be `def`,
    which is the whole point: see the note on `import_csv`.
    """
    content = file.file.read(MAX_UPLOAD_BYTES + 1)
    if len(content) > MAX_UPLOAD_BYTES:
        raise HTTPException(
            status_code=413,
            detail=f"That file is larger than {MAX_UPLOAD_BYTES // (1024 * 1024)} MB.",
        )
    if not content:
        raise HTTPException(status_code=400, detail="That file is empty.")
    return content


def _parse(content: bytes, overrides: dict[str, str] | None = None) -> csv_import.ParsedFile:
    try:
        return csv_import.parse(content, overrides)
    except csv_import.ImportError_ as error:
        # A readable explanation beats "0 books imported" for somebody who
        # picked the wrong file.
        raise HTTPException(status_code=400, detail=str(error)) from error


@router.post("/preview", response_model=ImportPreviewOut)
def preview_import(
    db: DbSession,
    current_user: CurrentUser,
    file: Annotated[UploadFile, File()],
    overrides: Annotated[
        str | None,
        Query(description="Correct a guessed column, as field=header pairs"),
    ] = None,
) -> ImportPreviewOut:
    """Read a file and report what it turned out to be, writing nothing.

    A column guessed wrong is invisible until after the import, and after the
    import is too late: undoing it means finding and deleting a few hundred
    books. So the mapping is shown first, against the file's real header list,
    with the first few rows as the parser actually read them.
    """
    # The same overrides the import will use. Without them a reader who
    # corrects a mapping cannot see the corrected result, which defeats the
    # point of looking before anything is written.
    parsed = _parse(_read_upload(file), _parse_overrides(overrides))

    return ImportPreviewOut(
        headers=parsed.headers,
        mapping=parsed.mapping,
        delimiter=parsed.delimiter,
        total_rows=len(parsed.rows),
        skipped=parsed.skipped,
        # A count of this file rather than "often hundreds", so the warning
        # about bringing tags across is about the file in hand.
        distinct_tags=len({tag.lower() for row in parsed.rows for tag in row.tags}),
        rows=[
            ImportPreviewRow(
                title=row.title,
                author=row.author,
                isbn=row.isbn,
                status=row.status.value if row.status else None,
            )
            for row in parsed.rows[: csv_import.PREVIEW_ROWS]
        ],
    )


@router.post("/csv", response_model=ImportResultOut)
def import_csv(
    db: DbSession,
    current_user: CurrentUser,
    file: Annotated[UploadFile, File()],
    create_missing: Annotated[
        bool, Query(description="Add books from the export that are not in the catalogue")
    ] = False,
    apply_tags: Annotated[
        bool, Query(description="Create the file's tags and put them on the books")
    ] = False,
    overrides: Annotated[
        str | None,
        Query(
            description=(
                "Correct a guessed column, as field=header pairs separated by "
                "commas, e.g. title=Book Name,author=Written By"
            )
        ),
    ] = None,
) -> ImportResultOut:
    """Apply a library export from Goodreads, LibraryThing, StoryGraph, Libib
    or anything else with a title column.

    **Declared `def`, not `async def`, and that is load bearing.** Everything
    below is blocking: SQLAlchemy has no async here. An `async` handler runs on
    the event loop, so a running import stops the whole application answering.
    Measured on a 3000 row file: `GET /api/books` went from 7ms to **14.4
    seconds**, and exactly one such request completed for the duration.
    FastAPI runs a `def` handler in a threadpool instead, which costs nothing
    and keeps the app alive while a library comes across.

    Statuses are **personal**, so this only ever writes the importing member's
    own `user_books` rows. Importing your shelves does not change what anyone
    else has read, and two members can import their own exports without
    fighting over the same books.

    Books created by `create_missing` are marked `ownership=unknown`: a reading
    history is not evidence of possession. They are then confirmed together
    from the library view, which is what the bulk ownership endpoint is for.

    `apply_tags` is off by default and deliberately so. A Goodreads export's
    tag column is its shelves, which for most people is a few hundred one-off
    names, and turning all of them into tags here buries the curated list under
    somebody's filing habits from another app.
    """
    import_limiter.check(current_user.username)

    parsed = _parse(_read_upload(file), _parse_overrides(overrides))

    # Everything the loop needs to match a row, fetched once.
    #
    # Measured before this existed: a 5000 row file cost 25,001 statements and
    # 61 seconds, and profiling put only ~15% of that in SQLite. The rest was
    # SQLAlchemy compiling the same three queries five thousand times each. The
    # catalogue is a library's, so holding two dicts of it is a few hundred
    # kilobytes.
    index = _CatalogueIndex.build(db, current_user.id)

    matched = 0
    updated = 0
    created = 0
    unmatched: list[str] = []
    unmatched_private = 0
    tag_cache: dict[str, Tag] = {}
    new_tags = 0

    for row in parsed.rows:
        book = index.find(db, row)

        if book is None and create_missing and index.isbn_is_taken(row.isbn):
            # The ISBN belongs to a book this member cannot see, which means
            # somebody else's private one. Creating it raises on the unique
            # index, and that raise is two problems at once: it aborts the
            # whole transaction, so a 5000-row import silently writes nothing,
            # and the 500-versus-200 difference is a clean oracle for "does a
            # book with this ISBN exist in this house", which is exactly what
            # the 404-not-403 rule exists to withhold.
            #
            # Counted as unmatched, and the title is NOT reported back: naming
            # it would disclose the row the caller is not allowed to see.
            unmatched_private += 1
            continue

        if book is None and create_missing:
            # No cover is fetched here, and that is deliberate. Every other add
            # path stores one on the way in (`routers/books._store_cover`); this
            # one runs over thousands of rows inside a single request, and a
            # fetch per row would be thousands of round trips holding the
            # request open until a proxy gives up on it. The books arrive
            # without covers and `POST /api/books/covers/backfill` fills them
            # in afterwards, concurrently and in bounded batches, which is the
            # same work without a request waiting on it.
            book = Book(
                title=row.title,
                author=row.author,
                isbn=row.isbn,
                publisher=row.publisher,
                year=row.year,
                page_count=row.pages,
                format=row.format,
                added_by_user_id=current_user.id,
                # An export says what someone read, not what is on the shelf.
                # Marking these OWNED would assert something nobody checked,
                # so they arrive unverified and are confirmed in bulk
                # afterwards.
                ownership=OwnershipStatus.UNKNOWN,
            )
            db.add(book)
            db.flush()
            index.remember(book)
            created += 1
        elif book is None:
            # Capped: a 5000-book export with nothing matching would otherwise
            # return a response larger than the file that produced it.
            if len(unmatched) < MAX_UNMATCHED_REPORTED:
                unmatched.append(row.title)
            continue
        else:
            matched += 1
            _fill_gaps(book, row)

        if apply_tags and row.tags:
            new_tags += _apply_tags(db, book, row.tags, tag_cache, new_tags)

        if _apply_row(db, index, book_id=book.id, user_id=current_user.id, row=row):
            updated += 1

        if row.notes:
            _import_review(db, index, book_id=book.id, user_id=current_user.id, text=row.notes)

    db.commit()

    return ImportResultOut(
        rows_read=len(parsed.rows),
        matched=matched,
        created=created,
        statuses_updated=updated,
        # Rows whose ISBN belongs to somebody else's private book are counted
        # with the ones that had no title: both are rows this import could not
        # act on, and separating them out would be the oracle again.
        skipped=parsed.skipped + unmatched_private,
        unmatched_titles=unmatched,
    )


@dataclass
class _CatalogueIndex:
    """The catalogue in memory, for the duration of one import.

    Three lookups happen per row and each was its own query: the book by ISBN,
    the book by title, and this member's reading status. That is fine for one
    row and is 25,000 statements for a Goodreads export.

    `taken_isbns` covers **every** book, invisible ones included, because
    `books.isbn` is unique across the whole table for any row nobody has
    declared a copy. That is the check that keeps
    a row whose ISBN belongs to somebody else's private book from raising on
    the index and taking the whole import with it.

    It stays that broad now that deliberate copies suspend the unique index for
    their ISBN, and the reason has changed rather than gone away: an export
    listing a book twice must not silently mint a second copy. A copy is
    something a person adds on purpose, one press at a time, never something a
    CSV file decides a library holds.
    """

    by_isbn: dict[str, int]
    by_title: dict[str, int]
    taken_isbns: set[str]
    statuses: dict[int, UserBook]
    notes: set[int]

    @classmethod
    def build(cls, db: DbSession, user_id: int) -> _CatalogueIndex:
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
            # `whole_table_for_uniqueness`: the ISBN is unique across the
            # whole table, so an import row that collides with a book this
            # member cannot see still collides. Filtering here would let the
            # import write a row the database then refuses, turning a reported
            # conflict into a 500.
            taken_isbns={
                isbn
                for (isbn,) in whole_table_for_uniqueness(db, Book.isbn).filter(
                    Book.isbn.isnot(None)
                )
            },
            statuses={
                row.book_id: row
                for row in db.query(UserBook).filter(UserBook.user_id == user_id)
            },
            notes={
                book_id
                for (book_id,) in db.query(Note.book_id).filter(Note.user_id == user_id)
            },
        )

    def find(self, db: DbSession, row: csv_import.ImportRow) -> Book | None:
        """Match an exported row to a book already in the catalogue.

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
        """Keep a freshly created book findable by later rows of the same file.

        An export listing one book twice would otherwise create it twice, or
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


def _parse_overrides(raw: str | None) -> dict[str, str]:
    """`title=Book Name,author=Written By` into a mapping.

    A pair with no `=` is skipped rather than raising. This parameter exists to
    rescue an import, and refusing the whole file over one malformed pair would
    be the opposite of that.
    """
    if not raw:
        return {}
    overrides: dict[str, str] = {}
    for pair in raw.split(","):
        field_name, separator, header = pair.partition("=")
        if separator and field_name.strip() and header.strip():
            overrides[field_name.strip()] = header.strip()
    return overrides


def _fill_gaps(book: Book, row: csv_import.ImportRow) -> None:
    """Add what the export knows and the catalogue does not.

    Never overwrites. A book already here was scanned from a real catalogue or
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


def _apply_tags(
    db: DbSession,
    book: Book,
    names: list[str],
    cache: dict[str, Tag],
    invented_so_far: int,
) -> int:
    """Put the file's tags on the book, inventing the new ones. Returns how
    many it invented.

    Cached by name across the whole import: a five hundred row export shares a
    handful of tags, and looking each one up per row is five hundred queries
    for the same answer.

    **Two caps, and both were measured rather than guessed.** A 12 KB file of
    200 rows created 4032 library wide tags and put 4000 of them on one book,
    because the only limit was per row. Past the caps this stops inventing
    rather than failing: the books in the file are still worth having.

    The name is truncated **before** the cache key and the lookup. Truncating
    only at the insert made two tags sharing their first hundred characters
    both miss the cache, both miss the query, and the second insert violate the
    unique index, which took the whole import down with it.
    """
    existing_ids = {tag.id for tag in book.tags}
    invented = 0

    for raw in names:
        if len(existing_ids) >= csv_import.MAX_TAGS_PER_BOOK:
            break

        name = raw[:MAX_TAG_NAME]
        key = name.lower()

        tag = cache.get(key)
        if tag is None:
            tag = db.query(Tag).filter(func.lower(Tag.name) == key).first()
            if tag is None:
                if invented_so_far + invented >= csv_import.MAX_NEW_TAGS_PER_IMPORT:
                    continue
                tag = Tag(name=name, category=TagCategory.CUSTOM, is_predefined=False)
                db.add(tag)
                db.flush()
                invented += 1
            cache[key] = tag

        if tag.id not in existing_ids:
            book.tags.append(tag)
            existing_ids.add(tag.id)

    return invented


def _import_review(
    db: DbSession, index: _CatalogueIndex, *, book_id: int, user_id: int, text: str
) -> None:
    """Keep the review the export carried, as this member's note.

    The parser has been reading "My Review" all along and the import threw it
    away, which is the same waste the rating and the finish date used to be.
    A review is personal, and `Note` is already per member and per book, so it
    lands there rather than on the book itself.

    Skipped when this member already has a note on the book: an import is not
    a reason to append the same paragraph on every re-run.
    """
    if book_id in index.notes:
        return
    db.add(Note(book_id=book_id, user_id=user_id, content=text[:5000]))
    index.notes.add(book_id)


def _apply_row(
    db: DbSession,
    index: _CatalogueIndex,
    *,
    book_id: int,
    user_id: int,
    row: csv_import.ImportRow,
) -> bool:
    """Write this member's status, rating and finish date. True if anything changed.

    Existing local values are never overwritten: somebody who has already rated
    a book here has expressed a more recent opinion than an export taken from
    another service. The import fills gaps, on the same principle as metadata
    enrichment.
    """
    if row.status is None and row.rating is None and row.date_read is None:
        # Nothing personal in this row. A file that is a plain book list
        # should not leave an "unread" marker on every book it touched.
        return False

    existing = index.statuses.get(book_id)

    if existing is None:
        existing = UserBook(user_id=user_id, book_id=book_id)
        db.add(existing)
        index.statuses[book_id] = existing
        changed = True
    else:
        changed = row.status is not None and ReadStatus(existing.status) is not row.status

    if row.status is not None:
        existing.status = row.status

    if row.rating is not None and existing.rating is None:
        existing.rating = row.rating
        changed = True

    # Only for books the export says were finished. A date on a
    # currently-reading row would be a finish date for a book nobody finished.
    if (
        row.status is ReadStatus.READ
        and row.date_read is not None
        and existing.finished_at is None
    ):
        existing.finished_at = datetime.combine(row.date_read, time.min)
        changed = True

    return changed
