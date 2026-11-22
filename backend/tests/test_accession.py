"""The accession number's rules on the Python side alone.

What both implementations must agree on is in `conformance/cases/accession.json`;
what is here is what only this side does, or what a case file cannot state.
"""

import random

import pytest

import accession


class TestMinting:
    @pytest.mark.parametrize("book_id", [0, -1, accession.MAX_SERIAL + 1])
    def test_an_id_no_nine_digit_code_can_carry_is_refused(self, book_id: int):
        """Past the serial a code would be ten long, an ISBN-10's length."""
        with pytest.raises(ValueError, match="outside the range"):
            accession.mint(book_id)

    def test_every_minted_code_is_an_accession_number(self):
        ids = [1, accession.MAX_SERIAL, *random.Random(31).sample(range(1, accession.MAX_SERIAL), 500)]
        assert [book_id for book_id in ids if not accession.is_accession(accession.mint(book_id))] == []

    def test_every_minted_code_is_as_wide_as_the_column(self):
        assert len(accession.mint(accession.MAX_SERIAL)) == accession.ACCESSION_LENGTH


class TestTheCheckDigit:
    """The measurement Damm was chosen on, held rather than quoted."""

    @staticmethod
    def _codes() -> list[str]:
        return [
            accession.mint(book_id)
            for book_id in random.Random(25).sample(range(1, accession.MAX_SERIAL), 200)
        ]

    def test_no_single_digit_error_is_accepted(self):
        accepted = [
            mutated
            for code in self._codes()
            for position in range(len(code))
            for digit in "0123456789"
            if digit != code[position]
            and accession.is_accession(mutated := code[:position] + digit + code[position + 1 :])
        ]
        assert accepted == []

    def test_no_adjacent_transposition_is_accepted(self):
        accepted = [
            mutated
            for code in self._codes()
            for position in range(len(code) - 1)
            if code[position] != code[position + 1]
            and accession.is_accession(
                mutated := code[:position] + code[position + 1] + code[position] + code[position + 2 :]
            )
        ]
        assert accepted == []
