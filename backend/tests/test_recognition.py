"""Which existing Book a record is: one arm per answer and per tie rule.

The importers' own tallies for each answer are in `tests/test_importing.py`;
this file drives the index alone, so a wrong answer is named here before it
becomes a wrong count there.
"""

from __future__ import annotations

from datetime import datetime

import pytest

from enums import BookIdentifierScheme
from models import Book, BookIdentifier, User
from recognition import Hidden, Index, InTrash, Seen, Source, Tied, Unknown, recognise_one

DUNE = "9780441013593"
#: The ISBN-10 of `DUNE`'s printing, as a row written before
#: canonicalisation holds it.
DUNE_TEN = "0441013597"
#: An ISBN-13 whose ISBN-10 ends in the check character X, and that ISBN-10
#: as a hand typed row might hold it.
LOWER_X = "9780804429573"
LOWER_X_TEN = "080442957x"


@pytest.fixture
def member(db) -> User:
    user = User(username="reader", password_hash="x")
    db.add(user)
    db.commit()
    return user


@pytest.fixture
def other(db, member) -> User:
    user = User(username="stranger", password_hash="x")
    db.add(user)
    db.commit()
    return user


def _book(db, owner: User, title: str, **fields: object) -> Book:
    book = Book(title=title, added_by_user_id=owner.id, **fields)
    db.add(book)
    db.commit()
    return book


#: When a trashed Book went to the trash. Naive UTC, as the column stores it.
TRASHED = datetime(2026, 1, 1)


class TestTheAnswers:
    def test_one_book_on_the_shelf_answering_is_seen(self, db, member):
        book = _book(db, member, "Dune", isbn=DUNE)

        index = Index.build(db, member.id, Source.CATALOGUE)

        assert index.recognise(title="Elsewhere", isbn=DUNE) == Seen(book.id)

    def test_nothing_answering_is_unknown(self, db, member):
        _book(db, member, "Dune", isbn=DUNE)

        index = Index.build(db, member.id, Source.CATALOGUE)

        assert index.recognise(title="Small Gods", isbn="9780552152976") == Unknown()

    def test_an_isbn_only_the_trash_view_holds_is_in_the_trash(self, db, member, other):
        mine = _book(db, member, "Dune", isbn=DUNE, deleted_at=TRASHED)

        index = Index.build(db, member.id, Source.READING_HISTORY)

        assert index.recognise(title="Elsewhere", isbn=DUNE) == InTrash(frozenset({mine.id}))

    def test_an_isbn_a_book_the_member_cannot_see_holds_is_hidden(self, db, member, other):
        _book(db, other, "Secret", isbn=DUNE, is_private=True)

        index = Index.build(db, member.id, Source.READING_HISTORY)

        assert index.recognise(title="Elsewhere", isbn=DUNE) == Hidden()

    def test_another_members_trashed_private_book_is_hidden_rather_than_in_the_trash(
        self, db, member, other
    ):
        """It is in their trash, not this Member's trash view."""
        _book(db, other, "Secret", isbn=DUNE, is_private=True, deleted_at=TRASHED)

        index = Index.build(db, member.id, Source.READING_HISTORY)

        assert index.recognise(title="Elsewhere", isbn=DUNE) == Hidden()

    def test_a_hidden_holder_outranks_one_in_the_trash(self, db, member, other):
        """`InTrash` promises every holder is one this Member could restore."""
        _book(db, member, "Dune", isbn=DUNE, deleted_at=TRASHED, copy_group="g")
        _book(db, other, "Dune", isbn=DUNE, is_private=True, copy_group="g")

        index = Index.build(db, member.id, Source.READING_HISTORY)

        assert index.recognise(title="Elsewhere", isbn=DUNE) == Hidden()

    def test_a_title_on_the_shelf_answers_before_an_isbn_held_off_it(self, db, member, other):
        """The ladder asks the shelf on both keys before it asks the table."""
        _book(db, other, "Secret", isbn=DUNE, is_private=True)
        mine = _book(db, member, "Dune")

        index = Index.build(db, member.id, Source.READING_HISTORY)

        assert index.recognise(title="Dune", isbn=DUNE) == Seen(mine.id)


