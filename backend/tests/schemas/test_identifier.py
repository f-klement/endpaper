"""What `BookIdentifierIn` takes, and the three things it refuses.

The ceiling and the deduplication are exercised through the route, in
`tests/routers/test_books_identifiers.py`, which is where a member meets them.
What is pinned here is the model's own rule: an identifier is an opaque token,
so the edges are trimmed and nothing invisible survives inside.
"""

import unicodedata

import pytest
from hypothesis import given
from hypothesis import strategies as st
from pydantic import ValidationError

from enums import BookIdentifierScheme
from models import BOOK_IDENTIFIER_MAX
from schemas.identifier import BookIdentifierIn
from tests.strategies import INVISIBLE_CATEGORIES, invisible_characters, text_around, witness


class TestTheValueIsTrimmedAndThenTested:
    def test_a_padded_value_loses_its_padding(self):
        """A store's XML indents its elements, so a reader taking the text node
        whole hands over the indentation with it."""
        assert (
            BookIdentifierIn(scheme=BookIdentifierScheme.ASIN, value="\n  B00J4YQKHY\n ").value
            == "B00J4YQKHY"
        )

    def test_a_value_of_only_padding_is_refused(self):
        """It passes `min_length=1` on what arrived and is nothing at all."""
        with pytest.raises(ValidationError):
            BookIdentifierIn(scheme=BookIdentifierScheme.ASIN, value="   ")

    def test_the_ceiling_is_measured_before_the_trim_and_that_is_the_trade(self):
        """**Padding counts against the budget**, and it is worth pinning
        because the opposite would be the natural guess.

        `max_length` is a field constraint, so it runs before the validator and
        bounds **what arrived**. That is the half worth keeping: it is what
        stops an unbounded string reaching the scan below at all, and
        `ClassificationIn` beside it is arranged the same way.

        What it costs is a value whose padding carries it past the ceiling,
        refused rather than trimmed into range. The exclusion is small and
        measured: the widest identifier any reader here produces is a Google
        volume id at 12 characters, so a payload would have to carry 48
        characters of whitespace around one before this bites.
        """
        padded = "  " + "B" * BOOK_IDENTIFIER_MAX + "  "

        with pytest.raises(ValidationError):
            BookIdentifierIn(scheme=BookIdentifierScheme.ASIN, value=padded)

    def test_a_padded_value_inside_the_budget_still_fits(self):
        """The other side: the trim is for a reader's indentation, which is what
        a store's XML actually hands over, and that is well inside the budget."""
        padded = "\n    " + "B" * 10 + "\n  "
        assert (
            len(BookIdentifierIn(scheme=BookIdentifierScheme.ASIN, value=padded).value)
            == 10
        )

    def test_a_value_past_the_ceiling_with_nothing_to_trim_is_refused(self):
        with pytest.raises(ValidationError):
            BookIdentifierIn(
                scheme=BookIdentifierScheme.ASIN, value="B" * (BOOK_IDENTIFIER_MAX + 1)
            )


class TestNothingInvisibleSurvivesInsideOne:
    """The unique index is on the exact characters, so a spelling that differs
    by something nobody can see earns a second row for one identifier.

    Refused rather than stripped, which is where this parts company with
    `ClassificationIn.tidy_number`: a call number legitimately holds spaces and
    a token never does, so collapsing here would store a value this app made up.
    """

    @pytest.mark.parametrize(
        "value",
        [
            pytest.param("B00J4 YQKHY", id="a space in the middle"),
            pytest.param("B00J4\tYQKHY", id="a tab"),
            pytest.param("B00J4\u00a0YQKHY", id="a no-break space, Zs"),
            pytest.param("B00J4\u200bYQKHY", id="a zero width space, Cf"),
            pytest.param("B00J4\u00adYQKHY", id="a soft hyphen, Cf"),
            pytest.param("B00J4\ufeffYQKHY", id="a byte order mark, Cf"),
            pytest.param("B00J4\u0085YQKHY", id="a C1 control, Cc"),
            pytest.param("B00J4\x00YQKHY", id="a NUL, which is Cc"),
        ],
    )
    def test_it_is_refused(self, value):
        with pytest.raises(ValidationError):
            BookIdentifierIn(scheme=BookIdentifierScheme.ASIN, value=value)

    def test_the_two_real_shapes_are_taken(self):
        """The other side, without which the rule above is satisfied by one
        that refuses everything. Both measured by their own readers: an ASIN is
        ten characters and a Google volume id is twelve of the URL safe
        alphabet, `-` and `_` included."""
        assert BookIdentifierIn(scheme="asin", value="B00J4YQKHY").value == "B00J4YQKHY"
        assert (
            BookIdentifierIn(scheme="google_books", value="zy-CAlFP_gYC").value
            == "zy-CAlFP_gYC"
        )


