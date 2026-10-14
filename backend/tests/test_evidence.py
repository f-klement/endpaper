"""Tests for backend/evidence.py: one policy per way outside evidence meets a Book.

The match level rule, the bound on a record, the refresh policy's column set and
the importers' door. What each route does around it is in the router tests.
"""

import logging
from typing import Any, Final

import pytest

import covers
import evidence
from catalogue import Record
from categories import join_categories
from evidence import Policy, _apply_match, _bounded_match
from google_books import _volume_to_fields
from models import Book
from schemas import BookMatch
from tests.test_google_books import VOLUME


def _as_match(volume: dict) -> BookMatch:
    """A Google volume through the bound `_apply_match` insists on.

    `_apply_match` takes a `BookMatch` rather than a dictionary, so a test that
    hands it a dictionary is testing a call the type checker refuses. That is
    the point of the signature and not an inconvenience of it: see
    `TestTheSignatureIsTheBound` below.
    """
    fields = _volume_to_fields(volume)
    # Joined as `catalogue.Record.as_match` joins it on the application's path,
    # since the adapter hands on a list and `BookMatch` carries the stored form.
    fields["categories"] = join_categories(fields["categories"])
    return BookMatch(**fields)


class TestMergeInto:
    """The rule that matters: fill gaps, do not overrule people."""

    def test_fills_an_empty_field(self):
        book = Book(title="Dune", page_count=None)
        changed = _apply_match(book, _as_match(VOLUME), Policy.FILL_GAPS)

        assert book.page_count == 412
        assert "page_count" in changed

    def test_leaves_an_existing_value_alone(self):
        # A member who corrected a value should not have Google undo it.
        book = Book(title="Dune", publisher="The edition I actually own")
        _apply_match(book, _as_match(VOLUME), Policy.FILL_GAPS)

        assert book.publisher == "The edition I actually own"

    def test_overwriting_with_the_value_already_there_reports_no_change(self):
        book = Book(title="Dune", publisher="Chilton")
        changed = _apply_match(book, _as_match(VOLUME), Policy.OVERWRITE)

        assert "publisher" not in changed

    def test_overwrite_replaces_it_when_asked(self):
        book = Book(title="Dune", publisher="Wrong")
        _apply_match(book, _as_match(VOLUME), Policy.OVERWRITE)

        assert book.publisher == "Chilton"

    def test_reports_only_what_actually_changed(self):
        # Enrichment often finds a volume and has nothing to add; saying
        # "done" would look like a no-op bug.
        book = Book(title="Dune", page_count=412, language="en")
        fields = {"page_count": 412, "language": "en"}

        assert _apply_match(book, BookMatch(**fields), Policy.FILL_GAPS) == []

    def test_ignores_fields_google_left_empty(self):
        book = Book(title="Dune", publisher="Chilton")
        _apply_match(book, BookMatch(publisher=None, page_count=None), Policy.OVERWRITE)

        assert book.publisher == "Chilton"

    def test_never_replaces_a_locally_uploaded_cover(self):
        # An uploaded cover lives under the local prefix and outranks a remote
        # one, which is the same question the metadata refresh asks.
        book = Book(title="Dune", cover_url="/covers/12.png")
        _apply_match(book, _as_match(VOLUME), Policy.OVERWRITE)

        assert book.cover_url == "/covers/12.png"

    def test_the_local_cover_rule_is_covers_own(self, monkeypatch):
        """Behavioural, because a grep is satisfied by the defect it replaced.

        This writer spelled the prefix itself. Every arm above passed, and goes
        on passing, for a copy of the literal: the two answers only diverge once
        the prefix moves. `covers.is_local` reads `LOCAL_COVER_PREFIX` at call
        time, so moving it here moves this writer with it, and a copy answers
        for the old prefix and overrules an upload the refresh handler protects.

        The structural half is
        `test_covers.py::TestNoOtherModuleDecidesWhetherACoverIsLocal`, which
        refuses the copy in any module rather than at this one call.
        """
        monkeypatch.setattr(covers, "LOCAL_COVER_PREFIX", "/held/")
        book = Book(title="Dune", cover_url="/held/1.jpg")

        # The cover alone: this volume fills nine other empty fields, and the
        # question here is which of them `cover_url` is not.
        assert "cover_url" not in _apply_match(book, _as_match(VOLUME), Policy.OVERWRITE)
        assert book.cover_url == "/held/1.jpg"

    def test_fills_an_absent_cover(self):
        book = Book(title="Dune", cover_url=None)
        changed = _apply_match(book, _as_match(VOLUME), Policy.FILL_GAPS)

        assert book.cover_url == "https://books.google.com/cover.jpg"
        assert "cover_url" in changed

    def test_does_not_touch_the_title(self):
        """Deliberately excluded from the merge list.

        A title is how the book is recognised on the shelf, and Google's
        spelling of it (series numbering, subtitle folded in) is often not the
        one the library uses.
        """
        book = Book(title="Dune (Dune Chronicles, Book 1)")
        _apply_match(book, _as_match(VOLUME), Policy.OVERWRITE)

        assert book.title == "Dune (Dune Chronicles, Book 1)"


