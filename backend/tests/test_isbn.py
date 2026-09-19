# ruff: noqa: RUF002
#
# This file's docstrings quote the digit spellings the reader has to tell
# apart: the fullwidth and Arabic-Indic forms among them. A confusable in a
# docstring here is the subject, not a typo. File level rather than per line
# because a bare `noqa` comment inside a triple quoted string is text rather
# than a directive, and would land in the docstring it was meant to annotate.
"""Tests for backend/isbn.py.

Each class below pins one of the four defects the previous implementation had.
The old rule was a bare regex, `^(97[89]\\d{10}|\\d{10})$`, with no checksum,
no normalisation and no ISBN-10/13 equivalence.
"""

from typing import Final

import pytest
from hypothesis import given
from hypothesis import strategies as st

from isbn import (
    BOOKLAND_PREFIXES,
    equivalent_forms,
    group_prefix,
    is_valid,
    is_valid_isbn10,
    is_valid_isbn13,
    isbn10_to_isbn13,
    isbn13_to_isbn10,
    normalise,
    parse,
    registration_group,
)
from tests.strategies import witness

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

    @pytest.mark.parametrize(
        "raw",
        [
            "978\u0660\u0660\u0660\u0660\u0660\u0660\u0660\u0660\u06602",
            "978\u00b2\u00b2\u00b2\u00b2\u00b2\u00b2\u00b2\u00b2\u00b2\u00b2",
            "185723999\uff17",
        ],
    )
    def test_strips_digits_that_are_not_ascii(self, raw):
        """`isalnum()` is Unicode and `[^0-9A-Za-z]` is not, so this used to diverge.

        Measured 2026-08-31: `frontend/src/lib/isbn.ts` stripped all three of
        these and this function kept them, which let a non-ASCII digit through
        `parse` and into storage. The shared cases in `conformance/cases/isbn.json`
        pin the same three on both sides; this pins them where somebody editing
        `normalise` will look.
        """
        assert normalise(raw).isascii()


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


