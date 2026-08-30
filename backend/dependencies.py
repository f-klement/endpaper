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
from fastapi import Path as PathParam
from sqlalchemy.orm import Session

import ddc
from auth import get_current_user, get_current_user_for_cover
from database import get_db
from enums import ClassificationScheme
from models import CLASSIFICATION_NUMBER_MAX, Book, User
from schemas.common import DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE, MAX_ROW_ID
from shelf import Loading, Shelf

#: A row id read out of the URL path, bounded at both ends.
#:
#: **Bounded is the whole point.** A Python int has no ceiling and SQLite's
#: does, so `2**63` in a path segment passes validation, reaches `db.get()` and
#: raises `OverflowError` from inside the query: a **500** answered to a value
#: the caller chose, which is the app calling its own code buggy. Measured on
#: `GET /api/books/{id}` and `DELETE /api/books/tags/{id}` before this existed.
#:
#: One alias rather than the bounds retyped at twelve call sites.
#: `tests/test_house_rules.py::TestEveryIntParameterFromTheOutsideIsBounded`
#: resolves it by name: it collects module-level names assigned a bounded
#: `Annotated[...]`, accepts any parameter annotated with one, and fails a
#: parameter annotated with a bare `int` on a route handler or a dependency.
#: `PathParam` rather than `Path` because `pathlib.Path` is the other one,
#: exactly as `routers/covers.py` already spells it.
RowId = Annotated[int, PathParam(ge=1, le=MAX_ROW_ID)]

#: The longest a comma separated list of row ids may be, as characters.
#:
#: **The bound has to be on the string, because the ids are inside it.** `RowId`
#: and `RowIdField` both work by annotating an `int`, and neither can see a
#: number that arrives as part of a `str`: measured on the public catalogue with
#: no session at all, `?tags=18446744073709551616` raised `OverflowError` from
#: inside the query, `?tags=<5000 digits>` exceeded `sys.int_max_str_digits`, and
#: a thousand ids exceeded SQLite's expression tree depth. All three answered
#: **500**, which is the app calling its own code buggy at a value the caller
#: chose.
#:
#: 400 characters is far past any real filter (32 ids of six digits is 224) and
#: far under `sys.int_max_str_digits`, which is 4300, so no single token in a
#: list this long can be expensive to parse.
MAX_ID_LIST_CHARS = 400

#: How many ids one filter may name.
#:
#: **A cost bound, not a product limit.** Each tag id becomes its own correlated
#: `EXISTS` and they are ANDed, so the work is linear in the count: measured on
#: the public listing against a one book catalogue, 500 ids took 0.789s and 900
#: took 0.900s of CPU, and the public rate limit of 120 requests a minute would
#: have allowed one address to spend more than a minute of CPU per minute
#: without ever tripping it.
#:
#: 32 against a seeded vocabulary of 105 tags, and the filter is a conjunction,
#: so a query naming 32 tags returns nothing on any real library. Measured after
#: the bound, on the same one book catalogue: 1 id 10.8ms, 32 ids **23.7ms**, 33
#: ids a 422 in 9.4ms. So the ceiling costs about 13ms over an unfiltered
#: request, against the 900ms one request could spend before it.
MAX_IDS_IN_A_FILTER = 32

#: One spelling of the parameter, so the two listings cannot bound it
#: differently. `routers/books.py` and `routers/public.py` both use it.
TagIdList = Annotated[
    str | None,
    Query(max_length=MAX_ID_LIST_CHARS, description="Comma-separated tag ids"),
]


