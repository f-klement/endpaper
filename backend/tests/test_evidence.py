"""Tests for backend/evidence.py: one policy per way outside evidence meets a Book.

The match level rule, the bound on a record, the refresh policy's column set and
the importers' door. What each route does around it is in the router tests.
"""

import ast
import importlib
import logging
import symtable
from collections import Counter
from collections.abc import Iterable
from types import ModuleType
from typing import Any, Final

import pytest
from sqlalchemy.orm.attributes import set_committed_value

import classifications
import covers
import evidence
import models
from catalogue import Record, Subject
from categories import join_categories
from evidence import Policy, _apply_match, _bounded_match
from google_books import _volume_to_fields
from models import Book
from schemas import BookMatch
from tests.bindings import SourceNames, source_of
from tests.corpus import BACKEND, shipped_modules
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


def _stored_blank(value: str) -> Book:
    """A Book whose `publisher` was read from the database holding `value`.

    Loaded rather than constructed, because `Book`'s own hook nulls a blank on
    construction: a row from before revision d3f8a1c6b250 is the shape that
    still reaches evidence holding one."""
    book = Book(title="Dune")
    set_committed_value(book, "publisher", value)
    return book


class TestEmptyIsNoneOrABlankString:
    def test_a_stored_empty_string_is_filled_from_a_match(self):
        book = _stored_blank("")

        assert "publisher" in _apply_match(book, _as_match(VOLUME), Policy.FILL_GAPS)
        assert book.publisher == "Chilton"

    def test_a_stored_whitespace_value_is_a_gap_too(self):
        book = _stored_blank("  ")

        assert "publisher" in _apply_match(book, _as_match(VOLUME), Policy.FILL_GAPS)
        assert book.publisher == "Chilton"

    def test_an_incoming_whitespace_value_asserts_nothing(self):
        book = Book(title="Dune")

        assert evidence.fill_gaps(book, {"publisher": " \t"}) == []
        assert book.publisher is None

    @pytest.mark.parametrize("blank", ["", "   "])
    def test_a_refresh_clears_to_null_rather_than_to_the_blank(self, blank):
        """A source answering a blank clears the column as silence does: null
        afterwards, and a second refresh with the same blank changes nothing.
        `Book`'s hook would null a blank written back anyway; what the second
        refresh measures is that evidence compares the null, so it does not
        report a column changed that was not."""
        book = Book(title="Dune", author="Frank Herbert")

        evidence.apply_record(book, Record(author=blank), Policy.REFRESH)

        assert book.author is None
        assert "author" not in evidence.apply_record(
            book, Record(author=blank), Policy.REFRESH
        )

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
    "subjects": (Subject("Science fiction"),),
}


#: Spelled out rather than read off `evidence.REFRESHED`, so a column joining or
#: leaving that tuple is a diff here as well as there. A refresh writing one of
#: the four it skips past the tuple reddens too: `_ASSERTED` asserts each of
#: them, `categories` through its subject. Why these nine and not `categories`,
#: the series fields or `google_books_id` is in `docs/decisions.md`.
_REFRESHED_NINE: Final = frozenset({
    "title", "subtitle", "author", "publisher", "year", "description",
    "language", "page_count", "cover_url",
})


class TestARefreshWritesExactlyItsNineColumns:
    def test_it_writes_the_nine_and_nothing_else(self):
        book = Book(**_HELD)

        changed = evidence.apply_record(book, Record(**_ASSERTED), Policy.REFRESH)

        assert sorted(changed) == sorted(_REFRESHED_NINE)
        assert {*evidence.REFRESHED, "cover_url"} == _REFRESHED_NINE
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


#: Spelled out for `_REFRESHED_NINE`'s reason. A record no Member selected
#: writes what a refresh writes, less `title`, which is work identity outside a
#: refresh. Owner's ruling of 2026-10-15.
_ENRICHED_EIGHT: Final = _REFRESHED_NINE - {"title"}
_SELECTED_ONLY: Final = frozenset(
    {"categories", "series_name", "series_index", "google_books_id"}
)


