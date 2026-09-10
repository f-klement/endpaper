"""What a browser may say about where a book file is.

The first of the two layers. Everything here bounds a payload; `test_models.py`
bounds what reaches the column, which is the layer `backup.restore` reaches and
this one does not. **Neither implies the other**, which is why both exist.
"""

import pytest
from pydantic import ValidationError

import catalogue
from models import (
    DIGITAL_REFERENCE_MAX_SIZE,
    DIGITAL_REFERENCE_PATH_MAX,
    DigitalReference,
)
from schemas.digital import DigitalReferenceIn, DigitalReferenceOut


def reference(**fields):
    return DigitalReferenceIn(
        **({"root_label": "/books", "relative_path": "a/b.epub"} | fields)
    )


class TestThePairIsBoundedAndNotOnlyEachHalf:
    """The bound that is actually derived, and the one a reviewer reading
    `max_length` would think was already covered."""

    def test_either_half_may_take_all_but_one_character_of_the_budget(self):
        """So the per field bound is the pair's and not half of it.

        All but one, because the other half is at least one character: the
        budget is the pair's and nothing may spend more of it than that.
        """
        widest = DIGITAL_REFERENCE_PATH_MAX - 1
        assert reference(root_label="r" * widest, relative_path="a")
        assert reference(root_label="r", relative_path="p" * widest)

    def test_the_field_bound_never_refuses_what_the_pair_rule_admits(self):
        """The property the shared constant buys: the column and the field are
        as wide as the whole budget, so the inequality on the pair is the only
        thing that ever refuses a path."""
        field = DigitalReferenceIn.model_fields["relative_path"]
        widest = max(
            data.max_length for data in field.metadata if hasattr(data, "max_length")
        )
        assert widest >= DIGITAL_REFERENCE_PATH_MAX - 1

    def test_two_halves_that_together_exceed_it_are_refused(self):
        half = DIGITAL_REFERENCE_PATH_MAX // 2 + 1
        with pytest.raises(ValidationError):
            reference(root_label="r" * half, relative_path="p" * half)

    def test_two_halves_that_together_fit_are_accepted(self):
        """The other side of the same inequality: without this the test above
        would pass on a rule that refused everything."""
        half = DIGITAL_REFERENCE_PATH_MAX // 2
        assert reference(root_label="r" * half, relative_path="p" * half)


class TestTheSchemaCeilingIsTheColumnCeiling:
    """Recomputed from the table, so the two cannot drift.

    The same rule `catalogue._TEXT_CEILINGS` follows and for the same reason: a
    ceiling derived from a literal the schema could not see would be a fact
    stored twice.
    """

    @pytest.mark.parametrize("name", ["root_label", "relative_path"])
    def test_the_field_is_bounded_at_the_column_width(self, name):
        column = DigitalReference.__table__.c[name].type.length
        field = DigitalReferenceIn.model_fields[name]
        assert [
            data.max_length for data in field.metadata if hasattr(data, "max_length")
        ] == [column]

    def test_the_field_ceilings_are_not_a_second_register(self):
        """`catalogue._TEXT_CEILINGS` bounds what a **catalogue** asserted about
        a book. A file reference is not a catalogue assertion and must not
        acquire an entry there by somebody tidying the two together."""
        assert "root_label" not in catalogue._TEXT_CEILINGS
        assert "relative_path" not in catalogue._TEXT_CEILINGS


class TestAPathIsRefusedOnlyForWhatCannotBeStored:
    def test_a_null_in_the_root_is_refused(self):
        with pytest.raises(ValidationError):
            reference(root_label="/bo\x00oks")

    def test_a_null_in_the_path_is_refused(self):
        with pytest.raises(ValidationError):
            reference(relative_path="a\x00.epub")

    def test_an_empty_root_is_refused(self):
        with pytest.raises(ValidationError):
            reference(root_label="")

    def test_an_empty_path_is_refused(self):
        with pytest.raises(ValidationError):
            reference(relative_path="")

    @pytest.mark.parametrize("odd", ["a\nb.epub", "a\tb.epub", "a\x1bb.epub"])
    def test_a_filename_carrying_a_control_character_is_kept(self, odd):
        """**Deliberate, and the narrowness is the decision.** A newline, a tab
        and an escape are all legal in a filename on the systems this app's
        Members use, so refusing them as a class would refuse a real file and
        tell its owner nothing they could act on. NUL is the one that cannot be
        a filename character anywhere."""
        assert reference(relative_path=odd).relative_path == odd

    @pytest.mark.parametrize("shape", ["/etc/passwd", "../../secrets", "C:\\books"])
    def test_a_path_shape_is_not_policed(self, shape):
        """This server never resolves any of it: the string is stored and echoed
        and never opened. The client that goes looking holds a file handle
        rather than this text, so that rule belongs there."""
        assert reference(relative_path=shape).relative_path == shape


class TestASizeIsBoundedAtWhatABrowserCouldHaveSent:
    def test_the_largest_safe_integer_is_accepted(self):
        assert reference(size_bytes=DIGITAL_REFERENCE_MAX_SIZE)

    def test_one_past_it_is_refused(self):
        with pytest.raises(ValidationError):
            reference(size_bytes=DIGITAL_REFERENCE_MAX_SIZE + 1)

    def test_a_negative_size_is_refused(self):
        with pytest.raises(ValidationError):
            reference(size_bytes=-1)

    def test_an_absent_size_is_the_ordinary_case(self):
        """A client that did not read the size says nothing, rather than zero."""
        assert reference().size_bytes is None


class TestWhatAClientMayNotSay:
    """The fields a client cannot set, asserted at the payload.

    **This is the guard on the honesty of the table**, not a completeness check.
    `confirmed_at` and `missing_since` are this server's own clock, and the
    moment either becomes settable the column's docstring stops being true: a
    browser would be able to state when it was told, which is a sentence only
    the server can make.
    """

    @pytest.mark.parametrize(
        "name", ["confirmed_at", "missing_since", "created_at", "id", "book_id"]
    )
    def test_a_client_cannot_set_it(self, name):
        assert name not in DigitalReferenceIn.model_fields

    def test_an_unknown_field_is_ignored_rather_than_stored(self):
        """Pydantic's default, pinned: a payload naming a server clock column
        must not reach the row through a model that took it silently."""
        assert not hasattr(reference(confirmed_at="2020-01-01T00:00:00"), "confirmed_at")

    def test_every_client_reported_field_comes_back_out(self):
        """A field a client may set and cannot read back would be a claim stored
        where nobody can check it."""
        assert set(DigitalReferenceIn.model_fields) <= set(
            DigitalReferenceOut.model_fields
        )
