"""Bulk import from other services.

Only Goodreads today, and only from a file: their API was retired in December
2020, so a CSV export is the sole supported way to get a library out. See
`backend/goodreads.py`.
"""

import logging
from datetime import datetime, time
from typing import Annotated

from fastapi import APIRouter, File, HTTPException, Query, UploadFile
from sqlalchemy import func

import goodreads
from config import MAX_UPLOAD_BYTES
from dependencies import CurrentUser, DbSession
from enums import OwnershipStatus, ReadStatus
from models import Book, UserBook, visible_to
from schemas import GoodreadsImportOut

logger = logging.getLogger("endpaper.imports")

router = APIRouter(prefix="/api/imports", tags=["imports"])


@router.post("/goodreads", response_model=GoodreadsImportOut)
async def import_goodreads(
    db: DbSession,
    current_user: CurrentUser,
    file: Annotated[UploadFile, File()],
    create_missing: Annotated[
        bool, Query(description="Add books from the export that are not in the catalogue")
    ] = False,
) -> GoodreadsImportOut:
    """Apply the reading statuses from a Goodreads export.

    Statuses are **personal**, so this only ever writes the importing member's
    own `user_books` rows. Importing your shelves does not change what anyone
    else has read, and two members can import their own exports without
    fighting over the same books.

    Books created by `create_missing` are marked `ownership=unknown`: a reading
    history is not evidence of possession. They can then be confirmed together
    from the library view, which is what the bulk ownership endpoint is for.
    """
    content = await file.read(MAX_UPLOAD_BYTES + 1)
    if len(content) > MAX_UPLOAD_BYTES:
        raise HTTPException(
            status_code=413,
            detail=f"That file is larger than {MAX_UPLOAD_BYTES // (1024 * 1024)} MB.",
        )
    if not content:
        raise HTTPException(status_code=400, detail="That file is empty.")

    try:
        parsed = goodreads.parse_export(content)
    except ValueError as error:
        # A readable explanation beats "0 books imported" for someone who
        # picked the wrong file.
        raise HTTPException(status_code=400, detail=str(error)) from error

    matched = 0
    updated = 0
    created = 0
    unmatched: list[str] = []

    for row in parsed.rows:
        book = _find_book(db, row, current_user.id)

        if book is None and create_missing:
            book = Book(
                title=row.title,
                author=row.author,
                isbn=row.isbn,
                added_by_user_id=current_user.id,
                # An export says what someone read, not what is on the shelf.
                # Marking these OWNED would assert something nobody checked,
                # so they arrive unverified and are confirmed in bulk
                # afterwards.
                ownership=OwnershipStatus.UNKNOWN,
            )
            db.add(book)
            db.flush()
            created += 1
        elif book is None:
            # Capped: a 5000-book export with nothing matching would otherwise
            # return a response larger than the file that produced it.
            if len(unmatched) < 50:
                unmatched.append(row.title)
            continue
        else:
            matched += 1

        if _apply_row(db, book_id=book.id, user_id=current_user.id, row=row):
            updated += 1

    db.commit()

    return GoodreadsImportOut(
        rows_read=len(parsed.rows),
        matched=matched,
        created=created,
        statuses_updated=updated,
        skipped=parsed.skipped,
        unmatched_titles=unmatched,
    )


def _find_book(db: DbSession, row: goodreads.GoodreadsRow, user_id: int) -> Book | None:
    """Match an exported row to a book already in the catalogue.

    ISBN first, since it is unambiguous. Falling back to a case-insensitive
    title match is deliberate but imperfect: two editions of the same title
    will collide, which is acceptable for a status and would not be for
    anything destructive.
    """
    if row.isbn:
        book = (
            db.query(Book)
            .filter(Book.isbn == row.isbn, visible_to(user_id))
            .first()
        )
        if book is not None:
            return book

    return (
        db.query(Book)
        .filter(func.lower(Book.title) == row.title.lower(), visible_to(user_id))
        .first()
    )


def _apply_row(
    db: DbSession, *, book_id: int, user_id: int, row: goodreads.GoodreadsRow
) -> bool:
    """Write this member's status, rating and finish date. True if anything changed.

    The rating and the date were parsed all along and thrown away, because
    there was nowhere to put them. There is now.

    Existing local values are never overwritten: somebody who has already rated
    a book here has expressed a more recent opinion than an export taken from
    another service. The import fills gaps, on the same principle as metadata
    enrichment.
    """
    existing = (
        db.query(UserBook)
        .filter(UserBook.user_id == user_id, UserBook.book_id == book_id)
        .first()
    )

    if existing is None:
        existing = UserBook(user_id=user_id, book_id=book_id)
        db.add(existing)
        changed = True
    else:
        changed = ReadStatus(existing.status) is not row.status

    existing.status = row.status

    if row.rating is not None and existing.rating is None:
        existing.rating = row.rating
        changed = True

    # Only for books the export says were finished. A date on a
    # currently-reading row would be a finish date for a book nobody finished.
    if row.status is ReadStatus.READ and row.date_read is not None and existing.finished_at is None:
        existing.finished_at = datetime.combine(row.date_read, time.min)
        changed = True

    return changed
