"""Turning ORM rows into the payloads the API returns.

Its own module rather than private helpers inside `routers/books.py` for two
reasons. `routers/loans.py` needs `books_to_out` and used to reach for it with
a function-local `from routers.books import ...` to dodge the import cycle that
a top-level import would have created, which is a cycle announcing itself. And
`BookOut` is assembled rather than mapped: several of its fields are not
columns, so the assembly is a piece of behaviour with its own tests, not
plumbing.

**`BookOut` depends on who is asking.** `active_loan`, the four `my_*` reading
fields and the three `my_progress_*` ones are all per-request, so the same book
row serialises differently for two accounts. Never cache a `BookOut` across
users.
"""

import re

from sqlalchemy import func, select
from sqlalchemy.orm import Session, aliased, joinedload, selectinload

from enums import ReadStatus
from models import Book, Loan, ReadingProgress, Tag, User, UserBook
from schemas import BookOut, LoanOut, UserOut

# The metadata sources themselves live in `metadata.py`. What is here is the
# part that is ours rather than theirs: mapping whatever subject headings a
# catalogue happens to use onto the household's own tag vocabulary.


def match_subjects_to_tags(subjects: list[str], tags: list[Tag]) -> list[int]:
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


def loan_summary(loan: Loan) -> LoanOut:
    """A loan as it appears *inside* a book payload.

    `book` is left None deliberately: the caller is already holding the book
    this loan belongs to, and populating it would both bloat the response and
    trigger a lazy load per book.
    """
    return LoanOut(
        id=loan.id,
        book_id=loan.book_id,
        loaned_to_user_id=loan.loaned_to_user_id,
        # Set instead of loaned_to_user_id when the book went to somebody with
        # no account. Carried here too, or the badge on a book lent to a
        # neighbour says "Loaned to" and then nothing.
        loaned_to_name=loan.loaned_to_name,
        loaned_by_user_id=loan.loaned_by_user_id,
        loaned_at=loan.loaned_at,
        returned_at=loan.returned_at,
        book=None,
        loaned_to=UserOut.model_validate(loan.loaned_to) if loan.loaned_to else None,
        loaned_by=UserOut.model_validate(loan.loaned_by) if loan.loaned_by else None,
    )


def derived_percent(page: int | None, percent: int | None, page_count: int | None) -> int | None:
    """How far through a book a recorded position is, as a whole number.

    Derived on every read rather than stored beside the position, so there is
    one fact in the database and no second copy to fall out of step when a
    metadata refresh corrects the page count.

    The order is the whole rule: a page against a known page count, else
    whatever percent was recorded, else nothing. A page with no page count
    yields nothing rather than a guess, which is why an audiobook records a
    percent in the first place.

    Clamped at 100 because `page_count` comes from a metadata provider and is
    off by one often enough that the last page routinely computes to 101.
    """
    if page is not None and page_count:
        return max(0, min(100, round(page / page_count * 100)))
    if page is not None:
        return None
    return percent


def _latest_progress(
    book_ids: list[int], current_user: User, db: Session
) -> dict[int, ReadingProgress]:
    """The caller's newest recorded position per book, in one statement.

    A window function rather than a query per book: adding a per-request field
    inside the serialisation loop is the N+1 that took listing 25 books from 6
    statements to 53, and this is exactly that shape of field.

    Ranked on `(recorded_at DESC, id DESC)` rather than on `max(id)`. The two
    agree for every row this app inserts, since the table is append-only and
    `recorded_at` defaults to now, and they stop agreeing after a restore,
    which carries the source database's timestamps into freshly assigned ids.

    `user_id` is in the filter, not only `book_id`. Progress is personal, and a
    page of books the caller may see is not a licence to see what anybody else
    was reading in them.
    """
    ranked = (
        select(
            ReadingProgress,
            func.row_number()
            .over(
                partition_by=ReadingProgress.book_id,
                order_by=(ReadingProgress.recorded_at.desc(), ReadingProgress.id.desc()),
            )
            .label("rank"),
        )
        .where(
            ReadingProgress.user_id == current_user.id,
            ReadingProgress.book_id.in_(book_ids),
        )
        .subquery()
    )
    entity = aliased(ReadingProgress, ranked)
    return {
        row.book_id: row
        for row in db.query(entity).filter(ranked.c.rank == 1).all()
    }


