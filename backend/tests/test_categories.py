"""A Book's Categories: the codec, and the drop and cap policy's arms.

The request bodies' refusal is driven through the routes in
`tests/routers/test_books_categories.py` and against the browser in
`tests/conformance/test_subject.py`; the match door's split and re-bound through
`BookMatch` in `tests/schemas/test_book.py`.
"""

import ast
import sys
from pathlib import Path

import pytest
from hypothesis import given
from hypothesis import strategies as st

import categories
from categories import (
    CATEGORY_SEPARATOR,
    MAX_CATEGORIES_PER_BOOK,
    join_categories,
    kept_categories,
    refuse_separator,
    split_categories,
)


class TestTheJoinRefusesToStoreASubjectThatWouldReadBackAsTwo:
    """`join_categories` drops a subject carrying the separator.

    Two catalogue producers build their value without looking inside a single
    subject, `google_books._volume_to_fields` and `catalogue.Record.as_match`, and a
    subject holding a bare separator is not representable in this column:
    `split_categories` splits on that character, so storing one serves two subjects
    to every reader and manufactures an assertion nobody made.
    """

    def test_a_clean_list_is_joined_whole(self) -> None:
        """The baseline. A join that dropped everything would pass every arm
        below."""
        assert join_categories(["Fiction", "Science Fiction"]) == (
            f"Fiction{CATEGORY_SEPARATOR}Science Fiction"
        )

    def test_a_subject_carrying_the_separator_is_dropped(self) -> None:
        """The arm. Before this, `["Fiction; general"]` stored whole and read back
        as two subjects, measured."""
        assert join_categories(["Fiction; general", "Horror"]) == "Horror"

    def test_a_list_of_nothing_but_such_subjects_stores_a_null(self) -> None:
        """The column is nullable and an empty join answers None, so dropping the
        only subject leaves no row claiming an empty string."""
        assert join_categories(["A;B"]) is None

    def test_no_value_this_join_produces_reads_back_as_more_subjects(self) -> None:
        """The property the drop buys, over inputs that can break it.

        The list here carries two separator bearing subjects, so a join that kept
        them would answer four subjects for a list of four.
        """
        supplied = ["Fiction", "Fiction; general", "Horror", "A;B"]
        assert any(CATEGORY_SEPARATOR.strip() in subject for subject in supplied)

        stored = join_categories(supplied)

        assert split_categories(stored) == ["Fiction", "Horror"]


class TestTheJoinCapsTheCountForAProducer:
    """`join_categories` caps what a producer hands `BookMatch`.

    **The cap belongs to the producer because the model refuses**, and
    `routers/books._match_rows` builds that model inside a `try` that drops the
    **row**. So an uncapped producer costs a whole search result for a record that
    is merely well described. `catalogue.Record.match_headings` carries the same
    rule one field over, and the incident that bought it.
    """

    def test_the_cap_is_the_default(self) -> None:
        """The arm that removes the duty: a producer that passes nothing is
        capped, so the next caller of the join cannot forget the count."""
        assert join_categories(["a"] * 40) == CATEGORY_SEPARATOR.join(
            ["a"] * MAX_CATEGORIES_PER_BOOK
        )

    def test_without_a_limit_nothing_is_truncated(self) -> None:
        """The opt out the Google adapter takes, because `as_match` caps after it."""
        assert join_categories(["a"] * 40, limit=None) == CATEGORY_SEPARATOR.join(
            ["a"] * 40
        )

    def test_a_list_inside_the_limit_is_untouched(self) -> None:
        """The false refusal the cap could have bought."""
        assert join_categories(["a"] * 32, limit=32) == CATEGORY_SEPARATOR.join(
            ["a"] * 32
        )

    def test_the_drop_runs_before_the_truncation(self) -> None:
        """`bounded_headings`' rule, and the arm that separates the two orders.

        The separator bearing subjects are at the **front**, so truncating first
        would keep them, watch the join drop them, and answer **30** against a limit
        of 32, having discarded the two good subjects that sat behind them. Measured
        both ways. Dropping first answers the limit exactly.
        """
        supplied = ["bad;one", "bad;two"] + [f"good {i}" for i in range(32)]

        stored = join_categories(supplied, limit=32)

        assert split_categories(stored) == [f"good {i}" for i in range(32)]


#: Subjects as a catalogue might send them: padded, empty, and carrying the
#: separator bare or spaced, which are the four shapes the identity below turns on.
_SUBJECTS = st.lists(
    st.one_of(
        st.text(alphabet="ab ;", max_size=6),
        st.sampled_from(["", " ", "Fiction; general", " Horror "]),
    ),
    max_size=40,
)


class TestTheListFormIsWhatAReaderGetsBack:
    """`kept_categories` is the joined value as `split_categories` reads it back.

    **This identity is what lets an adapter hand on a list rather than a string.**
    The Google adapter's list feeds `Record.subjects`, whose other readers saw the
    split of a join before; any difference would be a behaviour change in what
    they read. The right hand side is the join spelled without the module's own
    trim, so it cannot be a restatement of the left.
    """

    @pytest.mark.property
    @given(subjects=_SUBJECTS, limit=st.sampled_from([None, 0, 1, 3, 32]))
    def test_the_list_equals_the_split_of_the_join(
        self, subjects: list[str], limit: int | None
    ) -> None:
        bare = CATEGORY_SEPARATOR.strip()
        storable = [subject for subject in subjects if bare not in subject]
        capped = storable if limit is None else storable[:limit]

        assert kept_categories(subjects, limit=limit) == split_categories(
            CATEGORY_SEPARATOR.join(capped)
        )


class TestARequestEntryCarryingTheSeparatorIsRefused:
    """`refuse_separator`, the request bodies' policy, on its own."""

    def test_an_entry_with_the_bare_separator_is_refused(self) -> None:
        with pytest.raises(ValueError, match="may not contain"):
            refuse_separator("Fiction;general")

    def test_an_entry_without_it_is_returned_unchanged(self) -> None:
        """The false refusal: a comma is Google's own and is kept."""
        assert refuse_separator("Fiction, general") == "Fiction, general"


def test_the_module_imports_nothing_from_the_application() -> None:
    """**The class this stops is the import cycle that held the codec in the
    Google Books adapter.** That adapter needs `BookMatch` and `schemas.book`
    needs the codec, so a codec module importing the application can be pulled
    into the same cycle again. A standard library import cannot."""
    tree = ast.parse(Path(categories.__file__).read_text())
    imported = {
        alias.name.split(".")[0]
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    } | {
        (node.module or "").split(".")[0]
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom)
    }

    assert imported, "the walk found no import at all, so it is looking at nothing"
    assert imported <= set(sys.stdlib_module_names), sorted(
        imported - set(sys.stdlib_module_names)
    )
