"""The filing rules: what each scheme claims about its numbers and how it sorts them.

The Python half only. The SQL half of every rule is compared against real
SQLite in `test_shelf.py::TestTheFilingKeysAgree`, because a key that a test
recomputes in Python agrees with itself and says nothing about the database
that actually orders the listing.
"""

import pytest

import ddc
import filing
from enums import ClassificationScheme

#: Call numbers the two live sources have supplied, kept as they were stored.
#:
#: `metadata.py` writes an LCC number with no normaliser at all, so what the
#: column holds is what the catalogue wrote with its whitespace collapsed. The
#: Library of Congress row is the one `BookSort.DDC` was measured against on
#: 2026-08-29; the rest are Open Library `lc_classifications` shapes.
REAL_CALL_NUMBERS = [
    "BF575.S75 E64 2022",
    "PR6068.O93 H37 1997",
    "HQ1090.3 .M67 1999",
    "QA76.73.J38 F57 2020",
    "KJC1234.5 .A2 1976",
    "PZ8.3.G276Ci",
    "Q1",
]


class TestTheGenericRule:
    """A rule with no schedule, which is the fallback for every other one."""

    def test_makes_no_claim_about_a_number(self):
        """It recognises everything, and that is an admission rather than a pass.

        Answering False would say a value is not a call number, which is a
        claim a rule with no schedule has nothing to check against.
        """
        assert filing.GENERIC.recognises("Hello world")
        assert filing.GENERIC.recognises("")

    def test_files_a_value_as_its_own_text(self):
        assert filing.GENERIC.sort_key("BF575.S75 E64 2022") == "BF575.S75 E64 2022"

    def test_orders_no_shelf(self):
        """The one rule that refuses to.

        Sorting an unrecognised scheme's values as text is honest; offering
        that as a shelf order would promise an order nobody has verified,
        which is the defect this module exists to fix.
        """
        assert filing.GENERIC.orders_a_shelf is False


class TestTheDeweyRule:
    def test_recognises_a_notation_and_refuses_what_is_not_one(self):
        assert filing.DEWEY.recognises("155.9042")
        assert not filing.DEWEY.recognises("BF575.S75 E64 2022")
        assert not filing.DEWEY.recognises("Hello world")

    @pytest.mark.parametrize(
        "number",
        [f"{n:03d}" for n in range(0, 1000, 7)] + ["005.133", "005.13/3", "823.912"],
    )
    def test_the_key_is_what_the_notation_parser_would_have_returned(self, number):
        """The rule and the parser are one fact, so the key is derived rather than stated.

        Restricted to values with no whitespace at their edges, which is every
        value this column can hold: `ClassificationIn.tidy_number` collapses it
        at every door. `DeweyFiling.sort_key` says why it does not strip.
        """
        assert filing.DEWEY.sort_key(number) == ddc.notation(number)

    def test_text_order_is_shelf_order_across_the_whole_schedule(self):
        """Derived against `float`, not asserted from a handful of examples.

        This is the property the rule rests on: a notation carries exactly
        three leading digits, so a plain string comparison reproduces the
        numeric one. All 1,000 three digit numbers plus 200 fractions, sorted
        both ways and compared as sequences.
        """
        numbers = [f"{n:03d}" for n in range(1000)]
        numbers += [f"{n:03d}.{n % 97:04d}" for n in range(0, 1000, 5)]

        by_key = sorted(numbers, key=filing.DEWEY.sort_key)
        by_value = sorted(numbers, key=float)

        assert by_key == by_value

    def test_removes_the_segmentation_prime_a_stored_row_can_carry(self):
        """`005.13/3` and `005.133` are one heading and file as one.

        Reachable rather than hypothetical: `ClassificationIn` validates
        through `ddc.notation` and does not write its answer back, so the
        prime survives into the column.
        """
        assert filing.DEWEY.sort_key("005.13/3") == filing.DEWEY.sort_key("005.133")

    def test_orders_a_shelf(self):
        assert filing.DEWEY.orders_a_shelf is True


