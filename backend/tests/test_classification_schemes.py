"""Tests for classification_schemes.py: which schemes are built in, defining,
renaming and deleting a library's own, and what a restore inserts."""

import pytest

import classification_schemes
import filing
from enums import ClassificationScheme, FilingRuleName
from models import CLASSIFICATION_SCHEME_NAME_MAX, Book, Classification, ClassificationSchemeRow, User


@pytest.fixture
def reader(db) -> User:
    account = User(username="reader", password_hash="x")
    db.add(account)
    db.commit()
    return account


@pytest.fixture
def stranger(db, reader) -> User:
    account = User(username="stranger", password_hash="x")
    db.add(account)
    db.commit()
    return account


def _quote(db, scheme: str, *, owner: User, private: bool = False) -> Book:
    book = Book(title="Quoting", added_by_user_id=owner.id, is_private=private)
    db.add(book)
    db.flush()
    db.add(Classification(book_id=book.id, scheme=scheme, number="ST 250"))
    db.flush()
    return book


class TestTheBuiltInSchemes:
    def test_only_the_two_shelf_schemes_order_a_shelf(self):
        assert classification_schemes.SHELF_SCHEMES == (ClassificationScheme.DDC, ClassificationScheme.LCC)

    def test_the_subject_vocabularies_file_under_the_generic_rule(self):
        """They are authority files, not shelf orders, so they have no schedule."""
        built_in = classification_schemes.BUILT_IN
        assert built_in[ClassificationScheme.GND].filing is FilingRuleName.GENERIC
        assert built_in[ClassificationScheme.LCSH].filing is FilingRuleName.GENERIC

    def test_a_built_in_scheme_cannot_be_renamed(self, db):
        row = db.get(ClassificationSchemeRow, "ddc")
        with pytest.raises(classification_schemes.Refused):
            classification_schemes.rename(db, row, "Dewey")

    def test_a_built_in_scheme_cannot_be_deleted_though_nothing_quotes_it(self, db, reader):
        row = db.get(ClassificationSchemeRow, "lcsh")
        with pytest.raises(classification_schemes.Refused):
            classification_schemes.remove(db, row, reader.id)


class TestALibrarysOwnScheme:
    def test_its_numbers_file_under_the_rule_it_was_defined_with(self, db, reader):
        classification_schemes.define(db, "rvk", "Regensburger Verbundklassifikation", FilingRuleName.LCC)
        book = _quote(db, "rvk", owner=reader)

        assert book.classifications[0].sort_key == filing.LIBRARY_OF_CONGRESS.sort_key("ST 250")

    def test_a_code_already_taken_is_refused(self, db):
        with pytest.raises(classification_schemes.Refused):
            classification_schemes.define(db, "gnd", "Another GND", FilingRuleName.GENERIC)

    def test_one_no_book_quotes_is_deleted(self, db, reader):
        row = classification_schemes.define(db, "rvk", "RVK", FilingRuleName.GENERIC)
        classification_schemes.remove(db, row, reader.id)

        assert db.get(ClassificationSchemeRow, "rvk") is None

    def test_deleting_one_a_book_quotes_is_refused_naming_the_count(self, db, reader):
        row = classification_schemes.define(db, "rvk", "RVK", FilingRuleName.GENERIC)
        _quote(db, "rvk", owner=reader)
        _quote(db, "rvk", owner=reader)

        with pytest.raises(
            classification_schemes.StillQuoted, match=r"^2 books you can see still use"
        ) as refusal:
            classification_schemes.remove(db, row, reader.id)
        assert refusal.value.count == 2
        assert db.get(ClassificationSchemeRow, "rvk") is not None

    def test_the_count_is_of_the_books_the_caller_can_see_and_says_so(self, db, reader, stranger):
        """Owner, 2026-11-20: the visible count, worded as what it is. A
        stranger's private book blocks the delete and is not counted."""
        row = classification_schemes.define(db, "rvk", "RVK", FilingRuleName.GENERIC)
        _quote(db, "rvk", owner=reader)
        _quote(db, "rvk", owner=stranger)
        _quote(db, "rvk", owner=stranger, private=True)

        with pytest.raises(
            classification_schemes.StillQuoted, match=r"^2 books you can see still use"
        ) as refusal:
            classification_schemes.remove(db, row, reader.id)
        assert refusal.value.count == 2

    def test_a_refusal_over_books_the_caller_cannot_see_gives_no_count(self, db, reader, stranger):
        """A number would say how many of somebody else's private books quote it."""
        row = classification_schemes.define(db, "rvk", "RVK", FilingRuleName.GENERIC)
        _quote(db, "rvk", owner=stranger, private=True)

        with pytest.raises(classification_schemes.StillQuoted) as refusal:
            classification_schemes.remove(db, row, reader.id)
        assert not any(character.isdigit() for character in str(refusal.value))
        assert refusal.value.count == 0


class TestWhatARestoreInserts:
    def test_an_archive_without_the_table_gets_the_built_in_rows(self):
        restored = classification_schemes.restorable([], [])

        assert restored == classification_schemes.seed_rows()

    def test_a_code_only_a_heading_quotes_gets_a_row_named_after_it(self):
        restored = classification_schemes.restorable([], [{"scheme": "udc", "number": "004"}])

        assert {"code": "udc", "name": "udc", "filing": "generic"} in restored

    @pytest.mark.parametrize("name", [None, "", "  ", 7])
    def test_a_row_with_no_usable_name_is_named_after_its_code(self, name):
        restored = classification_schemes.restorable([{"code": "rvk", "name": name, "filing": "lcc"}], [])

        assert {"code": "rvk", "name": "rvk", "filing": "lcc"} in restored

    def test_a_name_longer_than_the_column_is_clipped(self):
        restored = classification_schemes.restorable([{"code": "rvk", "name": "R" * 200}], [])

        assert {"code": "rvk", "name": "R" * CLASSIFICATION_SCHEME_NAME_MAX, "filing": "generic"} in restored

    def test_a_rule_the_archive_misspells_files_as_text(self):
        restored = classification_schemes.restorable(
            [{"code": "rvk", "name": "RVK", "filing": "rvk-order"}], []
        )

        assert {"code": "rvk", "name": "RVK", "filing": "generic"} in restored