class TestARecordNobodySelectedWritesWhatARefreshWrites:
    @pytest.mark.parametrize(
        ("policy", "held"),
        [(Policy.FILL_GAPS, {"title": "Held"}), (Policy.OVERWRITE, _HELD)],
        ids=["fill_gaps", "overwrite"],
    )
    def test_enrichment_writes_the_eight_and_nothing_else(self, policy, held):
        book = Book(**held)

        changed = evidence.apply_record(book, Record(**_ASSERTED), policy)

        assert sorted(changed) == sorted(_ENRICHED_EIGHT)
        assert set(evidence.SELECTED_ONLY) == _SELECTED_ONLY
        assert book.title == "Held"
        assert (
            book.categories, book.series_name, book.series_index, book.google_books_id
        ) == tuple(held.get(name) for name in (
            "categories", "series_name", "series_index", "google_books_id"
        ))

    def test_an_own_volume_record_writes_the_eight_and_the_volume_id(self):
        book = Book(title="Held")

        changed = evidence.apply_own_volume(
            book, Record(**_ASSERTED), "gbid00000001", Policy.FILL_GAPS
        )

        assert sorted(changed) == sorted(_ENRICHED_EIGHT | {"google_books_id"})
        assert book.google_books_id == "gbid00000001"
        assert (book.categories, book.series_name, book.series_index) == (
            None, None, None,
        )

    def test_a_record_carrying_another_id_than_the_one_looked_up_writes_no_id(self):
        book = Book(title="Held")

        changed = evidence.apply_own_volume(
            book, Record(**_ASSERTED), "otherotherid", Policy.FILL_GAPS
        )

        assert sorted(changed) == sorted(_ENRICHED_EIGHT)
        assert book.google_books_id is None

    def test_a_selected_record_writes_the_four(self, db):
        """The picker is now the only door for them, so its half is pinned."""
        book = Book(title="Held")

        changed = evidence.confirm(
            book, BookMatch(**Record(**_ASSERTED).as_match()), db, Policy.FILL_GAPS
        )

        assert set(changed) >= _SELECTED_ONLY
        assert (book.series_name, book.series_index, book.google_books_id) == (
            "Dune Chronicles", 2.0, "gbid00000001",
        )
        assert book.categories


#: Each function that names a heading writer, and how many times.
#:
#: **A heading writer** is `classifications.add_headings`, the `Classification`
#: constructor, and the two doors here that call the first. Equality keyed by
#: the enclosing function, so a new site reds by name, and so does one removed
#: or moved without its row.
HEADING_WRITES: Final[dict[str, dict[str, dict[str, int]]]] = {
    # The writer itself: the ceiling and the dedupe live around this one row.
    "classifications.py": {"add_headings": {"models.Classification": 1}},
    "evidence.py": {
        # The doors' own import.
        "<module>": {"classifications.add_headings": 1},
        # ADR 0006's route, `POST /{book_id}/enrich/apply`, through this door.
        "confirm": {"classifications.add_headings": 1},
        # The owner's ruling on the MARC importer: choosing the file is the
        # confirmation.
        "confirm_file_headings": {"classifications.add_headings": 1},
    },
    # A MARC file a Member chose to import, through its door.
    "importing.py": {"MarcImport._apply_one": {"evidence.confirm_file_headings": 1}},
    "routers/books.py": {
        # For `_create_book` alone, the one function here that calls it.
        "<module>": {"classifications.add_headings": 1},
        # A NEW Book, not an existing one: this function constructs it with
        # `Book(...)` and adds it a few lines above the call, so the Book holds
        # no row before these, and the headings are those the Member sent in
        # the create body.
        "_create_book": {"classifications.add_headings": 1},
        # `POST /{book_id}/enrich/apply`: the record row a Member selected.
        "apply_enrichment": {"evidence.confirm": 1},
    },
}

#: Named anywhere, called or not, so a writer handed on is seen where it is
#: handed: an import, a `partial`, an attribute holding it, a decorator, a
#: re-export under any name.
_NAMED: Final[tuple[tuple[object, str], ...]] = (
    (classifications.add_headings, "classifications.add_headings"),
    (evidence.confirm, "evidence.confirm"),
    (evidence.confirm_file_headings, "evidence.confirm_file_headings"),
)
#: Called, because most names of the model are reads: a query's entity, a
#: column, the restore's table list.
_CALLED: Final[tuple[tuple[object, str], ...]] = (
    (models.Classification, "models.Classification"),
)


def _module(name: str) -> ModuleType | None:
    """The module `name` imports, or None where it is not one."""
    try:
        return importlib.import_module(name)
    except (ImportError, TypeError, ValueError):
        return None


