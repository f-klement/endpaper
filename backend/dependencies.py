"""Reusable request dependencies: book access control and pagination.

Access to a book was previously decided inline in each handler, and most of
them decided nothing at all: any signed-in member could delete, retag,
re-cover or metadata-refresh any book, including a private one belonging to
someone else, and could read the notes on it. Centralising the rules here means
a new endpoint gets them by asking for the book, rather than by remembering to
write the checks.

The rules, in one place:

    read   visible to the caller: the book is on the shelf, and it is public
           or the caller added it.
    write  visible, and either public (a shared shelf: any member may curate
           it) or the caller's own private book.
    owner  visible, and the caller added it, or is an admin. Reserved for
           decisions that are the owner's alone, like flipping privacy.

Because "visible" already means *public or mine*, a private book that survives
the read check necessarily belongs to the caller. That is why the write rule
needs no separate private-book branch.
"""

from typing import Annotated

from fastapi import Depends, HTTPException, Query, status
from sqlalchemy.orm import Session, joinedload, selectinload

from auth import get_current_user, get_current_user_for_cover
from database import get_db
from models import Book, User, in_trash_for, visible_to
from schemas.common import DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE

# Absent and forbidden are reported identically on purpose: a 403 would confirm
# that a book with this id exists, which is exactly what privacy withholds.
_NOT_FOUND = HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Book not found")


def book_for_read(
    book_id: int,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> Book:
    """The book at `book_id`, if the caller is allowed to see it.

    Eager-loads the relationships every caller serialises, so resolving the
    book does not cost a query per related row later.
    """
    book = (
        db.query(Book)
        .options(joinedload(Book.added_by), selectinload(Book.tags))
        .filter(Book.id == book_id, visible_to(current_user.id))
        .first()
    )
    if book is None:
        raise _NOT_FOUND
    return book


def book_for_cover(
    book_id: int,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user_for_cover)],
) -> Book:
    """The same read rule as `book_for_read`, resolved for the cover route.

    Identical logic, different identity source: an `<img>` tag cannot send an
    `Authorization` header, so the cover route additionally accepts a
    path-scoped cookie. See `auth.COVER_COOKIE_NAME` for why that is safe here
    and would not be on any other route.

    No eager loading: this one serialises nothing, it decides whether to open a
    file.
    """
    book = (
        db.query(Book)
        .filter(Book.id == book_id, visible_to(current_user.id))
        .first()
    )
    if book is None:
        raise _NOT_FOUND
    return book


def book_in_trash(
    book_id: int,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> Book:
    """A **trashed** book the caller may see, for restoring or purging it.

    A separate dependency rather than a flag on `book_for_read`, because the
    two are opposites: `visible_to` now excludes trashed rows, so the ordinary
    dependency answers 404 for exactly the books this one is for.

    The same 404-not-403 rule applies, for the same reason. Somebody else's
    private book stays invisible in the trash too.
    """
    book = (
        db.query(Book)
        .options(joinedload(Book.added_by), selectinload(Book.tags))
        .filter(Book.id == book_id, in_trash_for(current_user.id))
        .first()
    )
    if book is None:
        raise _NOT_FOUND
    return book


def book_for_write(
    book: Annotated[Book, Depends(book_for_read)],
) -> Book:
    """The book at `book_id`, if the caller may modify it.

    Public books are a shared shelf: any member may retag, re-cover, refresh
    or remove one. Private books never reach here unless they are the caller's
    own, since `book_for_read` has already excluded everyone else's.
    """
    return book


def book_for_owner(
    book: Annotated[Book, Depends(book_for_read)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> Book:
    """The book at `book_id`, if the caller added it or is an admin.

    For decisions that belong to the owner rather than to the shelf. Making
    someone else's book private would hide it from everyone, so it is not
    something a passing member should be able to do.
    """
    if book.added_by_user_id != current_user.id and not current_user.is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only the member who added this book can change that",
        )
    return book


#: Past any real library, and small enough that `page * page_size` stays far
#: inside SQLite's INTEGER range.
MAX_PAGE_NUMBER = 1_000_000


class PageParams:
    """`page`/`page_size` query parameters, bounded so a caller cannot ask for
    the entire library and undo the point of paginating."""

    def __init__(
        self,
        # `le` is not decoration, and this parameter had it missing while
        # `page_size` beside it did not. `offset` multiplies this by the page
        # size, so an unbounded value overflows SQLite's INTEGER and reaches
        # `unhandled_exception_handler`: measured, `?page=9999999999999999999999`
        # answered **500** on the main book listing for any member. A million
        # pages is past any real library and keeps the product far inside the
        # driver's range. `tests/test_house_rules.py` is what found this.
        page: Annotated[
            int, Query(ge=1, le=MAX_PAGE_NUMBER, description="1-based page number")
        ] = 1,
        page_size: Annotated[
            int, Query(ge=1, le=MAX_PAGE_SIZE, description="Rows per page")
        ] = DEFAULT_PAGE_SIZE,
    ) -> None:
        self.page = page
        self.page_size = page_size

    @property
    def offset(self) -> int:
        return (self.page - 1) * self.page_size

    @property
    def limit(self) -> int:
        return self.page_size


BookForRead = Annotated[Book, Depends(book_for_read)]
BookInTrash = Annotated[Book, Depends(book_in_trash)]
BookForCover = Annotated[Book, Depends(book_for_cover)]
BookForWrite = Annotated[Book, Depends(book_for_write)]
BookForOwner = Annotated[Book, Depends(book_for_owner)]
Paging = Annotated[PageParams, Depends()]
CurrentUser = Annotated[User, Depends(get_current_user)]
DbSession = Annotated[Session, Depends(get_db)]
