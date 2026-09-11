"""What may be written to `book_identifiers`, and how much.

The route's own behaviour is pinned in `tests/routers/test_books_identifiers.py`,
which is where a member meets it. What is pinned here is the module's two rules:
that it adds rather than replaces, and that the ceiling is counted against the
Book rather than against the payload, which is the half that makes
`MAX_IDENTIFIERS_PER_BOOK` a per Book number at all.
"""

import logging

import pytest
from sqlalchemy.exc import IntegrityError

from enums import BookIdentifierScheme
from identifiers import add_identifiers
from models import Book, BookIdentifier
from schemas.identifier import MAX_IDENTIFIERS_PER_BOOK, BookIdentifierIn


def asin(value):
    return BookIdentifierIn(scheme=BookIdentifierScheme.ASIN, value=value)


@pytest.fixture
def book(db):
    row = Book(title="Praxiswissen Docker")
    db.add(row)
    db.commit()
    return row


class TestAddingThem:
    def test_an_identifier_becomes_a_row(self, db, book):
        assert add_identifiers(book, [asin("B00J4YQKHY")], db) == ["B00J4YQKHY"]
        db.commit()

        assert [(row.scheme, row.value) for row in book.identifiers] == [
            (BookIdentifierScheme.ASIN, "B00J4YQKHY")
        ]

    def test_two_schemes_live_on_one_book(self, db, book):
        """The case that decided a table over a column: a merge really does
        leave one row carrying an ASIN and a Google volume id."""
        add_identifiers(
            book,
            [
                asin("B00J4YQKHY"),
                BookIdentifierIn(
                    scheme=BookIdentifierScheme.GOOGLE_BOOKS, value="zyTCAlFPjgYC"
                ),
            ],
            db,
        )
        db.commit()

        assert {row.scheme for row in book.identifiers} == set(BookIdentifierScheme)


class TestItAddsRatherThanReplaces:
    def test_one_already_stored_is_not_written_twice(self, db, book):
        add_identifiers(book, [asin("B00J4YQKHY")], db)
        db.commit()

        assert add_identifiers(book, [asin("B00J4YQKHY")], db) == []
        db.commit()
        assert len(book.identifiers) == 1

    def test_an_earlier_one_survives_a_later_import(self, db, book):
        """Additive: importing a second store must not take the first's row."""
        add_identifiers(book, [asin("B00J4YQKHY")], db)
        db.commit()
        add_identifiers(
            book,
            [BookIdentifierIn(scheme="google_books", value="zyTCAlFPjgYC")],
            db,
        )
        db.commit()

        assert len(book.identifiers) == 2

    def test_the_same_value_twice_in_one_payload_becomes_one_row(self, db, book):
        """Two identical rows in one flush trip the unique index rather than
        the check above it, so the deduplication has to be within the payload
        as well as against the Book."""
        assert add_identifiers(book, [asin("B00J4YQKHY"), asin("B00J4YQKHY")], db) == [
            "B00J4YQKHY"
        ]
        db.commit()
        assert len(book.identifiers) == 1

    def test_the_database_refuses_the_second_copy_too(self, db, book):
        """The check above the flush answers a request; this is what holds when
        a writer forgets to make it."""
        db.add(BookIdentifier(book=book, scheme="asin", value="B00J4YQKHY"))
        db.add(BookIdentifier(book=book, scheme="asin", value="B00J4YQKHY"))

        with pytest.raises(IntegrityError):
            db.commit()
        db.rollback()

    def test_two_books_may_carry_one_identifier(self, db, book):
        """The index is per Book, not global. Two rows for one edition is what
        `/duplicates` and the merge exist for, and refusing the second write
        would turn that into a 500 rather than into a question."""
        other = Book(title="Praxiswissen Docker, again")
        db.add(other)
        db.commit()
        add_identifiers(book, [asin("B00J4YQKHY")], db)
        add_identifiers(other, [asin("B00J4YQKHY")], db)
        db.commit()

        assert len(book.identifiers) == 1
        assert len(other.identifiers) == 1


class TestTheCeilingIsCountedAgainstTheBook:
    def test_a_payload_that_would_take_it_past_the_ceiling_is_cut(self, db, book):
        entries = [asin(f"B{index:09d}") for index in range(MAX_IDENTIFIERS_PER_BOOK + 3)]

        added = add_identifiers(book, entries, db)
        db.commit()

        assert len(added) == MAX_IDENTIFIERS_PER_BOOK
        assert len(book.identifiers) == MAX_IDENTIFIERS_PER_BOOK

    def test_a_second_call_cannot_walk_past_it(self, db, book):
        """The rule the per request `max_length` cannot supply: every caller is
        bounded per request and this writer is additive across them, so without
        the count here the per Book total is unbounded."""
        add_identifiers(
            book, [asin(f"B{index:09d}") for index in range(MAX_IDENTIFIERS_PER_BOOK)], db
        )
        db.commit()

        assert add_identifiers(book, [asin("B999999999")], db) == []
        db.commit()
        assert len(book.identifiers) == MAX_IDENTIFIERS_PER_BOOK

    def test_the_drop_is_logged(self, db, book, caplog):
        """A dropped identifier came out of a member's own file and nothing
        regenerates it, so a silent drop is a loss with nowhere to read it off.
        `classifications.add_headings` logs its own for the same reason."""
        add_identifiers(
            book, [asin(f"B{index:09d}") for index in range(MAX_IDENTIFIERS_PER_BOOK)], db
        )
        db.commit()

        with caplog.at_level(logging.INFO, logger="endpaper.identifiers"):
            add_identifiers(book, [asin("B999999999")], db)

        assert "B999999999" in caplog.text
