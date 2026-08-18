import csv
import io
import re
from collections.abc import Callable
from datetime import UTC, date, datetime
from typing import Annotated, Any

import httpx
from fastapi import APIRouter, File, HTTPException, Query, UploadFile, status
from fastapi.responses import StreamingResponse
from sqlalchemy import func, nullslast, or_
from sqlalchemy.orm import Session, joinedload, selectinload
from sqlalchemy.sql.elements import UnaryExpression

import google_books
import isbn as isbn_utils
import settings_store
from config import COVERS_DIR
from dependencies import (
    BookForOwner,
    BookForRead,
    BookForWrite,
    CurrentUser,
    DbSession,
    Paging,
)
from enums import BookSort, BulkAction, ExportFormat, OwnershipStatus, ReadStatus, SettingKey
from models import Book, Loan, Note, Tag, User, UserBook, visible_to
from schemas import (
    BookCreate,
    BookDetailsUpdate,
    BookEnrichmentOut,
    BookLookup,
    BookOut,
    BookRatingUpdate,
    BookStatusUpdate,
    BulkOwnershipResult,
    BulkOwnershipUpdate,
    BulkRequest,
    BulkResult,
    DuplicateGroup,
    GoogleBooksMatch,
    LoanOut,
    LocationOut,
    MergeRequest,
    NoteCreate,
    NoteOut,
    OwnershipUpdate,
    Page,
    PrivacyUpdate,
    SeriesOut,
    TagOut,
    UserOut,
)
from uploads import read_image_upload

router = APIRouter(prefix="/api/books", tags=["books"])

# How long to wait on Open Library / Google Books before giving up. These are
# third-party services on the request path, so the timeout is what stops a slow
# one from holding a worker open.
_LOOKUP_TIMEOUT_SECONDS = 10


# ── Metadata sources ──────────────────────────────────────────────────────────


async def _fetch_open_library(isbn: str) -> dict[str, Any] | None:
    url = f"https://openlibrary.org/isbn/{isbn}.json"
    async with httpx.AsyncClient(timeout=_LOOKUP_TIMEOUT_SECONDS, follow_redirects=True) as client:
        response = await client.get(url)
        if response.status_code != 200:
            return None
        data = response.json()

    # Author names live at /authors/{key}.json. Fetch the first one.
    author: str | None = None
    authors_list = data.get("authors", [])
    if authors_list:
        author_key = authors_list[0].get("key", "")
        async with httpx.AsyncClient(
            timeout=_LOOKUP_TIMEOUT_SECONDS, follow_redirects=True
        ) as client:
            author_response = await client.get(f"https://openlibrary.org{author_key}.json")
            if author_response.status_code == 200:
                author = author_response.json().get("name")

    publishers = data.get("publishers", [])
    publish_dates = data.get("publish_date", "")
    year_match = re.search(r"\d{4}", publish_dates) if publish_dates else None

    # description is either a plain string or {"value": ...}, depending on age.
    description_raw = data.get("description", "")
    description = (
        description_raw.get("value", "") if isinstance(description_raw, dict) else description_raw
    )

    subjects: list[str] = []
    for key in ("subjects", "subject_places", "subject_times", "subject_people"):
        for entry in data.get(key, []):
            if isinstance(entry, str):
                subjects.append(entry)
            elif isinstance(entry, dict) and "name" in entry:
                subjects.append(entry["name"])

    return {
        "isbn": isbn,
        "title": data.get("title", ""),
        "subtitle": data.get("subtitle"),
        "author": author,
        "publisher": publishers[0] if publishers else None,
        "year": int(year_match.group()) if year_match else None,
        "description": description or None,
        "cover_url": f"https://covers.openlibrary.org/b/isbn/{isbn}-L.jpg",
        "subjects": subjects,
    }