class TestRegistrationGroup:
    """Which group an ISBN belongs to, and the one shape of that question that
    is easy to get silently wrong.

    **A group is variable length and a wrong length is silent.** Every case here
    is a real assignment rather than a constructed one, because the failure this
    guards is not a crash: it is a group name that looks plausible, matches
    nothing in `sources.SERVES_GROUPS`, and takes a catalogue out of the chain
    for a book it holds.
    """

    def test_a_single_digit_group_is_one_digit(self):
        # 978-3 is German language publishing, the group the two German
        # catalogues in this roster exist for.
        assert registration_group("9783442267743") == "978-3"

    def test_a_two_digit_group_is_two(self):
        assert registration_group("9788020023278") == "978-80"

    def test_a_three_digit_group_is_three(self):
        assert registration_group("9789601234564") == "978-960"

    def test_a_four_digit_group_is_four(self):
        assert registration_group("9789974123458") == "978-9974"

    def test_six_is_not_a_single_digit_group(self):
        """**The trap this whole function exists for.** Greek publishing's
        second group is 978-618 and Brazil's is 978-65, both starting with a
        digit that is not itself a group. A survey script written while
        measuring #122 read `6` as a single digit group, filed 23 of the 500
        sampled ISBNs under a group that does not exist, and produced a table
        that looked entirely reasonable."""
        assert registration_group("9786180123456") == "978-618"
        assert registration_group("9786512345679") == "978-65"

    def test_the_979_prefix_has_its_own_groups(self):
        """979 is not 978 with a different first digit: `979-8` is one digit and
        `979-12` is two, and neither number means anything under 978."""
        assert registration_group("9798886663303") == "979-8"
        assert registration_group("9791234567896") == "979-12"

    def test_an_isbn10_answers_for_its_isbn13_form(self):
        """`parse` canonicalises first, so the same book scanned either way
        reaches one group rather than none."""
        assert registration_group("0441013597") == registration_group("9780441013593")
        assert registration_group("0441013597") == "978-0"

    def test_a_five_digit_group_is_five(self):
        """**The longest row in the range table, and nothing covered it.**
        Deleting `(5, "99901", "99993")` left every other test in this file and
        both new classes in `test_sources.py` green, because no ISBN under
        `backend/tests/` fell in a five digit group. Every other row was pinned
        by something."""
        assert registration_group("9789990100006") == "978-99901"

    def test_a_group_prefix_is_the_bookland_half(self):
        """`sources._serves` reads this to tell a remit that is **silent** about a
        prefix from one that excludes a group inside it."""
        assert group_prefix("978-960") == "978"
        assert group_prefix("979-12") == "979"

    def test_a_group_prefix_refuses_anything_it_cannot_take_apart(self):
        """None means no claim here too, and `_serves` reads it as "ask"."""
        for candidate in ("978", "978-", "-3", "", "980-1", "nonsense"):
            assert group_prefix(candidate) is None, candidate

    def test_anything_that_is_not_an_isbn_has_no_group(self):
        assert registration_group("nonsense") is None
        assert registration_group("") is None
        assert registration_group(None) is None
        # A valid EAN-13 that is not Bookland: `parse` rejects it first.
        assert registration_group("5012345678900") is None

    def test_an_unassigned_range_says_so_rather_than_guessing(self):
        """**None means no claim, and the caller has to ask everyone.** 978-99999
        is outside every range in the table, and answering `978-9` or `978-99`
        would invent a group that is in nobody's remit and quietly drop a
        catalogue from the chain."""
        assert registration_group("9789999912341") is None

    def test_no_assigned_group_is_the_start_of_a_longer_one(self):
        """The table's ranges are prefix free, which is what makes first match
        the only match and the order of the table presentation rather than
        precedence. Checked against the ranges themselves rather than asserted
        in the docstring, because a range added later could break it."""
        from isbn import _GROUP_RANGES

        for ranges in _GROUP_RANGES.values():
            for short_len, short_low, short_high in ranges:
                for long_len, long_low, long_high in ranges:
                    if long_len <= short_len:
                        continue
                    # Every element of the longer range, truncated to the
                    # shorter length, must fall outside the shorter range.
                    for value in range(int(long_low), int(long_high) + 1):
                        head = str(value).zfill(long_len)[:short_len]
                        assert not short_low <= head <= short_high, (
                            f"{head} is both a {short_len} digit group "
                            f"and the start of {value}"
                        )