class TestTheTieRule:
    def test_a_tie_inside_one_copy_group_takes_the_lowest_id(self, db, member):
        first = _book(db, member, "Dune", isbn=DUNE, copy_group="g")
        _book(db, member, "Dune", isbn=DUNE, copy_group="g")

        index = Index.build(db, member.id, Source.READING_HISTORY)

        assert index.recognise(title="Dune", isbn=DUNE) == Seen(first.id)

    def test_two_books_outside_one_copy_group_are_tied(self, db, member):
        one = _book(db, member, "Dune")
        two = _book(db, member, "Dune")

        index = Index.build(db, member.id, Source.READING_HISTORY)

        assert index.recognise(title="Dune") == Tied(frozenset({one.id, two.id}))

    def test_two_copy_groups_sharing_a_key_are_tied(self, db, member):
        one = _book(db, member, "Dune", author="Frank Herbert", copy_group="g")
        two = _book(db, member, "Dune", author="Frank Herbert", copy_group="h")

        index = Index.build(db, member.id, Source.CATALOGUE)

        assert index.recognise(title="Dune", author="Frank Herbert") == Tied(
            frozenset({one.id, two.id})
        )

    def test_a_tie_on_the_isbn_does_not_fall_through_to_the_title(self, db, member):
        """Two holders of one identifier are a stronger claim than a title."""
        one = _book(db, member, "Dune", isbn=DUNE)
        two = _book(db, member, "Dune Messiah", isbn=DUNE_TEN)

        index = Index.build(db, member.id, Source.READING_HISTORY)

        assert index.recognise(title="Dune Messiah", isbn=DUNE) == Tied(
            frozenset({one.id, two.id})
        )

    def test_readwise_waits_on_a_copy_group_tie(self, db, member):
        """Readwise's ruling of 2026-10-15 stands: the copy rule is the
        importers'."""
        for _ in range(2):
            book = _book(db, member, "Dune", author="Frank Herbert", copy_group="g")
            db.add(
                BookIdentifier(
                    book_id=book.id, scheme=BookIdentifierScheme.ASIN, value="B00B7NPRY8"
                )
            )
        db.commit()

        index = Index.build(db, member.id, Source.HIGHLIGHTS)

        answer = index.recognise(
            title="Dune",
            author="Frank Herbert",
            identifiers=((BookIdentifierScheme.ASIN, "b00b7npry8"),),
        )
        assert isinstance(answer, Tied)


class TestIsbnForms:
    def test_a_stored_isbn_ten_meets_the_isbn_thirteen_a_reader_produces(self, db, member):
        book = _book(db, member, "Dune", isbn=DUNE_TEN)

        index = Index.build(db, member.id, Source.CATALOGUE)

        assert index.recognise(title="Elsewhere", isbn=DUNE) == Seen(book.id)

    def test_a_hidden_isbn_ten_still_refuses_the_isbn_thirteen(self, db, member, other):
        _book(db, other, "Secret", isbn=DUNE_TEN, is_private=True)

        index = Index.build(db, member.id, Source.CATALOGUE)

        assert index.recognise(title="Elsewhere", isbn=DUNE) == Hidden()


class TestRemember:
    def test_a_book_created_during_the_import_answers_a_later_row(self, db, member):
        index = Index.build(db, member.id, Source.CATALOGUE)
        book = _book(db, member, "Dune", isbn=DUNE)

        index.remember(book)

        assert index.recognise(title="Elsewhere", isbn=DUNE) == Seen(book.id)
        assert index.sees(book.id)


class TestOneRecord:
    def test_an_asin_stored_in_lower_case_answers_one_sent_in_upper_case(self, db, member):
        """The read for one record compares exact spellings, so the index on
        the value serves it; this is the spelling that rule could lose."""
        book = _book(db, member, "Docker")
        db.add(BookIdentifier(book_id=book.id, scheme=BookIdentifierScheme.ASIN, value="b00j4yqkhy"))
        db.commit()

        answer = recognise_one(
            db,
            member.id,
            Source.STORE,
            identifiers=[(BookIdentifierScheme.ASIN, "B00J4YQKHY")],
        )

        assert answer == Seen(book.id)

    def test_a_volume_id_differing_only_in_case_is_another_volume(self, db, member):
        """Google's volume ids are case sensitive, so the case folding an ASIN
        takes would refuse an add of a different volume."""
        book = _book(db, member, "Dune")
        db.add(
            BookIdentifier(
                book_id=book.id, scheme=BookIdentifierScheme.GOOGLE_BOOKS, value="zytcalfpjgyc"
            )
        )
        db.commit()

        answer = recognise_one(
            db,
            member.id,
            Source.STORE,
            identifiers=[(BookIdentifierScheme.GOOGLE_BOOKS, "zyTCAlFPjgYC")],
        )

        assert answer == Unknown()

    def test_an_isbn_stored_with_hyphens_answers_the_canonical_one(self, db, member):
        """The full index keys every stored ISBN through `isbn.parse`, so the
        door has to find the spelling an exact comparison would miss."""
        book = _book(db, member, "Dune", isbn="978-0-441-01359-3")

        assert recognise_one(db, member.id, Source.ADD, isbn=DUNE) == Seen(book.id)

    def test_an_isbn_ten_stored_with_a_lower_case_x_answers_the_canonical_one(
        self, db, member
    ):
        book = _book(db, member, "Night Train", isbn=LOWER_X_TEN)

        assert recognise_one(db, member.id, Source.ADD, isbn=LOWER_X) == Seen(book.id)