async def _fetch_google_books(isbn: str) -> dict[str, Any] | None:
    url = f"https://www.googleapis.com/books/v1/volumes?q=isbn:{isbn}"
    async with httpx.AsyncClient(timeout=_LOOKUP_TIMEOUT_SECONDS, follow_redirects=True) as client:
        response = await client.get(url)
        if response.status_code != 200:
            return None
        data = response.json()

    items = data.get("items", [])
    if not items:
        return None

    info = items[0].get("volumeInfo", {})
    isbn13 = next(
        (i["identifier"] for i in info.get("industryIdentifiers", []) if i["type"] == "ISBN_13"),
        isbn,
    )
    published = info.get("publishedDate", "")
    year_match = re.search(r"\d{4}", published) if published else None

    return {
        "isbn": isbn13,
        "title": info.get("title", ""),
        "subtitle": info.get("subtitle"),
        "author": ", ".join(info.get("authors", [])) or None,
        "publisher": info.get("publisher"),
        "year": int(year_match.group()) if year_match else None,
        "description": info.get("description"),
        "cover_url": info.get("imageLinks", {}).get("thumbnail"),
        "subjects": info.get("categories", []),
    }


def _match_subjects_to_tags(subjects: list[str], tags: list[Tag]) -> list[int]:
    """Case-insensitive substring match of source subjects against our tags."""
    if not subjects:
        return []
    subjects_blob = " | ".join(subject.lower() for subject in subjects)
    matched: list[int] = []
    for tag in tags:
        # Strip parenthetical suffixes: "Young Adult (13-18)" becomes "young adult".
        tag_core = re.sub(r"\s*\([^)]+\)", "", tag.name).strip().lower()
        if tag_core and tag_core in subjects_blob:
            matched.append(tag.id)
    return matched


# ── Serialisation ─────────────────────────────────────────────────────────────


def _loan_summary(loan: Loan) -> LoanOut:
    """A loan as it appears *inside* a book payload.

    `book` is left None deliberately: the caller is already holding the book
    this loan belongs to, and populating it would both bloat the response and
    trigger a lazy load per book.
    """
    return LoanOut(
        id=loan.id,
        book_id=loan.book_id,
        loaned_to_user_id=loan.loaned_to_user_id,
        loaned_by_user_id=loan.loaned_by_user_id,
        loaned_at=loan.loaned_at,
        returned_at=loan.returned_at,
        book=None,
        loaned_to=UserOut.model_validate(loan.loaned_to) if loan.loaned_to else None,
        loaned_by=UserOut.model_validate(loan.loaned_by) if loan.loaned_by else None,
    )


def _books_to_out(books: list[Book], current_user: User, db: Session) -> list[BookOut]:
    """Serialise a page of books, adding the two per-request fields.

    `active_loan` and `my_status` are not columns, and the obvious
    implementation queries for each of them per book, which is what made
    listing 25 books cost 53 SELECTs. Both are fetched here in one query each,
    so a page costs a constant three regardless of its size.
    """
    if not books:
        return []

    book_ids = [book.id for book in books]

    active_loans = {
        loan.book_id: loan
        for loan in db.query(Loan)
        .options(joinedload(Loan.loaned_to), joinedload(Loan.loaned_by))
        .filter(Loan.book_id.in_(book_ids), Loan.returned_at.is_(None))
        .all()
    }

    # One query for the whole page, not one per book. The row carries the
    # status, the rating and both dates, so adding those three fields cost no
    # extra statements: the fetch was already here.
    user_books = {
        user_book.book_id: user_book
        for user_book in db.query(UserBook)
        .filter(UserBook.user_id == current_user.id, UserBook.book_id.in_(book_ids))
        .all()
    }

    results: list[BookOut] = []
    for book in books:
        out = BookOut.model_validate(book)
        loan = active_loans.get(book.id)
        out.active_loan = _loan_summary(loan) if loan else None

        user_book = user_books.get(book.id)
        # No row means unread: a user_books row only appears once a status is set.
        # The status is coerced back to the enum explicitly, because the column
        # is a plain VARCHAR and assigning a str onto an enum-typed Pydantic
        # field bypasses validation and serialises with a warning. (Assignment
        # skips validation; model_validate would coerce.)
        out.my_status = ReadStatus(user_book.status) if user_book else ReadStatus.UNREAD
        out.my_rating = user_book.rating if user_book else None
        out.my_started_at = user_book.started_at if user_book else None
        out.my_finished_at = user_book.finished_at if user_book else None
        results.append(out)
    return results


def _book_to_out(book: Book, current_user: User, db: Session) -> BookOut:
    return _books_to_out([book], current_user, db)[0]


# ── Tags and lookup ───────────────────────────────────────────────────────────