class TestADigitIsNotAlwaysADigit:
    """`str.isdigit()` is true of far more than `0` to `9`, and both halves bit.

    Two defects, executed against the running app before being written down, and
    they fail in opposite directions:

    * **`int()` raises.** A superscript two, `U+00B2`, is `isdigit()` and
      `int("²")` is a `ValueError`. Thirteen of them behind `978` passed the
      length check and left `GET /api/books/lookup` as an unhandled exception.
    * **`int()` accepts.** An Arabic-Indic zero, `U+0660`, is `isdigit()` and
      `int()` reads it as 0, so a checksum computed over it can pass. That one
      is worse: nothing crashed, `POST /api/books` returned 201, and the stored
      string was not the ISBN anybody typed, so `uq_books_isbn_single_copy`
      could no longer see a second copy as the same book.

    The class returning is stopped by
    `test_house_rules.py::TestAnAlphanumericPredicateIsAlwaysNarrowedToAscii`,
    which requires an `isascii()` beside every alphanumeric predicate in every
    backend module.
    These pin the behaviour that rule protects.
    """

    SUPERSCRIPT_TWO = "²"
    ARABIC_INDIC_ZERO = "٠"
    ARABIC_INDIC_SEVEN = "٧"

    def test_the_two_characters_are_what_this_class_says_they_are(self):
        """The fixtures' own precondition. Without it a Python that stopped
        calling these digits would make every test below pass for nothing."""
        assert self.SUPERSCRIPT_TWO.isdigit()
        assert self.ARABIC_INDIC_ZERO.isdigit()
        assert self.ARABIC_INDIC_SEVEN.isdigit()
        with pytest.raises(ValueError):
            int(self.SUPERSCRIPT_TWO)
        assert int(self.ARABIC_INDIC_ZERO) == 0
        assert int(self.ARABIC_INDIC_SEVEN) == 7
        # **The two are not one shape and the diagonal below turns on it.** Only
        # the Arabic-Indic pair is `isdecimal()`, which is what makes `int()`
        # accept it, and that is the half a checksum can be computed over.
        assert self.ARABIC_INDIC_ZERO.isdecimal()
        assert not self.SUPERSCRIPT_TWO.isdecimal()

    def test_a_digit_int_refuses_is_refused_rather_than_raising(self):
        assert parse("978" + self.SUPERSCRIPT_TWO * 10) is None
        assert is_valid_isbn13("978" + self.SUPERSCRIPT_TWO * 10) is False

    def test_an_isbn10_body_of_unicode_digits_is_refused(self):
        """**The body arm, with a fixture only the body arm refuses.**

        This test and its sibling below are a diagonal, and they are one because
        the first version was not. It carried three assertions, all spelling the
        non ASCII digit as a superscript two, and named itself for a defect that
        was "once on the body and once on the check character". A superscript is
        refused by the **check** arm on every one of those three, so removing
        `body.isascii()` left the test green: the arm it was named for was
        pinned by nothing, and only the house rule caught the hole.

        Nine Arabic-Indic zeros and an ASCII check digit separates them.
        `int()` accepts each of those as 0, so the modulus-11 sum is 0 and the
        checksum passes: with the body arm dropped this is `True` and `parse`
        answers `978` followed by nine non ASCII digits and a `2`.

        **This is the arm the forgery argument belongs to**, and it was
        attributed to the check arm below until a critic measured that one dead.
        A body is what survives into storage: `isbn10_to_isbn13` keeps
        `isbn10[:9]` verbatim, so a non ASCII body becomes a non ASCII ISBN-13,
        a distinct string that `uq_books_isbn_single_copy` cannot match against
        the ASCII spelling of the same number. The check digit is discarded and
        recomputed, so it cannot do that.
        """
        forged = self.ARABIC_INDIC_ZERO * 9 + "0"
        assert len(forged) == 10
        assert forged.isdigit() and not forged.isascii()
        assert is_valid_isbn10(forged) is False
        assert parse(forged) is None

    def test_an_isbn10_check_digit_of_unicode_digits_is_refused(self):
        """**The check arm, with a fixture only the check arm refuses.**

        An ASCII body and an Arabic-Indic seven, which is Dune's real check
        digit spelled in another script.

        **What this arm buys is strictness, and not the forgery the arm above
        prevents.** That claim sat here and was wrong in the one direction that
        matters: it said the input "becomes a different and entirely real book".
        It becomes the **same** book, and it cannot become anything else.
        `isbn10_to_isbn13` reads `isbn10[:9]` and recomputes the check digit, so
        the check character never reaches storage, and modulus-11 admits exactly
        one check value per body.

        Measured with the arm dropped, sweeping **all of `range(0x110000)`** on
        Python 3.14.0 with unicodedata 16.0.0: **76** characters satisfy
        `isdigit()` and that sum for this body, 37 in the BMP and 39 above it,
        every one of them category `Nd` with numeric value 7. They are every
        script's digit seven, ASCII `7` and the fullwidth `７` among them, and
        **all 76 map to the single ISBN-13 `9780441013593`**, which is what the
        ASCII spelling gives. Re-derived a second way with no module of this
        project in the loop, computing the modulus-11 sum directly: the same 76.

        **That number read 40 until somebody re-derived it**, because the sweep
        behind it was written `range(0x11000)` and stopped a sixteenth of the way
        through, inside plane 1. 40 is not a plane boundary or any other natural
        stopping point, which is the tell that was there to be noticed and was
        not. The denominator is stated above so the next reader can tell a
        recount from a re-run.

        So `uq_books_isbn_single_copy` is untouched by this arm. What it does
        buy is that `is_valid_isbn10` stops answering True for a string that is
        not an ISBN-10, which is `parse`'s contract about its **input** rather
        than about what it stores. Worth keeping and worth not overselling.
        """
        forged = "044101359" + self.ARABIC_INDIC_SEVEN
        assert forged.isdigit() and not forged.isascii()
        assert is_valid_isbn10(forged) is False
        assert parse(forged) is None
        # **The same book, which is the point rather than an aside.** With the
        # arm dropped the forgery parses to exactly this, so what is refused is
        # a spelling and never a second identity.
        assert parse("0441013597") == "9780441013593"

    def test_a_superscript_pins_the_check_arm_and_says_so(self):
        """Kept, with its reach stated. A superscript is not `isdecimal()`, so
        `int()` refuses it and the **check** arm is what turns it away in an
        ISBN-10. It says nothing about the body arm, which is what the two tests
        above exist for."""
        assert parse(self.SUPERSCRIPT_TWO * 10) is None
        assert is_valid_isbn10(self.SUPERSCRIPT_TWO * 10) is False
        assert is_valid_isbn10("044101359" + self.SUPERSCRIPT_TWO) is False

    def test_a_digit_int_accepts_is_still_refused(self):
        """The quiet half. This checksum passes, and the string is not an ISBN."""
        forged = "978316148410" + self.ARABIC_INDIC_ZERO
        assert len(forged) == 13
        assert forged.isdigit()
        assert parse(forged) is None
        assert is_valid("9783161484100") is True

    def test_a_registration_group_is_not_decoded_from_one_either(self):
        """The range test is a string comparison, so a non ASCII digit would be
        ordered against `"0"` to `"9"` by code point. `parse` is what stops it
        reaching that comparison at all."""
        assert registration_group("978" + self.ARABIC_INDIC_ZERO * 10) is None