def _writer(meaning: str, writers: tuple[tuple[object, str], ...]) -> str | None:
    """The one of `writers` a dotted name holds, as Python would look it up, or None.

    Looked up rather than compared as text, so a re-export (`from evidence
    import add_headings`) is the writer it holds. Only a name ending in one of
    the writers' own names is looked up, which keeps imports to those, and is
    why a name re-exported under a new name is not the writer here. A writer
    in `_NAMED` so re-exported reds where the re-export is made, which names
    it; the constructor so re-exported is not seen.
    """
    if meaning.rsplit(".", 1)[-1] not in {label.rsplit(".", 1)[-1] for _, label in writers}:
        return None
    parts = meaning.split(".")
    for cut in range(len(parts), 0, -1):
        found: object = _module(".".join(parts[:cut]))
        if found is None:
            continue
        for part in parts[cut:]:
            found = getattr(found, part, None)
        return next((label for writer, label in writers if writer is found), None)
    return None


def _scope(table: symtable.SymbolTable, name: str, line: int) -> symtable.SymbolTable:
    """The scope `table` opens for the function, class or lambda `name` at `line`."""
    return next(
        (
            child
            for child in table.get_children()
            if child.get_name() == name and child.get_lineno() == line
        ),
        table,
    )


def _global(name: str, table: symtable.SymbolTable, bound: frozenset[str]) -> bool:
    """Whether a bare `name` read in `table` is the module's binding.

    Read the way the compiler reads it. `bound` holds the comprehension
    variables around the read, because an inlined comprehension leaves none of
    its own in the table.
    """
    if name in bound:
        return False
    if table.get_type() == symtable.SymbolTableType.MODULE:
        return True
    try:
        return table.lookup(name).is_global()
    except KeyError:
        return True


def _heading_writes(
    source: str, package: str | None = None, module: str | None = None
) -> dict[str, dict[str, int]]:
    """The heading writes in `source`, counted by enclosing function.

    Keyed by the dotted names of the classes and functions around a site,
    `<module>` outside all of them. A writer in `_NAMED` counts each time a
    name holds it, `_CALLED` each time it is called, whatever the name is
    spelled through: an alias, the module, a rebinding, a re-export (for
    `_CALLED`, one under its own name). `module` is the dotted name `source` is
    imported under, so a bare name it defines is seen too: `add_headings`
    called inside `classifications`. A bare name bound in its own scope, a
    parameter, a local, a class attribute or a comprehension variable, is
    neither the module's nor what the module imports under that name: without
    that, `def apply_record(db, confirm=False)` in `evidence` would name a
    door. So a writer imported inside a function counts at the import alone.
    """
    names = SourceNames(source, package=package, star=_module)
    counts: dict[str, Counter[str]] = {}

    def count(
        around: tuple[str, ...], meanings: Iterable[str], writers: tuple[tuple[object, str], ...]
    ) -> None:
        for label in {w for m in meanings if (w := _writer(m, writers))}:
            counts.setdefault(".".join(around) or "<module>", Counter())[label] += 1

    def visit(
        node: ast.AST, around: tuple[str, ...], table: symtable.SymbolTable, bound: frozenset[str]
    ) -> None:
        if isinstance(node, ast.Import | ast.ImportFrom):
            alone = SourceNames(
                ast.Module(body=[node], type_ignores=[]), package=package, star=_module
            )
            count(around, {binding.target for binding in alone.bindings}, _NAMED)
        elif isinstance(node, ast.Attribute) and isinstance(node.ctx, ast.Load):
            count(around, names.means(node), _NAMED)
        elif (
            isinstance(node, ast.Name)
            and isinstance(node.ctx, ast.Load)
            and _global(node.id, table, bound)
        ):
            own = {f"{module}.{node.id}"} if module else set()
            count(around, names.means(node) | own, _NAMED)
        elif isinstance(node, ast.Call):
            count(around, names.means(node.func), _CALLED)
        # Only a body runs in the new scope; decorators, defaults and bases run
        # in the one around it.
        inner: symtable.SymbolTable = table
        body: tuple[ast.AST, ...] = ()
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
            around = (*around, node.name)
            inner, body = _scope(table, node.name, node.lineno), tuple(node.body)
        elif isinstance(node, ast.Lambda):
            inner, body = _scope(table, "lambda", node.lineno), (node.body,)
        elif isinstance(node, ast.ListComp | ast.SetComp | ast.DictComp | ast.GeneratorExp):
            bound |= {
                name.id
                for generator in node.generators
                for name in ast.walk(generator.target)
                if isinstance(name, ast.Name)
            }
        for child in ast.iter_child_nodes(node):
            visit(child, around, inner if any(child is b for b in body) else table, bound)

    visit(ast.parse(source), (), symtable.symtable(source, module or "<source>", "exec"), frozenset())
    return {where: dict(found) for where, found in counts.items()}


