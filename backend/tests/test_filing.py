"""The filing rules: what each scheme claims about its numbers and how it sorts them.

A rule is one implementation now, and `CORPUS` below is the corpus every reader
of it is held against: the column `models.Classification` stores
(`test_shelf.py::TestTheStoredKeyIsTheRulesKey`), the derivation
`backup.restore` performs, and the copy of the rule that revision `f1c30ab27d84`
carries (`test_schema.py::TestTheStoredShelfKey`). It lives here because it is a
corpus of call numbers, and because the coverage it has to reach is a property
of `filing._LCC`.
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

#: Call numbers whose only job is to reach a class shape the live ones miss.
#:
#: A shape is (class letters, class integer digits), and there are twelve.
#: `REAL_CALL_NUMBERS` and the values below it reach six between them, so half
#: the schedule was carried by no fixture at all and one shape, three letters
#: and four digits, was carried by `KJC1234.5 .A2 1976` alone. Measured against
#: this tree before these were added: `CORPUS` 6 of 12, a seeded 400 value
#: random corpus 6 of 12, either 9, and `(1,3)`, `(1,4)` and `(3,3)` reached by
#: nothing.
#:
#: **Two per shape rather than one**, which is the whole point of adding them:
#: a single fixture is a gap that reopens the day somebody trims a line in a
#: tidy up, and nothing would say so.
#: `TestTheCorpusReachesEveryClassShape` is what refuses that.
#:
#: Real classes, not `AAA1111`: `E` is American history, `D` world history, `Z`
#: bibliography, `KJC` European law and `KFN` the law of a state of the United
#: States, so a reader can check a shape against a schedule rather than against
#: this list.
SHAPE_FIXTURES = [
    "E11 .A5 1999",
    "D16.9 .B7",
    "E184.A1 J3 2004",
    "D731 .B4 1990",
    "Z8001 .A1",
    "E1234.5 .S5",
    "KJC1 .A2",
    "KFN5",
    "KJC12 .A2",
    "KFN52.5 .B7",
    "KJC123 .A2 1976",
    "KFN525 .B7 2001",
    "KFN1234 .S5 2001",
]

#: The values a filing rule is measured against, wherever it is read.
#:
#: **Chosen to break a rule apart, not to be representative.** The call numbers
#: the live sources supply, both spellings of the cutter separator, the two
#: boundaries the caps sit on (`_LETTERS_WIDTH` at `ABCD1`, `_DECIMAL_WIDTH` at
#: `QA76.1234567`), the class decimal against a cutter, values that fall to the
#: generic rule, characters the class ranges refuse, and `SHAPE_FIXTURES` for
#: the twelve class shapes.
#:
#: **The NUL is a fixture rather than an omission, and it is one this change
#: bought.** While the rule was also written in SQL, a stored NUL keyed
#: differently on the two sides, because SQLite's string functions stop at one
#: and Python's do not, so the corpus could not carry it and the divergence was
#: recorded as a known mis-sort. There is one implementation now and the key is
#: stored rather than computed in SQL, so the NUL is carried like any other
#: character: measured through the driver, `'QA \x00 76'` round trips byte for
#: byte and compares as text. `ClassificationIn.tidy_number` still refuses one
#: at every door; `backup.restore` is the path that can still put one here.
CORPUS = [
    *REAL_CALL_NUMBERS,
    *SHAPE_FIXTURES,
    "BF575.5.S75",
    "BF575.S7 A1",
    "BF75",
    "QA1",
    "ABCD1",
    "A1B2",
    "QA76.1234567",
    "QA76.",
    "QA76..5",
    "bf575",
    "155.9042",
    "005.13/3",
    "004",
    "Hello world",
    "",
    " ",
    "ü9",
    "٣٤",
    "ẞ1",
    "-1",
    "[]{}",
    "QA76\nS75",
    "QA76\tS75",
    "QA76\rS75",
    "QA \x00 76",
]

#: Every (class letters, class integer digits) pair a call number can have.
#:
#: Derived from the two widths `filing._LCC` is built out of, so widening either
#: grows this set and the corpus has to grow with it. Twelve today.
EVERY_CLASS_SHAPE = frozenset(
    (letters, digits)
    for letters in range(1, filing._LETTERS_WIDTH + 1)
    for digits in range(1, filing._INTEGER_WIDTH + 1)
)


def class_shape(value: str) -> tuple[int, int] | None:
    """Which shape a value has, asked of production's own expression.

    None where `filing._LCC` refuses the value, which is the generic rule's
    territory and not a shape.
    """
    match = filing._LCC.fullmatch(value)
    return None if match is None else (len(match.group(1)), len(match.group(2)))


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

    def test_files_two_class_decimals_in_numeric_order(self):
        """`QA76.45` is class 76.45 and `QA76.5` is class 76.5, so the first
        files before the second.

        **The direction the class decimal is padded in, and nothing else
        reaches it.** The two other paddings are pinned by keys asserted
        literally elsewhere in this file, and those assert an *empty* decimal,
        which pads to the same six zeroes whichever end it is filled from.
        Measured: with `ljust` turned to `rjust` here the whole of
        `test_filing.py`, `test_shelf.py`, `test_models.py` and
        `test_backup.py` stays green, and the only thing that goes red is the
        comparison against revision `f1c30ab27d84`'s copy of the rule, which
        by this project's own rule stops tracking `filing.py` the first time a
        rule legitimately changes.
        """
        order = sorted(
            ["QA76.5", "QA76.45"], key=filing.LIBRARY_OF_CONGRESS.sort_key
        )

        assert order == ["QA76.45", "QA76.5"]

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


class TestTheCorpusReachesEveryClassShape:
    """`CORPUS` is the instrument every reader of a filing rule is measured
    with, so what it does not reach is what nothing measures.

    **The residual this closes, stated as it was measured.** While the rule was
    written twice, two guards pinned that the SQL expression built one arm per
    shape and that it read production's own tuple of shapes. Neither could see
    a rewrite with the same number of arms and different shapes, and the
    docstring deferred that to key agreement, which is this corpus. It reached
    9 of the 12 shapes, and the documented escape was caught by one fixture.

    The second implementation is gone and the residual has moved rather than
    closed: revision `f1c30ab27d84` carries a copy of the rule, because a
    migration describes the data as it was on the day it ran, and this corpus is
    the only thing holding that copy to the original. A shape it does not reach
    is a shape the copy may get wrong in silence.
    """

    #: Two, not one. A shape carried by a single fixture is a gap that reopens
    #: the day somebody trims a line, and the trim is what nothing would notice.
    MINIMUM_PER_SHAPE = 2

    def test_every_shape_has_more_than_one_fixture(self):
        """So no single deletion can take a shape out of the corpus."""
        counted = dict.fromkeys(EVERY_CLASS_SHAPE, 0)
        # Collected and asserted rather than left to `counted[shape] += 1`
        # raising. A shape the expression produces that `EVERY_CLASS_SHAPE` does
        # not hold is a real failure, and until this line it was reported by a
        # `KeyError`: an error rather than an assertion, and one a later tidy to
        # a `Counter` or a `.get` would have removed without anything going red.
        outside = []
        for value in CORPUS:
            shape = class_shape(value)
            if shape is None:
                continue
            if shape not in counted:
                outside.append((value, shape))
                continue
            counted[shape] += 1

        assert not outside, f"shapes the expression produces and this set omits: {outside}"
        thin = {
            shape: count
            for shape, count in sorted(counted.items())
            if count < self.MINIMUM_PER_SHAPE
        }

        assert not thin, f"class shapes with too few fixtures: {thin}"

    def test_the_shapes_are_read_off_the_expression_that_produces_them(self):
        """The half that makes the count above worth anything.

        `EVERY_CLASS_SHAPE` is built from the two widths `filing._LCC` is built
        from, so widening a cap grows the set the test demands. The first
        assertion sends one value of each shape back through the expression and
        asks for the set out again, so it is the regex that has to agree rather
        than the constants agreeing with themselves: it replaced a comparison of
        the set's length against the product of the two widths, which is true of
        every pair of widths and could not fail.

        **Both assertions catch a rewrite of `_LCC` that reorders its groups**,
        which this docstring used to name as a residual nothing reached. Each
        measured with the other stubbed, against the group swap: both red. So
        the residual was already closed by the second assertion before the round
        trip existed, and the sentence claiming otherwise was wrong twice, once
        for saying nothing reached it and once for crediting the round trip with
        reaching it first. What the round trip adds over the length comparison
        is a shape the regex can no longer produce, which the length could not
        see.
        """
        assert {
            class_shape("A" * letters + "1" * digits)
            for letters, digits in EVERY_CLASS_SHAPE
        } == EVERY_CLASS_SHAPE
        assert class_shape("KJC1234.5 .A2 1976") == (
            filing._LETTERS_WIDTH,
            filing._INTEGER_WIDTH,
        )

    def test_a_value_no_call_number_shape_covers_is_not_counted_as_one(self):
        """`class_shape` answers None for the generic rule's territory, so a
        corpus of nothing but prose could not pass the count above."""
        assert class_shape("Hello world") is None
        assert class_shape("155.9042") is None


class TestTheKeyReadsPastANewline:
    """`_LCC` is compiled `re.DOTALL`, and this is what goes red without it.

    Nothing pinned the flag directly while the rule was also written in SQL: it
    was caught by the two implementations disagreeing, and that harness is gone.
    A newline is the only character that pins it, because bare `.` already
    matches a tab and a carriage return.

    `ClassificationIn.tidy_number` refuses a newline at every door.
    `backup.restore` writes this table through Core and is the path that can
    still put one in the column, which is why the rule does not lean on the
    validator.
    """

    def test_a_number_carrying_a_newline_still_files_under_its_class(self):
        """Without `DOTALL` this falls to the generic rule and files as raw
        text, which stands it apart from every other number in class QA76."""
        assert filing.LIBRARY_OF_CONGRESS.sort_key("QA76\nS75") == (
            "QA " + "0076" + "000000" + "\nS75"
        )

    def test_the_tab_and_the_carriage_return_are_not_evidence_of_the_flag(self):
        """Named so nobody reads them as guarding something they do not: both
        pass with the flag removed."""
        assert filing.LIBRARY_OF_CONGRESS.sort_key(
            "QA76\tS75"
        ) == "QA " + "0076" + "000000" + "\tS75"


class TestTheKeyIsAsciiOnly:
    """`_LCC` uses `[A-Za-z]` and `[0-9]` rather than `\\w` and `\\d`.

    The shorthands are wider than the schedules: `\\d` matches `٣`, so `٣٤`
    would be read as a class number and padded into a shelf position the
    Library of Congress has never published. These values file as their own
    text instead, which is the generic rule's answer and the honest one.
    """

    @pytest.mark.parametrize("number", ["٣٤", "ü9", "ẞ1"])
    def test_a_value_outside_ascii_files_as_its_own_text(self, number):
        assert filing.LIBRARY_OF_CONGRESS.sort_key(number) == filing.GENERIC.sort_key(
            number
        )


class TestTheKeyGrowsByABoundedAmount:
    """`MAX_KEY_GROWTH` is what `CLASSIFICATION_SORT_KEY_MAX` is built on, so a
    wrong bound is a column too narrow for its own values.

    Derived here by measuring every shape rather than by repeating the
    subtraction the constant states, which is the second instrument.
    """

    @staticmethod
    def _every_shape() -> list[str]:
        return [
            "A" * letters + "1" * digits + ("." + "1" * decimals if decimals else "")
            for letters in range(1, filing._LETTERS_WIDTH + 1)
            for digits in range(1, filing._INTEGER_WIDTH + 1)
            for decimals in range(filing._DECIMAL_WIDTH + 1)
        ]

    def test_the_bound_is_the_worst_shape_measured(self):
        worst = max(
            len(filing.LIBRARY_OF_CONGRESS.sort_key(value)) - len(value)
            for value in self._every_shape()
        )

        assert worst == filing.MAX_KEY_GROWTH

    def test_the_shortest_call_number_is_the_one_that_reaches_it(self):
        """`Q1` is two characters and files as thirteen, which is the sentence
        `MAX_KEY_GROWTH` states."""
        assert len(filing.LIBRARY_OF_CONGRESS.sort_key("Q1")) - len("Q1") == (
            filing.MAX_KEY_GROWTH
        )

    @pytest.mark.parametrize("number", CORPUS)
    def test_no_corpus_value_grows_by_more(self, number):
        """Over every rule, not the Library of Congress one alone: the bound is
        on the column, and the column holds all four schemes' keys."""
        for scheme in ClassificationScheme:
            key = filing.rule_for(scheme).sort_key(number)
            assert len(key) - len(number) <= filing.MAX_KEY_GROWTH