# ── The same rules as properties ──────────────────────────────────────────────
#
# **What the classes above pin is four defects and their fixes, case by case.**
# What is below is the rule each case is an instance of, over inputs nobody
# chose. The two are not redundant and neither replaces the other: a named case
# carries the incident it came from, and a property carries the bound the case
# has no way to state.
#
# The generators are built from the checksum arithmetic and from the predicate
# `normalise` applies, never from a list of the spellings anybody has met. The
# hand written list is what this module already paid for once: a survey script
# that read `6` as a single digit registration group filed 23 ISBNs under a
# group that does not exist and nothing failed.

_DIGITS: Final = "0123456789"

#: Every character an ISBN-10 check position may hold.
_CHECK_CHARACTERS: Final = _DIGITS + "X"


@st.composite
def isbn10s(draw) -> str:
    """A valid ISBN-10, from nine digits and the character modulus 11 wants.

    **The check character is computed here rather than asked of the module.** A
    generator that used `isbn10_to_isbn13` to decide what a valid ISBN-10 looks
    like would agree with that function whatever it did, and every round trip
    over it would pass by construction.
    """
    body = draw(st.text(alphabet=_DIGITS, min_size=9, max_size=9))
    remainder = (
        11 - sum(int(digit) * (10 - at) for at, digit in enumerate(body)) % 11
    ) % 11
    return body + ("X" if remainder == 10 else str(remainder))


@st.composite
def ean13s(draw) -> str:
    """A valid EAN-13 with any prefix at all: a food packet as easily as a book."""
    body = draw(st.text(alphabet=_DIGITS, min_size=12, max_size=12))
    total = sum(int(digit) * (1 if at % 2 == 0 else 3) for at, digit in enumerate(body))
    return body + str((10 - total % 10) % 10)


@st.composite
def isbn13s(draw) -> str:
    """A valid EAN-13 that is also a book, which is the Bookland half of them."""
    body = draw(st.sampled_from(BOOKLAND_PREFIXES)) + draw(
        st.text(alphabet=_DIGITS, min_size=9, max_size=9)
    )
    total = sum(int(digit) * (1 if at % 2 == 0 else 3) for at, digit in enumerate(body))
    return body + str((10 - total % 10) % 10)