@router.get("/tags", response_model=list[TagOut])
def list_tags(db: DbSession, current_user: CurrentUser) -> list[Tag]:
    return db.query(Tag).order_by(Tag.category, Tag.name).all()


@router.get("/lookup", response_model=BookLookup)
async def lookup_isbn(
    db: DbSession,
    current_user: CurrentUser,
    isbn: Annotated[str, Query(min_length=10, max_length=20)],
) -> BookLookup:
    # Validated before either upstream is called: a misread barcode would
    # otherwise cost two network round trips to learn nothing.
    canonical = isbn_utils.parse(isbn)
    if canonical is None:
        raise HTTPException(
            status_code=422,
            detail="Not a valid ISBN. Check the digits and try again.",
        )

    data = await _fetch_open_library(canonical)
    if not data:
        data = await _fetch_google_books(canonical)
    if not data:
        raise HTTPException(status_code=404, detail="Book not found for this ISBN")

    subjects = data.pop("subjects", [])
    all_tags = db.query(Tag).all()
    return BookLookup(**data, suggested_tag_ids=_match_subjects_to_tags(subjects, all_tags))


@router.get("/google/search", response_model=list[GoogleBooksMatch])
async def search_google_books(
    db: DbSession,
    current_user: CurrentUser,
    q: Annotated[str, Query(min_length=2, max_length=200, description="Title, author or both")],
    limit: Annotated[int, Query(ge=1, le=20)] = 10,
) -> list[GoogleBooksMatch]:
    """Free-text search, for adding a book nobody can scan.

    The barcode path covers a book that is physically to hand. This covers the
    rest: a book with no barcode, a damaged one, or one being added from a
    list rather than from the shelf. The caller picks a result and the client
    prefills the form from it, so nothing is written until a person confirms.

    Two segments (`/google/search`) rather than one, so it cannot be confused
    with `/{book_id}` however the routes are later reordered.
    """
    api_key = _require_google_books(db)

    try:
        matches = await google_books.search(q, api_key, limit=limit)
    except google_books.GoogleBooksError as error:
        raise HTTPException(status_code=502, detail=str(error)) from error

    all_tags = db.query(Tag).all()
    results: list[GoogleBooksMatch] = []
    for match in matches:
        subjects = google_books.split_categories(match.get("categories"))
        results.append(
            GoogleBooksMatch(
                **match,
                suggested_tag_ids=_match_subjects_to_tags(subjects, all_tags),
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
            ]
        )
        for book in books:
            writer.writerow(
                [
                    book.title or "",
                    book.author or "",
                    book.isbn or "",
                    book.publisher or "",
                    book.year if book.year is not None else "",
                    book.description or "",
                    "; ".join(tag.name for tag in book.tags),
                    status_map.get(book.id, ReadStatus.UNREAD),
                    book.added_at.date().isoformat() if book.added_at else "",
                    book.added_by.username if book.added_by else "",
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
    series: Annotated[str | None, Query(max_length=255)] = None,
    location: Annotated[str | None, Query(max_length=120)] = None,
    unrated: Annotated[bool, Query(description="Only books you have not rated")] = False,
    sort: Annotated[BookSort, Query()] = BookSort.TITLE_ASC,
) -> Page[BookOut]:
    query = db.query(Book).filter(visible_to(current_user.id))

    if ownership is not None:
        query = query.filter(Book.ownership == ownership)

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
        items=_books_to_out(books, current_user, db),
        total=total,
        page=paging.page,
        page_size=paging.page_size,
    )


# ── Creating ──────────────────────────────────────────────────────────────────


def _create_book(payload: BookCreate, current_user: User, db: Session, conflict: str) -> BookOut:
    # payload.isbn is already canonical ISBN-13 (see BookCreate's validator),
    # but rows written before canonicalisation may hold the ISBN-10, so both
    # spellings are checked or the same book gets added twice.
    if payload.isbn:
        forms = isbn_utils.equivalent_forms(payload.isbn)
        if forms and db.query(Book).filter(Book.isbn.in_(forms)).first():
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=conflict)
    book = Book(**payload.model_dump(), added_by_user_id=current_user.id)
    db.add(book)
    db.commit()
    db.refresh(book)
    return _book_to_out(book, current_user, db)


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

    `/bulk/ownership` predates this and is kept: it is the older, narrower
    shape and something may already be calling it.
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
    for book in books:
        db.delete(book)
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