def row_ids(raw: str | None, *, field: str) -> list[int]:
    """A comma separated list of row ids, bounded at both ends and in length.

    **The one parser, shared, because the line it replaces was copied.** It was
    written inline in `routers/books.py` and copied verbatim onto the public
    listing, where it became reachable with no session; the defect was already
    there and the copy is what made it worth fixing rather than filing.

    Two rules, and they are deliberately different from each other:

    * **A token that is not a row id is dropped**, which is the existing
      contract: `?tags=abc` has always been ignored rather than refused. An id
      past `MAX_ROW_ID` is dropped by the same rule, because it is not a row id
      either, and dropping it is what stops it reaching the driver.
    * **Too many ids is refused**, with a 422 naming the ceiling. Truncating
      instead would answer a different question from the one asked and say
      nothing about it, and this is a filter: a wrong answer looks like a
      correct one.
    """
    if not raw:
        return []
    found = [
        number
        for token in raw.split(",")
        if (stripped := token.strip()).isdigit()
        and 1 <= (number := int(stripped)) <= MAX_ROW_ID
    ]
    if len(found) > MAX_IDS_IN_A_FILTER:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=(
                f"Name at most {MAX_IDS_IN_A_FILTER} ids in `{field}`; "
                f"this asked for {len(found)}."
            ),
        )
    return found


#: The longest `scheme:number` that could name a stored row.
#:
#: `lcsh` is the longest scheme spelling at four characters, plus the colon,
#: plus `CLASSIFICATION_NUMBER_MAX`. A value longer than this cannot match any
#: row, whatever it says.
MAX_HEADING_CHARS = 5 + CLASSIFICATION_NUMBER_MAX

#: How many values the repeated heading parameter may carry before Pydantic
#: refuses the request outright.
#:
#: **This bounds the list and nothing else**, which is the correction rather
#: than the design: on `list[str] | None` Pydantic renders `max_length` as
#: OpenAPI `maxItems`, so it counts the values and says nothing about how long
#: one may be. Written first as a per value bound with a docstring asserting
#: exactly that, it left the parameter with no length bound at all: a single
#: 20,000 character value answered 200 and parsed into one heading. Both
#: critic seats found it independently, which is what that costs.
#:
#: The per value bound is `MAX_HEADING_CHARS`, applied inside `headings()` by
#: dropping, because a value too long to match a row is a value that is not a
#: heading and this module drops those rather than refusing them. Above the
#: `MAX_IDS_IN_A_FILTER` ceiling so the useful refusal is the one naming the
#: count.
MAX_HEADING_VALUES = 128

#: One spelling of the heading filter, so a second listing cannot bound it
#: differently, in the way `TagIdList` already serves two.
#:
#: **Repeated rather than comma separated, and that is forced by the data.**
#: `?tags=1,2,3` works because a tag id is a number. An LCSH `number` is the
#: authorised heading string itself, and those carry commas
#: (`Mental health, Public`) and colons. A comma separated list of them cannot
#: be taken apart again, so the parameter repeats instead:
#: `?classification=lcsh:Mental health&classification=ddc:004`.
HeadingList = Annotated[
    list[str] | None,
    Query(
        max_length=MAX_HEADING_VALUES,
        description=(
            "Only books carrying this heading, as `scheme:number`. Repeat the "
            "parameter for more than one; they are ANDed."
        ),
    ),
]

#: The Dewey division filter. Comma separated is safe here where it is not for a
#: heading: a division is three digits by construction.
DivisionList = Annotated[
    str | None,
    Query(max_length=MAX_ID_LIST_CHARS, description="Comma-separated Dewey divisions"),
]