def discarded_characters() -> st.SearchStrategy[str]:
    """Any character `normalise` throws away, derived from the rule it applies.

    **The complement of `isascii() and isalnum()`, taken as a predicate rather
    than as a list.** The list a reader would write is the hyphen and the space,
    which is the formatting publishers use and about sixty of the million and a
    half characters this covers. The two that mattered were neither: an
    Arabic-Indic digit and a superscript two, each of which reached storage or a
    500 through this exact door.
    """
    return st.characters().filter(
        lambda character: not (character.isascii() and character.isalnum())
    )


@st.composite
def formatted(draw) -> str:
    """A real ISBN with the formatting a person or a catalogue puts through it."""
    characters = list(draw(st.one_of(isbn10s(), isbn13s())))
    for noise in draw(st.lists(discarded_characters(), max_size=6)):
        characters.insert(draw(st.integers(min_value=0, max_value=len(characters))), noise)
    return "".join(characters)


@st.composite
def near_misses(draw) -> str:
    """A real ISBN with one character changed, which is the misread a checksum
    exists to catch. Sometimes it changes nothing, which is the case a generator
    written to always break something would never produce."""
    isbn = draw(st.one_of(isbn10s(), isbn13s()))
    at = draw(st.integers(min_value=0, max_value=len(isbn) - 1))
    return isbn[:at] + draw(st.sampled_from(_CHECK_CHARACTERS)) + isbn[at + 1 :]


#: Everything that reaches `parse`: a scan, a paste, a catalogue field, a
#: barcode off something that is not a book, and text that is not any of those.
#:
#: **Free text on its own would be a generator that never reaches the accepting
#: branch.** The chance of `st.text()` producing a string with a valid checksum
#: is not worth stating, so a property given only that is a thorough test of the
#: `return None` and silence about everything else. The witnesses below assert
#: both branches are still reachable from this, which is the only thing standing
#: between these properties and that.
ANYTHING_SCANNED = st.one_of(
    st.text(max_size=40),
    isbn10s(),
    isbn13s(),
    ean13s(),
    formatted(),
    near_misses(),
)


@pytest.mark.property
class TestTheGeneratorsReachBothBranches:
    """The control on every property below, and the reason they are not empty.

    A property over a generator that cannot produce the interesting class passes
    and tests nothing. These fail loudly when that happens, which is the one
    thing the properties themselves cannot report about themselves.
    """

    def test_something_generated_here_is_a_real_isbn(self):
        witness(ANYTHING_SCANNED, lambda raw: parse(raw) is not None, reaches="an ISBN")

    def test_something_generated_here_is_not(self):
        witness(ANYTHING_SCANNED, lambda raw: parse(raw) is None, reaches="a non ISBN")

    def test_the_discarded_characters_are_not_only_the_formatting_ones(self):
        """Hyphens and spaces are the easy half and were never the defect."""
        witness(
            discarded_characters(),
            lambda character: not character.isascii(),
            reaches="a character outside ASCII",
        )

    def test_a_scanned_value_reaches_a_barcode_that_is_not_a_book(self):
        witness(
            ANYTHING_SCANNED,
            lambda raw: is_valid_isbn13(normalise(raw))
            and not normalise(raw).startswith(BOOKLAND_PREFIXES),
            reaches="a valid EAN-13 that is not Bookland",
        )


@pytest.mark.property
class TestParseAnswersForAnything:
    @given(raw=ANYTHING_SCANNED)
    def test_the_answer_is_none_or_a_canonical_isbn13(self, raw):
        """`parse`'s contract about its output, which four callers rely on and
        `targets.Target.isbn_query` states in its own reasoning: what comes back
        is thirteen ASCII digits or nothing."""
        canonical = parse(raw)
        if canonical is None:
            return
        assert len(canonical) == 13
        assert canonical.isascii() and canonical.isdigit()
        assert canonical.startswith(BOOKLAND_PREFIXES)
        assert is_valid_isbn13(canonical)

    @given(raw=ANYTHING_SCANNED)
    def test_parsing_a_parsed_value_changes_nothing(self, raw):
        canonical = parse(raw)
        assert parse(canonical) == canonical

    @given(raw=ANYTHING_SCANNED)
    def test_is_valid_is_the_same_question(self, raw):
        assert is_valid(raw) is (parse(raw) is not None)