class TestTheSchemeIsClosed:
    def test_a_scheme_no_reader_produces_is_refused(self):
        """`enums.BookIdentifierScheme`'s rule: a scheme nothing reads an
        identifier out of is a row that lies."""
        with pytest.raises(ValidationError):
            BookIdentifierIn(scheme="kobo", value="B00J4YQKHY")

    @pytest.mark.parametrize("scheme", list(BookIdentifierScheme))
    def test_every_member_is_accepted(self, scheme):
        assert BookIdentifierIn(scheme=scheme, value="B00J4YQKHY").scheme is scheme


# ── The same rule as a property ───────────────────────────────────────────────
#
# **What the cases above pin is the three refusals a reader needs to recognise.**
# What is below is the rule they are instances of, which is the one thing a case
# cannot state: that there is no fourth string that gets through.
#
# The generator names the invisible characters by Unicode category. The narrower
# rule this validator replaced reached the 24 ASCII controls and admitted the 41
# C1 controls, SOFT HYPHEN, ZERO WIDTH SPACE and the byte order mark, and a
# sweep written by hand is how that was found: one character at a time, after
# the second one had already reached a unique index.

_VALUES = st.one_of(
    st.text(max_size=BOOK_IDENTIFIER_MAX),
    text_around(invisible_characters(), padding=8),
    text_around(st.text(alphabet=" \t\n", min_size=1, max_size=3), padding=8),
).filter(lambda value: len(value) <= BOOK_IDENTIFIER_MAX)


def _stored(value: str) -> str | None:
    """The identifier this model would store, or None where it refuses."""
    try:
        return BookIdentifierIn(scheme=BookIdentifierScheme.ASIN, value=value).value
    except ValidationError:
        return None


def _opaque(value: str) -> bool:
    """Whether every character in this value is one an opaque token may hold."""
    return not any(
        character.isspace()
        or unicodedata.category(character) in INVISIBLE_CATEGORIES
        for character in value
    )


@pytest.mark.property
class TestTheGeneratorStillReachesEveryAnswer:
    def test_it_reaches_an_identifier_that_is_stored(self):
        witness(_VALUES, lambda value: _stored(value) is not None, reaches="a stored identifier")

    def test_it_reaches_one_that_is_refused(self):
        witness(_VALUES, lambda value: _stored(value) is None, reaches="a refused identifier")

    def test_it_reaches_one_whose_padding_is_trimmed(self):
        witness(
            _VALUES,
            lambda value: _stored(value) not in (None, value),
            reaches="an identifier with padding around it",
        )

    def test_it_reaches_an_invisible_character_that_is_not_a_control(self):
        witness(
            _VALUES,
            lambda value: any(
                unicodedata.category(character) == "Cf" for character in value
            ),
            reaches="a formatting character",
        )


@pytest.mark.property
class TestAnOpaqueTokenIsTrimmedAndThenTakenWhole:
    @given(value=_VALUES)
    def test_the_rule_is_the_whole_rule(self, value):
        """**Stated as one expression over every input**, which is what a case
        cannot do: the padding comes off, and what is left is stored unless it
        is empty or holds anything invisible or any whitespace at all.

        Whitespace **inside** is refused rather than collapsed, and that is
        where this parts company with `ClassificationIn.tidy_number`: a call
        number legitimately contains spaces, and an identifier does not, so
        whitespace inside one means the reader picked up something that is not
        the identifier.
        """
        trimmed = value.strip()
        expected = trimmed if trimmed and _opaque(trimmed) else None
        assert _stored(value) == expected

    @given(value=_VALUES)
    def test_storing_a_stored_identifier_changes_nothing(self, value):
        """The failure is `uq_book_identifiers_book_scheme_value`, which is on
        the exact characters: a value that normalised to something new on a
        second pass would be a second row for one identifier."""
        stored = _stored(value)
        assert stored is None or _stored(stored) == stored

    @given(value=_VALUES)
    def test_a_stored_identifier_has_no_edges_left_to_trim(self, value):
        stored = _stored(value)
        assert stored is None or (stored == stored.strip() and stored != "")
