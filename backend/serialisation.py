"""Turning ORM rows into the payloads the API returns.

Its own module rather than private helpers inside `routers/books.py` for two
reasons. `routers/loans.py` needs `books_to_out` and used to reach for it with
a function-local `from routers.books import ...` to dodge the import cycle that
a top-level import would have created, which is a cycle announcing itself. And
`BookOut` is assembled rather than mapped: two of its fields are not columns,
so the assembly is a piece of behaviour with its own tests, not plumbing.

**`BookOut` depends on who is asking.** `active_loan` and `my_status` are
per-request, so the same book row serialises differently for two accounts.
Never cache a `BookOut` across users.
"""

import re

from sqlalchemy.orm import Session, joinedload, selectinload

from enums import ReadStatus
from models import Book, Loan, Tag, User, UserBook
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
        loaned_by_user_id=loan.loaned_by_user_id,
        loaned_at=loan.loaned_at,
        returned_at=loan.returned_at,
        book=None,
        loaned_to=UserOut.model_validate(loan.loaned_to) if loan.loaned_to else None,
        loaned_by=UserOut.model_validate(loan.loaned_by) if loan.loaned_by else None,
    )


def books_to_out(books: list[Book], current_user: User, db: Session) -> list[BookOut]:
    """Serialise a page of books, adding the two per-request fields.

    `active_loan` and `my_status` are not columns, and the obvious
    implementation queries for each of them per book, which is what made
    listing 25 books cost 53 SELECTs. Both are fetched here in one query each,
    so a page costs a constant three regardless of its size.
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
        results.append(out)
    return results


def book_to_out(book: Book, current_user: User, db: Session) -> BookOut:
    return books_to_out([book], current_user, db)[0]