@router.post("/bulk/ownership", response_model=BulkOwnershipResult)
def bulk_set_ownership(
    payload: BulkOwnershipUpdate,
    db: DbSession,
    current_user: CurrentUser,
) -> BulkOwnershipResult:
    """Mark a selection of books as owned, not owned, or unverified.

    Declared before /{book_id} would match "bulk" as an id, which is the same
    trap /export sits behind.

    Only books the caller may modify are touched. A selection containing
    someone else's private book reports it as skipped rather than failing the
    whole request: the member cannot see that book to deselect it, so failing
    would leave them stuck with no way to tell which entry was the problem.
    """
    requested = set(payload.book_ids)

    books = db.query(Book).filter(Book.id.in_(requested), visible_to(current_user.id)).all()

    updated = 0
    unchanged = 0
    for book in books:
        if book.ownership == payload.ownership:
            unchanged += 1
            continue
        book.ownership = payload.ownership
        updated += 1

    if updated:
        db.commit()

    return BulkOwnershipResult(
        updated=updated,
        unchanged=unchanged,
        skipped=len(requested) - len(books),
    )


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
    books = db.query(Book).filter(visible_to(current_user.id)).all()

    groups: dict[str, list[Book]] = {}
    for book in books:
        groups.setdefault(_duplicate_key(book), []).append(book)

    return [
        DuplicateGroup(key=key, books=_books_to_out(members, current_user, db))
        for key, members in sorted(groups.items())
        if len(members) > 1
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
        # Expire before deleting. The repointing above moved rows out from
        # under the loser, but its loaded relationship collections still list
        # them, and the delete cascade walks those collections rather than the
        # database. Without this, every note, loan and status just moved to the
        # keeper is deleted along with the row they came from.
        db.expire(loser)
        db.delete(loser)
    db.commit()
    db.refresh(keeper)
    return _book_to_out(keeper, current_user, db)


_MERGEABLE_FIELDS = (
    # `isbn` is absent deliberately: it is unique and handled separately, ahead
    # of everything here. See _absorb_fields.
    "subtitle", "author", "publisher", "year", "description", "cover_url",
    "page_count", "language", "categories", "google_books_id",
    "series_name", "series_index", "location",
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
    for loan in db.query(Loan).filter(Loan.book_id.in_(loser_ids)).all():
        loan.book_id = keeper.id

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


# ── Single book ───────────────────────────────────────────────────────────────


@router.get("/{book_id}", response_model=BookOut)
def get_book(book: BookForRead, db: DbSession, current_user: CurrentUser) -> BookOut:
    return _book_to_out(book, current_user, db)


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
    return _book_to_out(book, current_user, db)


@router.delete("/{book_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_book(book: BookForWrite, db: DbSession) -> None:
    db.delete(book)
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
    return _book_to_out(book, current_user, db)


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
    """
    now = datetime.now(UTC).replace(tzinfo=None)

    started = new_status in (ReadStatus.READING, ReadStatus.READ)
    if started and user_book.started_at is None:
        user_book.started_at = now

    if new_status is ReadStatus.READ:
        if user_book.finished_at is None:
            user_book.finished_at = now
    else:
        # Anything other than READ means it is not finished, whatever it was.
        user_book.finished_at = None

    if new_status in (ReadStatus.UNREAD, ReadStatus.WANT_TO_READ):
        user_book.started_at = None


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
    return _book_to_out(book, current_user, db)


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
    return _book_to_out(book, current_user, db)


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

    # Remove any previous cover in another format, or both would exist and
    # which one won would depend on lookup order.
    for old_extension in ("jpg", "jpeg", "png", "webp"):
        old_path = COVERS_DIR / f"{book.id}.{old_extension}"
        if old_path.exists():
            old_path.unlink()

    (COVERS_DIR / f"{book.id}.{extension}").write_bytes(data)
    book.cover_url = f"/covers/{book.id}.{extension}"
    db.commit()
    db.refresh(book)
    return _book_to_out(book, current_user, db)


# ── Metadata refresh ──────────────────────────────────────────────────────────


@router.put("/{book_id}/refresh", response_model=BookOut)
async def refresh_metadata(book: BookForWrite, db: DbSession, current_user: CurrentUser) -> BookOut:
    if not book.isbn:
        raise HTTPException(status_code=400, detail="Book has no ISBN, cannot refresh metadata")

    lookup_key = isbn_utils.parse(book.isbn) or book.isbn
    data = await _fetch_open_library(lookup_key)
    if not data:
        data = await _fetch_google_books(lookup_key)
    if not data:
        raise HTTPException(status_code=404, detail="No metadata found for this ISBN")

    book.title = data["title"] or book.title
    book.subtitle = data.get("subtitle")
    book.author = data.get("author")
    book.publisher = data.get("publisher")
    book.year = data.get("year")
    book.description = data.get("description")

    # A cover the member uploaded outranks whatever the source offers.
    if not (book.cover_url and book.cover_url.startswith("/covers/")):
        book.cover_url = data.get("cover_url")

    db.commit()
    db.refresh(book)
    return _book_to_out(book, current_user, db)


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


def _require_google_books(db: Session) -> str:
    """The configured API key, or a 400 explaining what to turn on.

    Both the toggle and the key are admin settings, so the message names which
    one is missing rather than reporting a generic failure to a member who
    cannot fix either.
    """
    if not settings_store.get_bool(db, SettingKey.GOOGLE_BOOKS_ENABLED):
        raise HTTPException(
            status_code=400,
            detail="Google Books lookup is switched off. An admin can enable it in Settings.",
        )

    # The resolved key: the environment's if the deployment supplied one, else
    # the stored one. Reading the setting directly here would ignore an
    # environment key and refuse a lookup that would have worked.
    api_key = settings_store.google_books_api_key(db)
    if not api_key:
        raise HTTPException(
            status_code=400,
            detail="No Google Books API key is set. An admin can add one in Settings.",
        )
    return api_key


@router.post("/{book_id}/enrich", response_model=BookEnrichmentOut)
async def enrich_book(
    book: BookForWrite,
    db: DbSession,
    current_user: CurrentUser,
    overwrite: Annotated[bool, Query(description="Replace fields that already have a value")] = False,
) -> BookEnrichmentOut:
    """Fill in the fields Open Library usually lacks, from Google Books.

    Matched by ISBN when there is one, otherwise by title and author. Only
    empty fields are filled unless `overwrite` is set: enrichment adds what is
    missing, it does not overrule what somebody typed.
    """
    api_key = _require_google_books(db)

    try:
        fields = None
        if book.isbn:
            fields = await google_books.lookup_by_isbn(book.isbn, api_key)

        if fields is None:
            # No ISBN, or Google does not carry this edition under it.
            query = " ".join(part for part in (book.title, book.author) if part)
            matches = await google_books.search(query, api_key, limit=1)
            fields = matches[0] if matches else None
    except google_books.GoogleBooksError as error:
        raise HTTPException(status_code=502, detail=str(error)) from error

    if fields is None:
        return BookEnrichmentOut(
            book=_book_to_out(book, current_user, db), updated_fields=[], found=False
        )

    updated = google_books.merge_into(book, fields, overwrite=overwrite)
    if updated:
        db.commit()
        db.refresh(book)

    return BookEnrichmentOut(
        book=_book_to_out(book, current_user, db), updated_fields=updated, found=True
    )


@router.get("/{book_id}/enrich/candidates", response_model=list[GoogleBooksMatch])
async def enrichment_candidates(
    book: BookForRead,
    db: DbSession,
    current_user: CurrentUser,
) -> list[GoogleBooksMatch]:
    """Editions Google offers for this book, so the right one can be chosen.

    Useful when the automatic match picks a different printing: the page count
    and cover of a paperback and its hardback are not the same.
    """
    api_key = _require_google_books(db)
    query = " ".join(part for part in (book.title, book.author) if part)

    try:
        matches = await google_books.search(query, api_key, limit=5)
    except google_books.GoogleBooksError as error:
        raise HTTPException(status_code=502, detail=str(error)) from error

    return [GoogleBooksMatch(**match) for match in matches]


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
    return _book_to_out(book, current_user, db)


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
    return _book_to_out(book, current_user, db)


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
    return _book_to_out(book, current_user, db)
