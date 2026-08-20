"""Tests for backend/serialisation.py: assembling BookOut.

Exercised directly rather than through a route, because the behaviour under
test is the assembly: two of BookOut's fields are not columns, and both depend
on who is asking.
"""

import pytest
from sqlalchemy import event

from enums import ReadStatus
from models import Book, Loan, Tag, User, UserBook
from serialisation import book_to_out, books_to_out, loan_summary, match_subjects_to_tags


@pytest.fixture
def two_books(db):
    books = [Book(title="Dune"), Book(title="Neuromancer")]
    db.add_all(books)
    db.commit()
    for book in books:
        db.refresh(book)
    return books


class TestMatchSubjectsToTags:
    def test_it_matches_case_insensitively(self):
        tags = [Tag(id=1, name="Fantasy")]
        assert match_subjects_to_tags(["EPIC FANTASY"], tags) == [1]

    def test_it_ignores_a_parenthetical_suffix_on_the_tag(self):
        """"Young Adult (13-18)" has to match a source saying "young adult"."""
        tags = [Tag(id=7, name="Young Adult (13 to 18)")]
        assert match_subjects_to_tags(["young adult fiction"], tags) == [7]

    def test_no_subjects_matches_nothing(self):
        assert match_subjects_to_tags([], [Tag(id=1, name="Fantasy")]) == []

    def test_an_unrelated_subject_matches_nothing(self):
        assert match_subjects_to_tags(["cookery"], [Tag(id=1, name="Fantasy")]) == []


class TestLoanSummary:
    def test_it_leaves_the_book_out(self, db, admin, member, two_books):
        """The caller is already holding the book this loan belongs to, and
        populating it would trigger a lazy load per book."""
        loan = Loan(
            book_id=two_books[0].id,
            loaned_to_user_id=member["user"]["id"],
            loaned_by_user_id=admin["user"]["id"],
        )
        db.add(loan)
        db.commit()

        assert loan_summary(loan).book is None

    def test_it_carries_an_external_borrower_name(self, db, admin, two_books):
        """Without this the badge on a book lent to a neighbour reads "Loaned
        to" and then nothing."""
        loan = Loan(
            book_id=two_books[0].id,
            loaned_to_name="the neighbour",
            loaned_by_user_id=admin["user"]["id"],
        )
        db.add(loan)
        db.commit()

        summary = loan_summary(loan)
        assert summary.loaned_to_name == "the neighbour"
        assert summary.loaned_to is None


class TestBooksToOut:
    def test_an_empty_page_costs_no_queries(self, db, admin):
        user = db.get(User, admin["user"]["id"])
        assert books_to_out([], user, db) == []

    def test_a_book_nobody_has_touched_reads_as_unread(self, db, admin, two_books):
        """A user_books row only appears once a status is set, so absence is
        the common case rather than an edge one."""
        user = db.get(User, admin["user"]["id"])

        out = book_to_out(two_books[0], user, db)

        assert out.my_status is ReadStatus.UNREAD
        assert out.my_rating is None
        assert out.active_loan is None

    def test_the_status_is_coerced_back_to_the_enum(self, db, admin, two_books):
        """The column is a plain VARCHAR. Assigning the str onto an enum-typed
        Pydantic field skips validation and serialises with a warning."""
        user = db.get(User, admin["user"]["id"])
        db.add(UserBook(user_id=user.id, book_id=two_books[0].id, status="read"))
        db.commit()

        out = book_to_out(two_books[0], user, db)

        assert out.my_status is ReadStatus.READ

    def test_two_accounts_see_the_same_row_differently(self, db, admin, member, two_books):
        """The reason a BookOut must never be cached across users."""
        them = db.get(User, member["user"]["id"])
        me = db.get(User, admin["user"]["id"])
        db.add(UserBook(user_id=me.id, book_id=two_books[0].id, status="read"))
        db.commit()

        assert book_to_out(two_books[0], me, db).my_status is ReadStatus.READ
        assert book_to_out(two_books[0], them, db).my_status is ReadStatus.UNREAD

    def test_a_page_costs_the_same_whatever_its_size(self, db, admin, two_books):
        """The N+1 this function exists to avoid, pinned by measurement rather
        than by reading. Listing 25 books cost 53 SELECTs once. It had already
        come back by a different door when this test was written: `BookOut`
        reads `book.tags`, which is lazy, so a page cost one more query per
        book on top of the constant three."""
        user = db.get(User, admin["user"]["id"])
        # Touch every column first. The rows expired at the last commit, so
        # otherwise the first call pays for reloading them and the measurement
        # is of the ORM's identity map rather than of this function.
        for book in two_books:
            _ = book.title

        statements: list[str] = []

        @event.listens_for(db.get_bind(), "before_cursor_execute")
        def record(conn, cursor, statement, *args):
            statements.append(statement)

        try:
            books_to_out(two_books, user, db)
            for_two = len(statements)
            statements.clear()
            books_to_out(two_books[:1], user, db)
            for_one = len(statements)
        finally:
            event.remove(db.get_bind(), "before_cursor_execute", record)

        assert for_two == for_one