def headings(raw: list[str] | None) -> list[tuple[ClassificationScheme, str]]:
    """`["lcsh:Mental health"]` as the pairs the shelf filters on.

    **Split on the first colon only.** An LCSH heading may contain one
    (`Photography: a history`), and splitting on every colon would turn that
    into a scheme nobody recognises plus a fragment. Taking the first is
    unambiguous because the left half is then checked against a closed enum: a
    value whose prefix is not one of four known schemes is dropped.

    **Dropped rather than refused**, which is `row_ids`'s contract and the
    reason to match it: `?tags=abc` has always been ignored, a link is not a
    form, and there is nobody to show an error to. Too many is still refused,
    for `row_ids`'s reason: truncating answers a different question from the one
    asked and says nothing about it.

    **A value too long to match a row is dropped**, by the same rule and for a
    reason worth stating: the parameter's own `max_length` bounds the number of
    values rather than their length, so without this check the filter has no
    length bound at all. See `MAX_HEADING_VALUES`.

    **Interior whitespace is collapsed**, because `ClassificationIn.tidy_number`
    collapses it on the way in. Without the same collapse here,
    `?classification=lcsh:Mental  health` never matches the stored
    `Mental health`, and nothing says why.

    Deduplicated, keeping the order asked for. Each one adds a separate
    correlated EXISTS, so a repeated heading is a repeated subquery that cannot
    change the answer, and `MAX_IDS_IN_A_FILTER` bounds the work rather than the
    spelling.
    """
    if not raw:
        return []
    found: dict[tuple[ClassificationScheme, str], None] = {}
    for value in raw:
        if len(value) > MAX_HEADING_CHARS:
            continue
        scheme_name, separator, number = value.partition(":")
        if not separator:
            continue
        try:
            scheme = ClassificationScheme(scheme_name.strip().lower())
        except ValueError:
            continue
        collapsed = " ".join(number.split())
        if collapsed:
            found.setdefault((scheme, collapsed), None)
    if len(found) > MAX_IDS_IN_A_FILTER:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=(
                f"Name at most {MAX_IDS_IN_A_FILTER} headings in `classification`; "
                f"this asked for {len(found)}."
            ),
        )
    return list(found)


def divisions(raw: str | None) -> list[str]:
    """`"150,330"` as the Dewey divisions the shelf filters on.

    Through `ddc.division`, so what reaches the shelf is a canonical division
    rather than whatever was typed: `155.9042` asked for as a division resolves
    to `150` instead of being dropped, and a token that is not a Dewey number at
    all is dropped by the same call. Dropping rather than refusing is
    `row_ids`'s contract, for its reasons.
    """
    if not raw:
        return []
    found: dict[str, None] = {}
    for token in raw.split(","):
        division = ddc.division(token.strip())
        if division is not None:
            found.setdefault(division, None)
    if len(found) > MAX_IDS_IN_A_FILTER:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=(
                f"Name at most {MAX_IDS_IN_A_FILTER} divisions in `ddc`; "
                f"this asked for {len(found)}."
            ),
        )
    return list(found)


def _not_found() -> HTTPException:
    """The answer for a book that is absent, and for one that is not yours.

    **Identical on purpose**: a 403 would confirm that a book with this id
    exists, which is exactly what privacy withholds.

    A function returning a fresh instance, not a module level singleton, and
    that is not style. Raising one shared exception object appends a frame to
    its `__traceback__` on **every** raise and never releases it, so each 404
    permanently pins that frame's locals: here a `Session` and a `User` row,
    password hash included. Measured on the author route that had the same
    shape: 20 requests grew the traceback from 0 to 180 frames and retained 20
    handler frames. Sync handlers also run in a threadpool, so two concurrent
    404s would mutate one object's `__traceback__` and `__cause__`.
    """
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Book not found")


def book_for_read(
    book_id: RowId,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> Book:
    """The book at `book_id`, if the caller is allowed to see it.

    Eager-loads `added_by`, so resolving the book does not cost a query for the
    member who added it. The collections are not loaded here: `books_to_out`
    re-reads the page and loads them itself, and `shelf.Loading` carries the
    measurement.
    """
    book = (
        Shelf.seen_by(db, current_user.id)
        .where(Book.id == book_id)
        .first(load=Loading.SERIALISED)
    )
    if book is None:
        raise _not_found()
    return book


def book_for_cover(
    book_id: RowId,
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
    book = Shelf.seen_by(db, current_user.id).where(Book.id == book_id).first()
    if book is None:
        raise _not_found()
    return book


def book_in_trash(
    book_id: RowId,
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
        Shelf.trashed_by(db, current_user.id)
        .where(Book.id == book_id)
        .first(load=Loading.SERIALISED)
    )
    if book is None:
        raise _not_found()
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