class TestTheLibraryOfCongressRule:
    @pytest.mark.parametrize("number", REAL_CALL_NUMBERS)
    def test_recognises_the_call_numbers_the_sources_supply(self, number):
        assert filing.LIBRARY_OF_CONGRESS.recognises(number)

    def test_refuses_a_number_from_another_scheme(self):
        assert not filing.LIBRARY_OF_CONGRESS.recognises("155.9042")
        assert not filing.LIBRARY_OF_CONGRESS.recognises("Stress management")

    def test_files_a_shorter_class_number_before_a_longer_one(self):
        """The defect this whole module was opened for.

        `BF75` stands before `BF575` on a shelf and after it in a string
        comparison, so a Dewey rule applied to LCC reverses them.
        """
        assert sorted(["BF575", "BF75"], key=filing.LIBRARY_OF_CONGRESS.sort_key) == [
            "BF75",
            "BF575",
        ]

    def test_files_a_class_number_before_its_own_decimal_extension(self):
        """`BF575.S75` is class 575 with a cutter; `BF575.5.S75` is class 575.5.

        The one place the remainder cannot be left as text: comparing `.S75`
        against `.5.S75` puts the digit first and reverses them.
        """
        order = sorted(
            ["BF575.5.S75", "BF575.S75"], key=filing.LIBRARY_OF_CONGRESS.sort_key
        )

        assert order == ["BF575.S75", "BF575.5.S75"]

    def test_reads_a_cutter_as_a_decimal_fraction(self):
        """`.S75` is 0.75 and `.S8` is 0.8, so the longer one files first.

        No padding needed for this: lexicographic order over digit strings is
        already decimal fraction order. The test is here because that is the
        argument for leaving the remainder verbatim.
        """
        order = sorted(
            ["BF575.S8", "BF575.S75"], key=filing.LIBRARY_OF_CONGRESS.sort_key
        )

        assert order == ["BF575.S75", "BF575.S8"]

    def test_keeps_the_boundary_between_two_cutters(self):
        """Why the separator is kept rather than stripped.

        `S7 A1` is cutter 0.7 then a second cutter; `S75` is cutter 0.75, so
        `S7` files first. With the dots and spaces removed both begin `S7` and
        the shorter cutter files second, which is wrong.
        """
        order = sorted(
            ["BF575.S75", "BF575.S7 A1"], key=filing.LIBRARY_OF_CONGRESS.sort_key
        )

        assert order == ["BF575.S7 A1", "BF575.S75"]

    def test_files_a_one_letter_class_before_a_two_letter_one(self):
        """Which is why the letters are padded with a space rather than a letter."""
        order = sorted(["QA1", "Q1"], key=filing.LIBRARY_OF_CONGRESS.sort_key)

        assert order == ["Q1", "QA1"]

    def test_reads_the_class_letters_in_either_case(self):
        assert filing.LIBRARY_OF_CONGRESS.sort_key(
            "bf575"
        ) == filing.LIBRARY_OF_CONGRESS.sort_key("BF575")

    def test_files_a_value_it_cannot_read_under_the_generic_rule(self):
        """Rather than raising or dropping it.

        The column holds whatever a catalogue wrote, and a shelf order that
        omits a row is worse than one that files it by its text.
        """
        assert filing.LIBRARY_OF_CONGRESS.sort_key(
            "no such call number"
        ) == filing.GENERIC.sort_key("no such call number")

    def test_orders_a_shelf(self):
        assert filing.LIBRARY_OF_CONGRESS.orders_a_shelf is True


class TestWhichRuleFilesWhichScheme:
    def test_every_published_scheme_has_a_rule(self):
        """Parametrised over the enum, so a fifth member is covered on the day
        it is added rather than the day somebody remembers this file."""
        assert set(filing.FILING_RULES) == set(ClassificationScheme)

    def test_a_scheme_with_no_rule_files_under_the_generic_one(self):
        """The fallback `FILING_RULES` documents, exercised rather than described.

        Reached with a value outside the enum because every member has an
        entry, which is the state the test above pins.
        """
        unknown = "udc"

        assert filing.rule_for(unknown) is filing.GENERIC  # type: ignore[arg-type]

    def test_only_the_two_shelf_schemes_order_a_shelf(self):
        assert filing.SHELF_SCHEMES == (
            ClassificationScheme.DDC,
            ClassificationScheme.LCC,
        )

    def test_the_shelf_schemes_are_derived_from_the_rules(self):
        """The other direction, so the tuple cannot drift from what it describes."""
        assert set(filing.SHELF_SCHEMES) == {
            scheme
            for scheme, rule in filing.FILING_RULES.items()
            if rule.orders_a_shelf
        }

    def test_the_subject_vocabularies_file_under_the_generic_rule(self):
        """They are authority files, not shelf orders, so they have no schedule."""
        assert filing.rule_for(ClassificationScheme.GND) is filing.GENERIC
        assert filing.rule_for(ClassificationScheme.LCSH) is filing.GENERIC

    def test_the_rules_are_named_as_the_reference_implementation_names_them(self):
        """Koha seeds `dewey`, `lcc` and `generic`. Keeping the spellings is
        what lets a reader match this against the design it came from."""
        assert {rule.name for rule in filing.FILING_RULES.values()} == {
            "dewey",
            "lcc",
            "generic",
        }
