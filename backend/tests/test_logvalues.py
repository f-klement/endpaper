"""Tests for `backend/logvalues.py`: the bound on what an untrusted value logs."""

import logging

import pytest
from sqlalchemy import insert, text
from sqlalchemy.exc import DBAPIError, StatementError

from enums import BookFormat, member_or
from logvalues import LOGGED_VALUE_MAX, clipped
from models import Book


class TestClipped:
    def test_a_short_value_is_left_alone(self) -> None:
        assert clipped("ebook") == "'ebook'"

    def test_a_long_value_is_cut_and_says_it_was(self) -> None:
        text_out = clipped("x" * 10_000)

        assert len(text_out) == LOGGED_VALUE_MAX + 3
        assert text_out.endswith("...")

    @pytest.mark.parametrize("value", [7, None, {"a": 1}, [1, 2], object()])
    def test_it_takes_anything_a_column_can_hold(self, value) -> None:
        """Slicing the value rather than its repr raises `TypeError` on every
        one of these, and an archive supplies all of them."""
        assert len(clipped(value)) <= LOGGED_VALUE_MAX + 3

    def test_a_newline_cannot_forge_a_second_log_line(self) -> None:
        """`repr` before the slice, which is what escapes it. A log reader
        splits on newlines, so an unescaped one is a second entry the attacker
        wrote."""
        assert "\n" not in clipped("ebook\nWARNING something else entirely")


class TestTheDegradeCannotFillADisk:
    """The read end degrade fires once per row per column on every read, and
    the column's declared length bounds nothing: SQLite stores as many
    characters as it is given in a `VARCHAR(20)`.
    """

    def test_a_long_stray_value_logs_a_bounded_line(self, db, caplog) -> None:
        book = Book(title="Poisoned")
        db.add(book)
        db.commit()
        book_id = book.id
        db.execute(
            text("UPDATE books SET format = :value WHERE id = :id"),
            {"value": "x" * 100_000, "id": book_id},
        )
        db.commit()
        db.expunge_all()

        with caplog.at_level(logging.WARNING, logger="endpaper.enums"):
            assert db.get(Book, book_id).format is None

        assert len(caplog.records) == 1
        assert len(caplog.records[0].getMessage()) < 400

    def test_the_column_still_refuses_a_shape_a_string_column_refuses(
        self, db
    ) -> None:
        """The write half. `str()` in the bind would store `"{'a': 1}"` here,
        which is a forged value in a column whose read end then logs it on every
        page. An archive carries dictionaries and `backup._parse_row` passes
        them through untouched.

        **Through the mapped table, which is the door `backup.restore` uses**
        (`backup.py`, Core insert). The first version of this test wrote through
        `text(...).bindparams(...)`, whose bind has `NullType`, so
        `process_bind_param` was never called at all: measured, that shape is
        refused by sqlite3 either way and the test therefore **passed with the
        defect put back**. A test that cannot see the code it names is the
        weaker half of a pair that looks like two.
        """
        with pytest.raises((DBAPIError, StatementError)):
            db.execute(insert(Book), {"title": "Shaped", "format": {"a": 1}})
        db.rollback()

    def test_a_member_still_binds_as_its_value(self, db) -> None:
        """What dropping the coercion could have broken, pinned rather than
        assumed."""
        book = Book(title="Sound", format=BookFormat.AUDIOBOOK)
        db.add(book)
        db.commit()

        stored = db.execute(
            text("SELECT typeof(format), format FROM books WHERE id = :id"),
            {"id": book.id},
        ).one()

        assert stored == ("text", "audiobook")


def test_member_or_clips_through_the_same_helper(caplog) -> None:
    """One bound, not two. A second constant here would be the fact stored
    twice that this module exists to stop."""
    with caplog.at_level(logging.WARNING, logger="endpaper.enums"):
        member_or(BookFormat, "y" * 10_000, None)

    assert len(caplog.records[0].getMessage()) < LOGGED_VALUE_MAX + 200