@pytest.mark.property
class TestNormaliseKeepsOnlyWhatItSaysItKeeps:
    @given(raw=st.text(max_size=60))
    def test_every_character_kept_is_ascii_alphanumeric(self, raw):
        assert all(
            character.isascii() and character.isalnum() for character in normalise(raw)
        )

    @given(raw=st.text(max_size=60))
    def test_normalising_a_normalised_value_changes_nothing(self, raw):
        assert normalise(normalise(raw)) == normalise(raw)

    @given(
        raw=st.text(max_size=40),
        noise=discarded_characters(),
        at=st.integers(min_value=0, max_value=60),
    )
    def test_inserting_a_discarded_character_anywhere_changes_nothing(
        self, raw, noise, at
    ):
        """**The property the browser has to agree with**, and the one the
        `isascii()` guard exists for. `conformance/cases/isbn.json` pins three
        instances of it in both languages; this is the rule they are instances
        of."""
        position = at % (len(raw) + 1)
        assert normalise(raw[:position] + noise + raw[position:]) == normalise(raw)


@pytest.mark.property
class TestACheckDigitIsUniqueWhichIsWhatMakesItOne:
    """Modulus 11 and modulus 10 each admit exactly one completion of a body.

    This is the arithmetic the two validators implement, asked as a question
    about them rather than restated as a second implementation: if two check
    characters passed, a single misread digit could land on a second valid ISBN
    and the whole scheme buys nothing.
    """

    @given(body=st.text(alphabet=_DIGITS, min_size=9, max_size=9))
    def test_one_character_completes_an_isbn10(self, body):
        accepted = [
            character
            for character in _CHECK_CHARACTERS
            if is_valid_isbn10(body + character)
        ]
        assert len(accepted) == 1

    @given(body=st.text(alphabet=_DIGITS, min_size=12, max_size=12))
    def test_one_digit_completes_an_isbn13(self, body):
        accepted = [digit for digit in _DIGITS if is_valid_isbn13(body + digit)]
        assert len(accepted) == 1


@pytest.mark.property
class TestTheTwoFormsAreOneBook:
    @given(isbn10=isbn10s())
    def test_an_isbn10_survives_the_trip_through_isbn13(self, isbn10):
        """Which is the fix for the fourth defect: one book, one stored value."""
        assert isbn13_to_isbn10(isbn10_to_isbn13(isbn10)) == isbn10

    @given(isbn13=isbn13s())
    def test_a_978_isbn13_survives_the_trip_through_isbn10(self, isbn13):
        as_isbn10 = isbn13_to_isbn10(isbn13)
        if not isbn13.startswith("978"):
            assert as_isbn10 is None
            return
        assert as_isbn10 is not None
        assert isbn10_to_isbn13(as_isbn10) == isbn13

    @given(raw=ANYTHING_SCANNED)
    def test_every_equivalent_form_is_the_same_book(self, raw):
        """A duplicate check reads every form, so a form that parses to some
        other ISBN would find the wrong row."""
        canonical = parse(raw)
        forms = equivalent_forms(raw)
        if canonical is None:
            assert forms == []
            return
        assert canonical in forms
        assert all(parse(form) == canonical for form in forms)


@pytest.mark.property
class TestOnlyABookParses:
    @given(ean=ean13s())
    def test_a_valid_barcode_parses_exactly_when_it_is_bookland(self, ean):
        """A loyalty card and a food packet carry valid EAN-13s, and neither is
        a book to look up."""
        assert (parse(ean) is not None) is ean.startswith(BOOKLAND_PREFIXES)


@pytest.mark.property
class TestARegistrationGroupNamesItsOwnPrefix:
    @given(raw=ANYTHING_SCANNED)
    def test_the_group_and_the_prefix_agree(self, raw):
        """`sources._serves` reads both, and a group whose prefix disagreed with
        the ISBN it came from would skip a catalogue for a book it holds."""
        group = registration_group(raw)
        if group is None:
            return
        canonical = parse(raw)
        assert canonical is not None
        assert group_prefix(group) == canonical[:3]
        assert group.startswith(canonical[:3] + "-")