class TestTheSignatureIsTheBound:
    """`_apply_match` takes a `BookMatch`, and that type is the whole guard.

    Every route that reaches this function writes third party values into columns.
    Until 2026-09-03 one of them validated its dictionary through the model and
    the other passed `Record.as_match()` straight through, so the identical
    oversized value was a 422 on `POST /{id}/enrich/apply` and a stored row on
    `POST /{id}/enrich`.

    The fix is a type rather than a call site convention, because a convention
    is what the second route already failed to follow. mypy refuses a
    dictionary at any call site; these pin the arms mypy cannot, which are a
    caller that never runs it and a later edit that widens the annotation back.
    """

    #: The five `BookMatch` fields `_apply_match` deliberately leaves alone, and
    #: why. Named rather than counted, so the partition below has to sum.
    #:
    #: `source` labels the picker row and has no column. `title` is how a book
    #: is recognised on the shelf and Google's spelling of it is often not the
    #: library's. `isbn13` is one printing among several rather than this copy.
    #: `classifications` and `suggested_tag_ids` are not scalars and are
    #: applied by `confirm` and by the caller respectively.
    NOT_WRITTEN = frozenset(
        {"source", "title", "isbn13", "classifications", "suggested_tag_ids"}
    )

    def _names_read_off_the_match(self) -> set[str]:
        """Every field name `_apply_match` takes off its argument, from the source.

        Two shapes, because the function uses two: a `getattr` over whatever the
        loop walks, and a direct attribute access for the cover. Reading both is
        what makes this a second derivation rather than a re-reading of the set,
        and the cover is the name only the second shape sees.

        **The loop's iterator is evaluated, not pattern matched.** A walk that
        reads `loop.iter.elts` sees a literal and nothing else, so it returns the
        empty set the moment the loop names a constant instead: the partition
        below then goes short and fails, which is the right direction, but it
        makes this a question about a spelling rather than about the columns.
        Evaluating the expression in the module's own namespace follows any
        spelling there is, for `test_the_model_is_the_only_channel_into_it`'s
        reason about `ast.unparse`: enumerating the kinds is the shape this
        repository keeps paying for.
        """
        import ast
        import inspect

        import evidence

        tree = ast.parse(inspect.getsource(evidence))
        fn = next(
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.FunctionDef) and node.name == "_apply_match"
        )
        names = {
            node.attr
            for node in ast.walk(fn)
            if isinstance(node, ast.Attribute)
            and isinstance(node.value, ast.Name)
            and node.value.id == "match"
        }
        for loop in (node for node in ast.walk(fn) if isinstance(node, ast.For)):
            walked = eval(ast.unparse(loop.iter), vars(evidence))
            names |= {name for name in walked if isinstance(name, str)}
        return names

    def test_every_column_it_writes_is_a_field_the_model_bounds(self):
        """The partition has to sum, which is what stops it going vacuous.

        An empty walk would leave the union short of the model's own fields and
        fail here rather than passing quietly, and a name added to the merge
        list that `BookMatch` does not carry cannot be bounded by anything.
        """
        written = self._names_read_off_the_match()

        assert written & self.NOT_WRITTEN == set()
        assert written | self.NOT_WRITTEN == set(BookMatch.model_fields)

    def test_the_model_is_the_only_channel_into_it(self):
        """Widening the annotation reopens the hole in silence, and so does
        leaving it alone and adding a second parameter beside it.

        mypy is what actually enforces the door, so the annotation is the door,
        and the parameter list is what stops a second door being cut. The
        partition above sees neither: it reads the names taken **off** `match`,
        so an unbounded dictionary arriving under another name writes the same
        columns and leaves that set untouched.

        **The whole argument list, not a list of its parts.** The first version
        of this checked `args`, `kwonlyargs`, `vararg` and `kwarg`, which is
        four of the five kinds an argument list has, and a security seat walked
        a `raw: dict, /` positional only parameter past both guards on the
        fifth, reading it in the body as `raw["series_index"]` where no
        `ast.Attribute` on `match` exists for the partition to see. Enumerating
        the kinds is the shape this repository keeps paying for; unparsing the
        node covers every kind there is, and the defaults and annotations with
        them, leaving no arm to add for the next one.
        """
        import ast
        import inspect

        import evidence

        tree = ast.parse(inspect.getsource(evidence))
        fn = next(
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.FunctionDef) and node.name == "_apply_match"
        )

        assert (
            ast.unparse(fn.args) == "book: Book, match: BookMatch, policy: Policy"
        )

    def test_a_bare_dictionary_raises_rather_than_writing(self):
        """The runtime arm, for a caller mypy never saw.

        It fails on the first field rather than on the twelfth, so nothing is
        half written when it does.
        """
        book = Book(title="Dune", page_count=None)

        with pytest.raises(AttributeError, match="'dict' object has no attribute"):
            _apply_match(book, _volume_to_fields(VOLUME), Policy.FILL_GAPS)  # type: ignore[arg-type]

        assert book.page_count is None


