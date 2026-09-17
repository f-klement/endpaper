"""Tests for `backend/enums.py`: the read end of an unconstrained enum column."""

import logging
from enum import StrEnum

import pytest

from enums import (
    BookCondition,
    BookFormat,
    CustomFieldKind,
    LendingWillingness,
    member_or,
)


class Colour(StrEnum):
    """A local enum, so a table of cases cannot be read as a claim about a
    column somebody may later change."""

    RED = "red"
    BLUE = "blue"


class TestMemberOr:
    """`(enum, stored) -> member | default`, with no session and no HTTP.

    The whole reason this is a function rather than a `try` at each read: the
    rule can be shown as a table. Before it existed, the only way to reach the
    poisoned row path was to restore an archive.
    """

    @pytest.mark.parametrize(
        ("stored", "expected"),
        [
            ("red", Colour.RED),
            ("blue", Colour.BLUE),
            (Colour.RED, Colour.RED),
            ("green", None),
            ("", None),
            ("RED", None),
            (" red", None),
            (None, None),
            (7, None),
            (object(), None),
        ],
    )
    def test_it_answers_a_member_or_the_default(self, stored, expected) -> None:
        assert member_or(Colour, stored, None) is expected

    def test_the_default_is_the_callers_and_is_not_always_none(self) -> None:
        assert member_or(Colour, "green", Colour.BLUE) is Colour.BLUE

    def test_a_missing_value_takes_the_default_without_complaining(
        self, caplog
    ) -> None:
        """NULL is the column saying nobody answered, which is not a stray
        value and is not worth a line in a log."""
        with caplog.at_level(logging.WARNING, logger="endpaper.enums"):
            assert member_or(Colour, None, Colour.RED) is Colour.RED
        assert caplog.records == []

    def test_a_stray_value_is_logged_with_what_it_was(self, caplog) -> None:
        """The degrade is data loss nobody can see: a restore goes quiet, and
        afterwards nothing says which rows changed their reading. So the value
        that arrived is in the message rather than only the fact that one did.
        """
        with caplog.at_level(logging.WARNING, logger="endpaper.enums"):
            member_or(Colour, "puce", None)

        assert len(caplog.records) == 1
        assert "puce" in caplog.records[0].getMessage()

    def test_the_context_names_the_row_when_the_caller_knows_it(
        self, caplog
    ) -> None:
        """A column type reading a value does not know which row it came out
        of. `custom_fields._kind_of` does, and that is the difference the
        keyword exists for."""
        with caplog.at_level(logging.WARNING, logger="endpaper.enums"):
            member_or(Colour, "puce", None, context="custom_fields.kind on field 3")

        assert "field 3" in caplog.records[0].getMessage()

    @pytest.mark.parametrize(
        "enum", [BookFormat, BookCondition, LendingWillingness, CustomFieldKind]
    )
    def test_every_member_of_a_real_enum_survives_a_round_trip(self, enum) -> None:
        """The rule is only safe if it is inert on good data. A degrade that
        also rewrote a valid value would be invisible in exactly the same way,
        and worse.

        Derived from the enum rather than listed, so a new member is covered on
        the commit that adds it.
        """
        for member in enum:
            assert member_or(enum, member.value, None) is member
