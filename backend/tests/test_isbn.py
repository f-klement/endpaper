"""Tests for backend/isbn.py.

Each class below pins one of the four defects the previous implementation had.
The old rule was a bare regex, `^(97[89]\\d{10}|\\d{10})$`, with no checksum,
no normalisation and no ISBN-10/13 equivalence.
"""

import pytest

from isbn import (
    equivalent_forms,
    is_valid,
    is_valid_isbn10,
    is_valid_isbn13,
    isbn10_to_isbn13,
    isbn13_to_isbn10,
    normalise,
    parse,
)

# Real ISBNs, in both forms, for books that exist.
DUNE_13 = "9780441013593"
DUNE_10 = "0441013597"
# An ISBN-10 whose check digit is X. Roughly one in eleven ends this way.
X_CHECK_10 = "043942089X"


class TestNormalise:
    @pytest.mark.parametrize(
        "raw", ["978-0-441-01359-3", "978 0 441 01359 3", "  9780441013593  "]
    )
    def test_strips_the_grouping_publishers_use(self, raw):
        assert normalise(raw) == DUNE_13

    def test_upper_cases_the_check_digit(self):
        assert normalise("043942089x") == X_CHECK_10


class TestIsbn13Checksum:
    def test_accepts_a_real_isbn(self):
        assert is_valid_isbn13(DUNE_13) is True

    def test_rejects_a_single_wrong_digit(self):
        # Previously accepted: no checksum was verified at all, so one misread
        # digit produced a lookup for a book that cannot exist.
        assert is_valid_isbn13("9780441013594") is False

    def test_rejects_transposed_digits(self):
        assert is_valid_isbn13("9780441013539") is False

    @pytest.mark.parametrize("candidate", ["978044101359", "97804410135933", "978044101359X"])
    def test_rejects_wrong_length_or_non_digits(self, candidate):
        assert is_valid_isbn13(candidate) is False


class TestIsbn10Checksum:
    def test_accepts_a_real_isbn(self):
        assert is_valid_isbn10(DUNE_10) is True

    def test_accepts_an_x_check_digit(self):
        """The defect that rejected roughly one older book in eleven."""
        assert is_valid_isbn10(X_CHECK_10) is True

    def test_rejects_a_wrong_check_digit(self):
        assert is_valid_isbn10("0441013590") is False

    def test_rejects_x_anywhere_but_the_end(self):
        assert is_valid_isbn10("X441013597") is False


class TestConversion:
    def test_isbn10_becomes_the_matching_isbn13(self):
        assert isbn10_to_isbn13(DUNE_10) == DUNE_13

    def test_an_x_check_digit_converts(self):
        converted = isbn10_to_isbn13(X_CHECK_10)
        assert is_valid_isbn13(converted)

    def test_round_trips(self):
        assert isbn10_to_isbn13(isbn13_to_isbn10(DUNE_13) or "") == DUNE_13

    def test_979_has_no_isbn10_form(self):
        # The 979 range exists precisely because 978 ran out of numbers.
        assert isbn13_to_isbn10("9791234567896") is None


class TestParse:
    def test_returns_the_canonical_form_unchanged(self):
        assert parse(DUNE_13) == DUNE_13

    def test_converts_an_isbn10_to_isbn13(self):
        """This is what makes the unique constraint mean anything: the same
        book scanned in either form lands on one stored value."""
        assert parse(DUNE_10) == DUNE_13

    @pytest.mark.parametrize("raw", ["978-0-441-01359-3", " 9780441013593 ", "0-441-01359-7"])
    def test_accepts_the_forms_people_actually_paste(self, raw):
        assert parse(raw) == DUNE_13

    def test_accepts_an_x_check_digit(self):
        assert parse(X_CHECK_10) is not None

    @pytest.mark.parametrize(
        "raw",
        ["9780441013594", "0441013590", "12345", "not an isbn", "", None],
        ids=["bad-13", "bad-10", "too short", "words", "empty", "none"],
    )
    def test_rejects_what_is_not_an_isbn(self, raw):
        assert parse(raw) is None

    def test_rejects_a_valid_ean13_that_is_not_a_book(self):
        """A food packet's barcode passes the EAN-13 checksum. It is not a
        book, and must not reach the metadata lookup."""
        assert parse("5012345678900") is None

    def test_accepts_the_979_range(self):
        assert parse("9791234567896") == "9791234567896"

    def test_is_valid_agrees_with_parse(self):
        assert is_valid(DUNE_10) is True
        assert is_valid("9780441013594") is False


class TestEquivalentForms:
    def test_lists_both_spellings(self):
        # Rows written before canonicalisation hold the ISBN-10, so a
        # duplicate check has to look for both or the book is added twice.
        assert set(equivalent_forms(DUNE_13)) == {DUNE_13, DUNE_10}

    def test_is_the_same_set_from_either_input(self):
        assert set(equivalent_forms(DUNE_10)) == set(equivalent_forms(DUNE_13))

    def test_a_979_isbn_has_only_one_form(self):
        assert equivalent_forms("9791234567896") == ["9791234567896"]

    def test_an_invalid_isbn_has_no_forms(self):
        assert equivalent_forms("nonsense") == []