class TestBoundingOneRecord:
    """`evidence._bounded_match`, the door `apply_record` bounds a record through.

    Its policy is per field where its neighbour `_match_rows` is per row, and
    the two disagree in a way a member can see: a record the picker refuses to
    show whole is a record the unattended route still fills a Book from.
    Measured, and filed rather than resolved here. These drive the arms the
    route tests above cannot reach from outside.
    """

    def test_a_clean_record_arrives_whole(self):
        match = _bounded_match({"title": "Dune", "page_count": 412, "year": 1965})

        assert (match.title, match.page_count, match.year) == ("Dune", 412, 1965)

    def test_only_the_refused_field_is_dropped(self):
        match = _bounded_match({"title": "Dune", "series_index": 1e9})

        assert match.title == "Dune"
        assert match.series_index is None

    def test_two_refused_fields_are_both_dropped(self):
        """Pydantic collects every field error in one pass, so this costs one
        iteration rather than two. Pinned anyway, because the loop's
        termination argument does not rest on that and a reader should not have
        to assume it.
        """
        match = _bounded_match({"title": "Dune", "series_index": 1e9, "year": 99999})

        assert match.title == "Dune"
        assert match.series_index is None
        assert match.year is None

    def test_a_refusal_naming_no_field_gives_up_on_the_record(
        self, monkeypatch, caplog
    ):
        """The arm there is nothing to drop for.

        `BookMatch` carries no model level validator today, which is exactly
        why this drives one in rather than asserting the arm is there.
        Measured: pydantic reports a `mode="after"` model validator's error at
        `loc == ()`, where a field error reports `loc == ("title",)`.

        The log is what separates this arm from the loop simply running out,
        which the bound makes it do to the same value. Without the early exit
        the record is reported as a dropped field, repeatedly, naming none.
        """
        from pydantic import BaseModel, Field, model_validator

        import evidence

        class Stub(BaseModel):
            title: str | None = Field(default=None, max_length=500)

            @model_validator(mode="after")
            def _refuse_shouting(self):
                if self.title == "SHOUT":
                    raise ValueError("not that one")
                return self

        monkeypatch.setattr(evidence, "BookMatch", Stub)

        with caplog.at_level(logging.INFO, logger="endpaper.evidence"):
            assert evidence._bounded_match({"title": "SHOUT"}).title is None

        assert "Discarded" in caplog.text
        assert "Dropped" not in caplog.text
        assert evidence._bounded_match({"title": "Dune"}).title == "Dune"

    def test_a_record_whose_every_field_is_refused_is_not_a_discard(self, caplog):
        """The pass the loop bound's `+ 1` exists for.

        Every pass deletes at least one key, so a record of one refused field
        needs a second pass to answer with the empty match. A bound of exactly
        one pass per key falls through to the fallback instead and reaches the
        same value, so only the log tells the two apart: this record was read
        and stripped, it was not refused whole.
        """
        with caplog.at_level(logging.INFO, logger="endpaper.evidence"):
            match = _bounded_match({"series_index": 1e9})

        assert match.series_index is None
        assert "series_index" in caplog.text
        assert "Discarded" not in caplog.text

    def test_a_field_the_record_never_supplied_is_not_deleted_from_it(
        self, monkeypatch
    ):
        """The arm the first mutation round missed, under its right name.

        Pydantic reports a **missing** required field at a `loc` naming a key
        the record never sent, so without intersecting the refused names with
        the record's own keys the helper deletes a key that is not there.
        Measured on a stub carrying one required field: `Req(title="x" * 10)`
        reports `[('name',), ('title',)]`, only the second of which is in the
        record, and removing the intersection raises `KeyError: 'name'`.

        **It is a `KeyError`, not a stall**, which is what this test was called
        after for one round. There is no shape that repeats a pass: a refused
        set either meets the record, in which case the record shrinks, or it
        does not, in which case the old code raised.

        The same stub drives the give up arm, which is why they are one test:
        with `name` required, `Req()` raises too, so a fallback that validated
        would answer 500 on the one path that exists to avoid one.
        """
        from pydantic import BaseModel, Field

        import evidence

        class Req(BaseModel):
            name: str
            title: str | None = Field(default=None, max_length=5)

        monkeypatch.setattr(evidence, "BookMatch", Req)

        match = evidence._bounded_match({"title": "far too long"})

        assert match.title is None

    def test_the_empty_match_is_what_the_fallback_builds(self):
        """`model_construct` skips validation, so it is worth pinning that it
        still produces the model `BookMatch()` produces rather than something
        emptier. If a required field is ever added the two stop agreeing, and
        this is where that shows up."""

        assert BookMatch.model_construct() == BookMatch()

    def test_it_says_what_it_dropped(self, caplog):
        """A dropped field is invisible in the response by design, so the log
        is where it is recorded. INFO, like `_match_rows`.
        """
        with caplog.at_level(logging.INFO, logger="endpaper.evidence"):
            _bounded_match({"source": "dnb", "title": "Dune", "series_index": 1e9})

        assert "series_index" in caplog.text
        assert "dnb" in caplog.text


