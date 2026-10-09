"""What `BookIdentifierIn` takes, and the three things it refuses.

The ceiling and the deduplication are exercised through the route, in
`tests/routers/test_books_identifiers.py`, which is where a member meets them.
What is pinned here is the model's own rule: an identifier is an opaque token,
so the edges are trimmed and nothing invisible survives inside.
"""

import pytest
from pydantic import ValidationError

from enums import BookIdentifierScheme
from models import BOOK_IDENTIFIER_MAX
from schemas.identifier import BookIdentifierIn


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
