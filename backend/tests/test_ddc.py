"""Tests for backend/ddc.py.

Two behaviours and one invariant. The parse has to tell a classification
heading from an ordinary subject heading, because the DNB puts both in the same
element and reading `20. Jahrhundert` as the number `20.` invents a
classification nobody asserted. The projection has to be on the number, because
that is the only half of a heading that means the same in two languages. And
every tag name in the mapping has to be a tag that exists, or the suggestion
silently matches nothing.
"""

import ddc
from main import PREDEFINED_TAGS


class TestTheNotation:
    """The single normaliser. Three source paths used to have three answers to
    "what is a number", and the column exists to hold one."""

    def test_a_plain_number_is_itself(self):
        assert ddc.notation("004") == "004"

    def test_a_decimal_number_keeps_its_fraction(self):
        assert ddc.notation("005.133") == "005.133"

    def test_the_marc_segmentation_prime_is_stripped(self):
        """`005.13/3` and `005.133` are one heading. K10plus sends the first on
        53 of 463 live 082 values and the DNB stores the second, so rejecting
        the prime drops an eighth of one catalogue and keeping it raw makes two
        rows the unique index cannot collapse."""
        assert ddc.notation("005.13/3") == "005.133"

    def test_a_caption_is_not_a_number(self):
        """The flattened string this whole table exists to stop storing."""
        assert ddc.notation("004 Informatik") is None

    def test_a_call_number_from_another_scheme_is_not_one(self):
        assert ddc.notation("QA76.73.P98") is None

    def test_two_digits_are_not_a_dewey_number(self):
        assert ddc.notation("20") is None

    def test_surrounding_space_is_ignored(self):
        assert ddc.notation("  004  ") == "004"


class TestParsingAHeading:
    def test_a_ddc_heading_splits_into_number_and_caption(self):
        assert ddc.parse_heading("004 Informatik") == ("004", "Informatik")

    def test_a_caption_may_contain_commas(self):
        """The DNB's own captions do: this one is a real record's."""
        assert ddc.parse_heading("360 Soziale Probleme, Sozialdienste") == (
            "360",
            "Soziale Probleme, Sozialdienste",
        )

    def test_a_decimal_number_keeps_its_fraction(self):
        assert ddc.parse_heading("005.133 Programmiersprachen") == (
            "005.133",
            "Programmiersprachen",
        )

    def test_a_bare_number_is_a_heading_with_no_caption(self):
        """MARC 082 carries the notation alone: the schedule holds the words."""
        assert ddc.parse_heading("004") == ("004", None)

    def test_a_year_is_not_a_classification(self):
        """`20. Jahrhundert` is a subject heading. A looser pattern reads it as
        the number `20.` with the caption `Jahrhundert`, which invents a
        classification the catalogue never asserted."""
        assert ddc.parse_heading("20. Jahrhundert") is None

    def test_the_dnb_sachgruppe_letter_is_not_a_classification(self):
        """`B Belletristik` rides beside the DDC heading in every German
        fiction record and is the DNB's own code, not Dewey."""
        assert ddc.parse_heading("B Belletristik") is None

    def test_a_plain_subject_heading_is_not_one(self):
        assert ddc.parse_heading("Informatik") is None

    def test_a_captioned_heading_is_normalised_too(self):
        """The heading path and the bare number path are one normaliser, so a
        prime is stripped wherever it arrives."""
        assert ddc.parse_heading("005.13/3 Programmierung") == (
            "005.133",
            "Programmierung",
        )


class TestTheDivision:
    def test_a_three_digit_number_gives_its_division(self):
        assert ddc.division("004") == "000"

    def test_a_decimal_number_gives_the_same_division(self):
        """`005.133` and `004` are one suggestion, not two."""
        assert ddc.division("005.133") == "000"

    def test_a_number_that_is_not_dewey_gives_nothing(self):
        assert ddc.division("QA76.73") is None

    def test_a_two_digit_string_is_not_a_dewey_number(self):
        assert ddc.division("20") is None

    def test_a_caption_is_not_read_as_a_division(self):
        """`division` goes through `notation`, so `004 Informatik` is refused
        rather than read as `000` with the caption silently discarded."""
        assert ddc.division("004 Informatik") is None

    def test_a_primed_number_divides_like_its_canonical_form(self):
        assert ddc.division("005.13/3") == ddc.division("005.133")


class TestProjectingToTags:
    def test_the_number_decides_and_not_the_caption(self):
        """The whole point: a German record and an English one resolve alike."""
        assert ddc.tag_names(["004"]) == ["Computing"]

    def test_two_numbers_in_one_division_suggest_one_tag(self):
        assert ddc.tag_names(["004", "005.133"]) == ["Computing"]

    def test_german_literature_suggests_fiction(self):
        """`830 Deutsche Literatur` is on most German novels the DNB holds, and
        its caption matches no seeded tag."""
        assert ddc.tag_names(["830"]) == ["Fiction"]

    def test_an_unmapped_division_suggests_nothing(self):
        """040 is unassigned in the schedule. Absent is a real answer."""
        assert ddc.tag_names(["040"]) == []

    def test_something_that_is_not_a_number_is_skipped(self):
        assert ddc.tag_names(["QA76.73.P98 V53 2021"]) == []

    def test_the_order_of_the_numbers_is_kept(self):
        assert ddc.tag_names(["150", "004"]) == ["Psychology", "Computing"]


def test_every_mapped_tag_name_is_a_seeded_tag():
    """A typo here would produce a suggestion that matches nothing, silently.

    The projection looks a tag up by name, so a value that is not in
    `PREDEFINED_TAGS` is not an error anywhere: the book just never gets the
    suggestion, and nothing says why.
    """
    seeded = {name for name, _category in PREDEFINED_TAGS}
    unknown = sorted(set(ddc.DIVISION_TAGS.values()) - seeded)

    assert unknown == []


def test_every_key_is_a_division():
    """The mapping is division level by design: `ddc.division` produces keys of
    exactly this shape, so a key of any other shape can never be looked up."""
    wrong = sorted(
        key
        for key in ddc.DIVISION_TAGS
        if len(key) != 3 or not key.isdigit() or not key.endswith("0")
    )

    assert wrong == []