class TestEmptyIsNoneOrAnEmptyString:
    def test_a_stored_empty_string_is_filled_from_a_match(self):
        book = Book(title="Dune", publisher="")

        assert "publisher" in _apply_match(book, _as_match(VOLUME), Policy.FILL_GAPS)
        assert book.publisher == "Chilton"

    @pytest.mark.parametrize(
        ("column", "value"), [("isbn", "9780441013593"), ("collection_id", 1)]
    )
    def test_an_importer_may_not_name_a_column_no_file_may_fill(self, column, value):
        """`isbn` is unique across the table, so filling it on a matched Book can
        raise on a row the Member cannot see. `collection_id` is a copy detail no
        importer names: a file setting it would file a matched Book."""
        with pytest.raises(ValueError, match=column):
            evidence.fill_gaps(Book(title="Dune"), {column: value})


#: Every column a refresh may touch, held by a Book before the refresh, and a
#: record asserting a different value for each of them.
_HELD: Final[dict[str, Any]] = {
    "title": "Held", "subtitle": "Held", "author": "Held", "publisher": "Held",
    "year": 1900, "description": "Held", "language": "de", "page_count": 1,
    "categories": "Held", "series_name": "Held", "series_index": 1.0,
    "google_books_id": "heldheldheld", "cover_url": "https://example.com/held.jpg",
}
_ASSERTED: Final[dict[str, Any]] = {
    "title": "Dune", "subtitle": "A Novel", "author": "Frank Herbert",
    "publisher": "Chilton", "year": 1965, "description": "Arrakis.",
    "language": "en", "page_count": 412, "series_name": "Dune Chronicles",
    "series_index": 2.0, "google_books_id": "gbid00000001",
    "cover_url": "https://covers.openlibrary.org/b/id/1-L.jpg",
}


class TestARefreshWritesExactlyItsNineColumns:
    """Pinned as it stands: why it writes `title` and skips `categories`, the
    series fields and `google_books_id` is a decision still to be taken."""

    def test_it_writes_the_nine_and_nothing_else(self):
        book = Book(**_HELD)

        changed = evidence.apply_record(book, Record(**_ASSERTED), Policy.REFRESH)

        assert sorted(changed) == sorted([*evidence.REFRESHED, "cover_url"])
        assert (book.categories, book.series_name, book.series_index) == (
            "Held", "Held", 1.0,
        )
        assert book.google_books_id == "heldheldheld"

    def test_a_source_silent_on_a_column_clears_five_and_keeps_three(self):
        book = Book(**_HELD)

        evidence.apply_record(book, Record(), Policy.REFRESH)

        assert (book.title, book.language, book.page_count) == ("Held", "de", 1)
        assert (
            book.subtitle, book.author, book.publisher, book.year, book.description
        ) == (None, None, None, None, None)
        assert book.cover_url is None

    def test_it_keeps_an_uploaded_cover(self):
        book = Book(**{**_HELD, "cover_url": "/covers/7.png"})

        changed = evidence.apply_record(book, Record(**_ASSERTED), Policy.REFRESH)

        assert "cover_url" not in changed