def _discussers(book_ids: list[int], db: Session) -> dict[int, list[UserOut]]:
    """Who has offered to talk about each of these books.

    **Not filtered to the caller**, unlike every other per-member field here,
    and that is the whole point of the flag: a reader browsing the shelf has to
    be able to see whose door to knock on. It leaks nothing else, in particular
    not whether those members have read the book.

    One statement for the page, joined to `users` so the names arrive with it.
    A per-book query here is the exact N+1 this module exists to avoid, and a
    lazy `user_book.user` read inside the loop would be the same thing wearing
    a different coat.

    Ordered by username so a book with three readers reads the same way twice.
    """
    rows = (
        db.query(UserBook.book_id, User)
        .join(User, User.id == UserBook.user_id)
        .filter(UserBook.book_id.in_(book_ids), UserBook.wants_to_discuss.is_(True))
        .order_by(User.username.asc())
        .all()
    )
    grouped: dict[int, list[UserOut]] = {}
    for book_id, user in rows:
        grouped.setdefault(book_id, []).append(UserOut.model_validate(user))
    return grouped


def books_to_out(books: list[Book], current_user: User, db: Session) -> list[BookOut]:
    """Serialise a page of books, adding the per-request fields.

    None of them is a column, and the obvious implementation queries for each
    of them per book, which is what made listing 25 books cost 53 SELECTs.

    **The cost, measured rather than counted off the source.** This function is
    the one place that states it; `docs/architecture.md` and
    `docs/data-model.md` point here rather than repeating a number, because
    both have been wrong before and were wrong in the same way twice.

    Six statements, constant in the size of the page: the books re-read to
    populate their tags, the tag load itself, the loans, the statuses, the
    progress, and the members offering to talk about each book. Measured at 1,
    5 and 25 books, unchanged.

    **Plus one per distinct `added_by` author the session has not already
    loaded**, and that one is not this function's: `BookOut.model_validate`
    reads `book.added_by`, which lazy loads unless the caller fetched it. So
    the number depends on who called, and on who wrote the books.

    The caller's own row is always already loaded, because the auth dependency
    put it in this session before the endpoint touched a book, so **books the
    caller added cost nothing here**. That is the one condition that moves the
    number, which is why it is stated rather than left in the measurement.

    Measured on rows fetched without `joinedload`, identical at 5 and at 25
    books, for one, two and three distinct authors:

        authors                  1   2   3
        caller wrote none        7   8   9
        caller is one of them    6   7   8

    Every listing endpoint in `routers/books.py` passes
    `joinedload(Book.added_by)`, so none of them pays any of it: `GET
    /api/books` measures a flat **11 SELECTs** end to end at 5 and 25 books and
    at one, two and three authors, and `books_to_out` on rows fetched with the
    option is a flat 6 at 1, 5 and 25 books.

    A new caller that fetches books without that option gets the per-author
    cost back. That is the trap this paragraph exists to name.
    """
    if not books:
        return []

    book_ids = [book.id for book in books]

    # visible_to exempt: not a visibility question. These rows were fetched by
    # a caller that applied the predicate, and this re-reads the same ids to
    # populate a relationship on the objects already in hand. Filtering here
    # would answer a question nobody asked.
    #
    # Tags in one query for the whole page. `BookOut.model_validate` reads
    # `book.tags`, which is a lazy relationship, so without this a page of 25
    # books issued 25 extra SELECTs: the identical N+1 this function exists to
    # avoid, arrived by a different door. Re-querying rows already in the
    # identity map looks redundant and is not: it is what populates the
    # collection, and the objects handed back are the same ones.
    db.query(Book).options(selectinload(Book.tags)).filter(Book.id.in_(book_ids)).all()

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

    latest_progress = _latest_progress(book_ids, current_user, db)
    discussers = _discussers(book_ids, db)

    results: list[BookOut] = []
    for book in books:
        out = BookOut.model_validate(book)
        loan = active_loans.get(book.id)
        out.active_loan = loan_summary(loan) if loan else None

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
        out.my_wants_to_discuss = bool(user_book.wants_to_discuss) if user_book else False
        out.discuss_with = discussers.get(book.id, [])

        progress = latest_progress.get(book.id)
        if progress is not None:
            out.my_progress_page = progress.page
            out.my_progress_percent = derived_percent(
                progress.page, progress.percent, book.page_count
            )
            out.my_progress_recorded_at = progress.recorded_at
        results.append(out)
    return results


def book_to_out(book: Book, current_user: User, db: Session) -> BookOut:
    return books_to_out([book], current_user, db)[0]