class TestClassificationsReachAnExistingBookOnlyThroughEvidence:
    """ADR 0006: only the functions in `HEADING_WRITES` reach a heading writer.

    Every shipped module is read, the application and its migrations, and a
    name is resolved the way Python resolves it. What this lets through:

    * a row moved by repointing its `book_id`, which is how a merge carries the
      losers' headings (`folding`);
    * an edit to a stored row's columns, which is how a merge keeps a losing
      caption (`folding._absorb_heading`): only a row's creation counts;
    * a write that constructs nothing, a Core `insert` or a
      `bulk_insert_mappings` anywhere, of which a restore's whole library
      (`backup`) is the one live member;
    * the model handed on uncalled, such as `partial(Classification, ...)`,
      because the constructor is counted by call;
    * a caller of a function that is itself in the table, such as a module
      re-exporting a writer under a new name once its row is stated;
    * a writer reached through a name built at run time (`getattr` with a
      string, `importlib`), which takes a deliberate act.
    """

    def test_only_the_stated_functions_reach_a_heading_writer(self) -> None:
        found: dict[str, dict[str, dict[str, int]]] = {}
        for path in shipped_modules():
            relative = path.relative_to(BACKEND)
            package = ".".join(relative.parent.parts) or None
            module = ".".join(relative.with_suffix("").parts).removesuffix(".__init__")
            if writes := _heading_writes(source_of(path), package, module):
                found[relative.as_posix()] = writes

        assert found == HEADING_WRITES, (
            "a function reaches a Classifications writer, or stopped. A Book that "
            "exists takes them through `evidence` (ADR 0006); state a new door here."
        )

    @pytest.mark.parametrize(
        ("source", "writes"),
        [
            (
                "from classifications import add_headings\n"
                "def f(book, db):\n    add_headings(book, [], db)",
                {"<module>": {"classifications.add_headings": 1},
                 "f": {"classifications.add_headings": 1}},
            ),
            (
                "from classifications import add_headings as more\n"
                "def f(book, db):\n    more(book, [], db)",
                {"<module>": {"classifications.add_headings": 1},
                 "f": {"classifications.add_headings": 1}},
            ),
            (
                "import classifications\n"
                "def f(book, db):\n    classifications.add_headings(book, [], db)",
                {"f": {"classifications.add_headings": 1}},
            ),
            (
                "import classifications as c\n"
                "class C:\n    def m(self, book, db):\n        c.add_headings(book, [], db)",
                {"C.m": {"classifications.add_headings": 1}},
            ),
            (
                "from evidence import add_headings\n"
                "def f(book, db):\n    add_headings(book, [], db)",
                {"<module>": {"classifications.add_headings": 1},
                 "f": {"classifications.add_headings": 1}},
            ),
            (
                "import evidence\n"
                "def f(book, db):\n    evidence.add_headings(book, [], db)",
                {"f": {"classifications.add_headings": 1}},
            ),
            (
                "from classifications import add_headings\nwrite = add_headings\n"
                "def f(book, db):\n    write(book, [], db)",
                {"<module>": {"classifications.add_headings": 2},
                 "f": {"classifications.add_headings": 1}},
            ),
            (
                "import classifications\nfrom functools import partial\n"
                "def f(book, db):\n    partial(classifications.add_headings, db=db)(book, [])",
                {"f": {"classifications.add_headings": 1}},
            ),
            (
                "import classifications\nclass C:\n    def __init__(self):\n"
                "        self.write = classifications.add_headings",
                {"C.__init__": {"classifications.add_headings": 1}},
            ),
            (
                "import classifications\n"
                "@classifications.add_headings\ndef f():\n    pass",
                {"f": {"classifications.add_headings": 1}},
            ),
            (
                "from classifications import add_headings as attach_headings",
                {"<module>": {"classifications.add_headings": 1}},
            ),
            (
                "import evidence\ndef f(run):\n    run(evidence.confirm)",
                {"f": {"evidence.confirm": 1}},
            ),
            (
                "from models import Classification\n"
                "def f(book):\n    book.classifications.append(Classification(number='004'))",
                {"f": {"models.Classification": 1}},
            ),
            (
                "import models\n"
                "def f(book):\n    book.classifications = [models.Classification(number='004')]",
                {"f": {"models.Classification": 1}},
            ),
            (
                "import evidence\n"
                "def f(book, db):\n    evidence.confirm_file_headings(book, [], db)",
                {"f": {"evidence.confirm_file_headings": 1}},
            ),
            (
                "from models import Classification\n"
                "def f(db):\n    return db.query(Classification.number).all()",
                {},
            ),
            ("from classifications import bounded_headings\nimport evidence", {}),
            ("def add_headings(*args):\n    pass\ndef f():\n    add_headings()", {}),
            ("import catalogue\ndef f(db):\n    db.confirm()\n    catalogue.confirm()", {}),
            (
                "from helpers import attach_headings\n"
                "def f(book, db):\n    attach_headings(book, [], db)",
                {},
            ),
            (
                "from sqlalchemy import insert\nfrom models import Classification\n"
                "def f(db, rows):\n    db.execute(insert(Classification), rows)",
                {},
            ),
            (
                "from models import Classification\n"
                "def f(db, rows):\n    db.execute(Classification.__table__.insert(), rows)",
                {},
            ),
            (
                "from models import Classification\n"
                "def f(db, rows):\n    db.bulk_insert_mappings(Classification, rows)",
                {},
            ),
        ],
        ids=[
            "imported",
            "imported under another name",
            "off the module",
            "off the module under another name, in a method",
            "re-exported by evidence",
            "off evidence",
            "rebound",
            "handed to partial",
            "held by an instance attribute",
            "a decorator",
            "re-exported under a new name, where it is made",
            "a door handed on, not called",
            "a row appended to an existing Book",
            "a row assigned through the module",
            "the file door",
            "a column read, not a write",
            "another name from the writer's module, and the doors' module",
            "a function of the same name defined elsewhere",
            "a method of the same name on something else",
            "miss: a consumer of a re-export under a new name",
            "miss: a Core insert",
            "miss: the table's own insert",
            "miss: bulk_insert_mappings",
        ],
    )
    def test_what_counts_as_a_heading_write(
        self, source: str, writes: dict[str, dict[str, int]]
    ) -> None:
        assert _heading_writes(source) == writes

    def test_a_writer_named_bare_in_its_own_module_counts(self) -> None:
        """A name a module binds by `def` means nothing to `SourceNames`, so a
        second caller inside `classifications` is seen only through `module`."""
        source = (
            "def add_headings(book, headings, db):\n    pass\n"
            "def f(book, db):\n    add_headings(book, [], db)"
        )

        assert _heading_writes(source, module="classifications") == {
            "f": {"classifications.add_headings": 1}
        }

    @pytest.mark.parametrize(
        ("source", "writes"),
        [
            ("def apply_record(db, confirm=False):\n    if confirm:\n        pass", {}),
            ("def f():\n    confirm = True\n    return confirm", {}),
            ("class C:\n    confirm = False\n    later = confirm", {}),
            ("def f(xs):\n    return [confirm for confirm in xs]", {}),
            ("def f(xs):\n    return lambda confirm: confirm", {}),
            (
                "def f(book, db):\n    confirm(book, db)",
                {"f": {"evidence.confirm": 1}},
            ),
            (
                "def f(confirm=confirm):\n    return confirm",
                {"f": {"evidence.confirm": 1}},
            ),
            (
                "from classifications import add_headings\n"
                "def f():\n    add_headings = None\n    return add_headings",
                {"<module>": {"classifications.add_headings": 1}},
            ),
            (
                "def f(book, db):\n    from classifications import add_headings\n"
                "    add_headings(book, [], db)",
                {"f": {"classifications.add_headings": 1}},
            ),
        ],
        ids=[
            "a parameter of a door's name",
            "a local of a door's name",
            "a class attribute of a door's name",
            "a comprehension variable of a door's name",
            "a lambda parameter of a door's name",
            "the module's own door, read from a function",
            "the module's own door as a default, read around the function",
            "a local shadowing an imported writer",
            "a writer imported inside a function, counted at the import",
        ],
    )
    def test_a_name_bound_in_its_own_scope_is_not_the_modules(
        self, source: str, writes: dict[str, dict[str, int]]
    ) -> None:
        assert _heading_writes(source, module="evidence") == writes