class TestTheKeyForARowsTwoColumns:
    """`sort_key_for` is the one entry point every writer of the column uses.

    Its argument is `object` rather than `ClassificationScheme` because
    `backup.restore` inserts through Core, so what arrives is whatever an
    archive holds.
    """

    def test_it_applies_the_scheme_s_own_rule(self):
        assert filing.sort_key_for(
            ClassificationScheme.LCC, "BF75"
        ) == filing.LIBRARY_OF_CONGRESS.sort_key("BF75")
        assert filing.sort_key_for(
            ClassificationScheme.DDC, "005.13/3"
        ) == filing.DEWEY.sort_key("005.13/3")

    def test_the_scheme_may_arrive_as_the_string_the_column_holds(self):
        """Which is what a `VARCHAR(20)` returns and what an archive carries."""
        assert filing.sort_key_for("lcc", "BF75") == (
            filing.LIBRARY_OF_CONGRESS.sort_key("BF75")
        )

    @pytest.mark.parametrize("scheme", ["udc", "", None, 7, ["ddc"]])
    def test_a_scheme_this_app_cannot_name_files_under_the_generic_rule(
        self, scheme
    ):
        """Rather than raising. One unrecognised row would otherwise fail the
        restore of a whole library, and the generic rule is the answer
        `FILING_RULES` already gives a scheme with no entry.
        """
        assert filing.sort_key_for(scheme, "BF75") == filing.GENERIC.sort_key("BF75")
