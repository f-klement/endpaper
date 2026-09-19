"""What `ClassificationIn` stores, as a rule over every string rather than cases.

The cases live where a member meets them:
`tests/routers/test_books_classifications.py` drives the routes, and
`tests/test_classifications.py` pins how a null kind is read and which heading a
full book loses. What is here is the validator's own rule, asked of inputs
nobody chose.

**The rule is a Unicode category, and that is what makes a property the right
shape for it.** A narrower version of this validator was written as
`character < " "`, which is a comparison that reads like "the control
characters" and reaches 24 of the 96: the other 72 are the C1 block, SOFT
HYPHEN, ZERO WIDTH SPACE and the byte order mark, and every one of them is
invisible in a call number and earns a second row past
`uq_classifications_book_scheme_number`. A case per character is how that was
found the first time, one sweep at a time; a generator over the category is how
it stays found.
"""

import unicodedata

import pytest
from hypothesis import given
from hypothesis import strategies as st
from pydantic import ValidationError

from enums import ClassificationScheme, HeadingKind
from models import CLASSIFICATION_NUMBER_MAX
from schemas.classification import ClassificationIn
from tests.strategies import INVISIBLE_CATEGORIES, invisible_characters, text_around, witness

#: A scheme whose number is opaque text, so the only rules in play are the
#: collapse and the refusal. `ddc` additionally has to be a Dewey notation,
#: which is a different question with its own tests.
_OPAQUE = ClassificationScheme.LCC

#: Anything a client or a catalogue might send as a number, short enough that
#: the field's own ceiling is not what answers.
_NUMBERS = st.one_of(
    st.text(max_size=CLASSIFICATION_NUMBER_MAX),
    text_around(invisible_characters(), padding=10),
    text_around(st.text(alphabet=" \t\n", min_size=1, max_size=4), padding=10),
).filter(lambda number: len(number) <= CLASSIFICATION_NUMBER_MAX)


def _invisible(value: str) -> bool:
    return any(
        unicodedata.category(character) in INVISIBLE_CATEGORIES for character in value
    )


def _stored(number: str) -> str | None:
    """The number this model would store, or None where it refuses."""
    try:
        return ClassificationIn(scheme=_OPAQUE, number=number).number
    except ValidationError:
        return None


@pytest.mark.property
class TestTheGeneratorStillReachesEveryAnswer:
    """The control. Three branches, and a generator that had lost one would
    leave this whole file green and one of them untested."""

    def test_it_reaches_a_number_that_is_stored(self):
        witness(_NUMBERS, lambda number: _stored(number) is not None, reaches="a stored number")

    def test_it_reaches_a_number_that_is_refused(self):
        witness(_NUMBERS, lambda number: _stored(number) is None, reaches="a refused number")

    def test_it_reaches_a_number_whose_padding_is_collapsed(self):
        witness(
            _NUMBERS,
            lambda number: _stored(number) not in (None, number),
            reaches="a number the collapse rewrites",
        )

    def test_it_reaches_an_invisible_character_that_is_not_a_control(self):
        """SOFT HYPHEN and the byte order mark are the half the first version of
        this validator admitted, and they are `Cf` rather than `Cc`."""
        witness(
            _NUMBERS,
            lambda number: any(
                unicodedata.category(character) == "Cf" for character in number
            ),
            reaches="a formatting character",
        )


@pytest.mark.property
class TestWhatIsStoredIsWhatTheRuleSays:
    @given(number=_NUMBERS)
    def test_a_stored_number_holds_nothing_invisible(self, number):
        """The failure this closes is the unique index, not the display:
        `uq_classifications_book_scheme_number` is on the exact characters, so
        one soft hyphen inside `QA76.5` is a second row for one call number and
        nothing on any screen shows the two apart."""
        stored = _stored(number)
        assert stored is None or not _invisible(stored)

    @given(number=_NUMBERS)
    def test_a_stored_number_is_its_own_collapse(self, number):
        stored = _stored(number)
        assert stored is None or " ".join(stored.split()) == stored

    @given(number=_NUMBERS)
    def test_storing_a_stored_number_changes_nothing(self, number):
        """Normalise then compare has to be idempotent or the column holds two
        spellings of one heading, which is the whole reason the collapse is
        here rather than in `filing`."""
        stored = _stored(number)
        assert stored is None or _stored(stored) == stored

    @given(number=_NUMBERS)
    def test_the_refusal_and_the_rule_are_the_same_thing(self, number):
        """Stated as the complete rule rather than as the cases that prompted
        it: what survives the collapse is stored unless it is empty or carries
        a character from either invisible category."""
        collapsed = " ".join(number.split())
        expected = None if not collapsed or _invisible(collapsed) else collapsed
        assert _stored(number) == expected


@pytest.mark.property
class TestACaptionIsCollapsedAndAnEmptyOneIsAbsent:
    @given(label=st.text(max_size=80))
    def test_an_empty_caption_is_stored_as_the_absence_it_means(self, label):
        """Otherwise `null` and `""` are two spellings of "no caption" and every
        client tests for both."""
        heading = ClassificationIn(scheme=_OPAQUE, number="QA76", label=label)
        assert heading.label is None or (
            heading.label == " ".join(label.split()) and heading.label != ""
        )


@pytest.mark.property
class TestASubjectIsTheAbsenceOfAKind:
    @given(kind=st.sampled_from(list(HeadingKind)))
    def test_only_the_word_subject_is_read_as_nothing(self, kind):
        heading = ClassificationIn(scheme=_OPAQUE, number="QA76", kind=kind)
        assert heading.kind == (None if kind is HeadingKind.SUBJECT else kind)
