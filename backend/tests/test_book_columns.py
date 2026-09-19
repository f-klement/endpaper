"""The partition of `books`' columns: that it is one, and that each cell means it.

Four writers used to carry a tuple of column names each, related to `Book` by
nothing, and a column added to the schema joined none of them with no diagnostic
anywhere. What is here is the rule those four sites could not state between them.

**Two kinds of arm, and the difference is the whole value.** The first kind asks
whether every column has a home, which is a presence check: it goes red on a new
column and says nothing about where it was put. The second asks what a cell
**means**, by deriving what it should hold from a source that is not the cell:
`CopyCreate`, `BookMatch` in both directions, `BookDetailsUpdate`, the compiled
visibility predicate, the foreign key graph, nullability and the unique index.
Those are the arms that see the evasion a presence check cannot, which is a
column classified into the cell beside the right one.

**How much they see, measured rather than claimed**, and the instrument matters
more than the number. Every column moved into every cell it is not in, 150
moves:

- **scored against this file alone, 21 stay green**;
- adding one arm from another file,
  `test_google_books.py::TestTheSignatureIsTheBound::test_every_column_it_writes_is_a_field_the_model_bounds`,
  takes it to **10**. That arm is a guard, not a behaviour test: it partitions
  `BookMatch`'s fields against the names `merge_into` walks, so it sees every
  column that **leaves** `WORK_DETAIL`, and every column arriving there except
  `cover_url`, which `merge_into` already reads off the match by name below its
  loop, so that one move leaves the partitioned set exactly where it was;
- adding `tests/routers/test_books_copies.py` and the rest of
  `test_google_books.py` takes it to **5**.

Recompute rather than copying: the first two fall out of
`book_columns.PARTITION` and the predicates below with no suite run at all, the
third needs those two files run once per move.

**The five, and what the whole suite says about them.** Those figures are
bounded to three files, which is what makes the first two free and is also what
stops any of them meaning "nothing catches this". Scored against the **whole
backend suite**, baseline `7615 passed`, exactly one of the five is green and
has a consequence: `added_at` into `WORK_IDENTITY` puts it in `WORK_FACTS`, so a
new copy carries the parent's added at date and sorts as though it was filed
then, and the suite still reports `7615 passed`.

The other four change **none** of the three doors: `id` and `added_at` into
`COPY_STANDING`, `copy_group` and `ownership` into `ROW_KEEPING`. That they are
observable by nothing is a derivation rather than a sample: the only names any
module that is not a test reads are `WORK_DETAIL`, `WORK_FACTS` and
`FILLABLE_FROM_ANOTHER_ROW`, so a move leaving all three intact cannot change
what any writer does. **That premise is an arm, not a date**:
`test_nothing_outside_the_tests_reaches_past_those_three_names` goes red the day
a module starts reading a fourth name, which is what would turn these four into
observable moves.

**No move that reaches `is_private`, `added_by_user_id` or `deleted_at` is among
them.** All fifteen are caught, by `test_the_visibility_rule_owns_its_columns`
alone. The one of the five that moves `ownership` changes no door.

**What is left with nothing on it** is the border between `COPY_STANDING` and
`ROW_KEEPING`, which no arm separates, and `WORK_IDENTITY`'s membership, which is
how `added_at` gets in unseen. `WORK_COVER`'s border with `WORK_DETAIL` used to
be here and is not: `test_the_cover_is_what_the_copy_route_cannot_carry_in_the_constructor`
closes it in both directions.
"""

import ast
import importlib.util
import inspect
from pathlib import Path
from types import ModuleType
from typing import Final

import pytest
from sqlalchemy import Column, Integer, MetaData, Table
from sqlalchemy.sql import visitors

import book_columns
import models
from schemas.book import BookDetailsUpdate, BookMatch, CopyCreate
from tests.test_house_rules import BACKEND, _every_python_file

BOOK_COLUMNS = Path(__file__).resolve().parent.parent / "book_columns.py"

WORK = set(
    book_columns.WORK_IDENTITY + book_columns.WORK_DETAIL + book_columns.WORK_COVER
)

#: The only `book_columns` names a module that is not a test may read.
#:
#: `WORK_DETAIL` is here because it is a cell two record writers walk directly;
#: the other two are the doors. Everything else is this module's own vocabulary.
REACHABLE: Final = frozenset(
    {"WORK_DETAIL", "WORK_FACTS", "FILLABLE_FROM_ANOTHER_ROW"}
)


def _columns() -> list[str]:
    return list(models.Book.__table__.c.keys())


def _books_table() -> Table:
    table = models.Book.__table__
    assert isinstance(table, Table)
    return table


def _sets_walked_by(module: ModuleType, function: str) -> list[object]:
    """Every module level collection the named function iterates, evaluated.

    The iterator expression rather than its spelling, so a set that moves or is
    renamed is followed and a set written out again at the call site is not: the
    arms below assert **identity** with the module's own tuple, which a literal
    equal to it fails. Evaluated in the module's namespace for the reason
    `tests/test_google_books.py::TestTheSignatureIsTheBound` gives about
    `ast.unparse`, and a local name (`for loser in losers`) raises `NameError`
    there rather than needing a rule to exclude it.
    """
    tree = ast.parse(inspect.getsource(module))
    fn = next(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and node.name == function
    )
    walked: list[object] = []
    for node in ast.walk(fn):
        if not isinstance(node, ast.For | ast.comprehension):
            continue
        try:
            walked.append(eval(ast.unparse(node.iter), vars(module)))
        except NameError:
            continue
    return walked


def _assigned_after_the_insert(module: ModuleType, function: str, constructor: str) -> set[str]:
    """Every attribute the named function stores on the function's single row.

    The row is found by its constructor call rather than by name, and the stores
    are collected anywhere in the function, so neither the local's spelling nor
    the order of the writes is what this asks about. A row built inside a branch
    is found, because the walk descends.

    **Two rows in one function is a refusal, not a choice.** Taking the first in
    walk order would let a second construction earlier in the function be read
    instead of the real one, and the silent version of that is a decoy storing
    exactly the column under test. Nothing else in this helper would notice, so
    the count is asserted before the row is used and the caller is told to say
    which row it meant.
    """
    tree = ast.parse(inspect.getsource(module))
    fn = next(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and node.name == function
    )
    rows = [
        node.targets[0].id
        for node in ast.walk(fn)
        if isinstance(node, ast.Assign)
        and isinstance(node.targets[0], ast.Name)
        and isinstance(node.value, ast.Call)
        and isinstance(node.value.func, ast.Name)
        and node.value.func.id == constructor
    ]
    assert len(rows) == 1, (
        f"{module.__name__}.{function} assigns {len(rows)} {constructor}(...) "
        f"rows to a local, {sorted(rows)}, so there is no single row to read the "
        "post insert writes off and picking one would be arbitrary. Name the row "
        "this is about rather than letting walk order choose it."
    )
    return {
        node.attr
        for node in ast.walk(fn)
        if isinstance(node, ast.Attribute)
        and isinstance(node.ctx, ast.Store)
        and isinstance(node.value, ast.Name)
        and node.value.id == rows[0]
    }


def _names_read_outside_the_tests() -> set[str]:
    """Every `book_columns` name read as code by a module that is not a test.

    **The corpus is `_every_python_file`, not a walk of this file's own.**
    `tests/test_house_rules.py` owns what counts as vendored, and its first
    draft here excluded `.venv` by name, which is the enumeration that file
    records going red on ten of twenty pushes when the pipeline unpacked
    `.uv-cache/`. That rule fires on this module by name
    (`TestTheSourceWalkSeesOnlyThisProject`), which is how the draft was caught.
    The two exclusions left are ours and semantic rather than about vendored
    code: the test tree, because the claim is about modules that are not tests,
    and this module's own source. `migrations/` is in, deliberately, which is
    why the wider walk is the one asked.

    Read as code, not matched: `WORK_IDENTITY` is named in two module docstrings
    and read by neither, and an `ast` walk sees that difference where a `grep`
    does not.

    **The receiver is read off each file's own imports, not spelled here.** An
    earlier version matched the name `book_columns` literally and said it
    covered "both import shapes", which is an inclusion of two where there are
    three: `import book_columns as bc` then `bc.COPY_STANDING` was invisible,
    and on a name that long the alias is what somebody writes. Third time on
    this branch that an arm was written as a list of the spellings its author
    thought of.

    **What this still does not see, stated as the exclusion**: any reach that
    does not name the module in an `import` of the same file. `getattr`,
    `importlib`, and a rebinding through an assignment are all outside it, and
    each is visible at its own call site in a way an alias is not.
    """
    names: set[str] = set()
    for path in _every_python_file():
        if path == BOOK_COLUMNS or "tests" in path.relative_to(BACKEND).parts:
            continue
        tree = ast.parse(path.read_text())
        receivers = {
            alias.asname or alias.name
            for node in ast.walk(tree)
            if isinstance(node, ast.Import)
            for alias in node.names
            if alias.name == "book_columns"
        }
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Attribute)
                and isinstance(node.value, ast.Name)
                and node.value.id in receivers
            ):
                names.add(node.attr)
            if isinstance(node, ast.ImportFrom) and node.module == "book_columns":
                names |= {alias.name for alias in node.names}
    return names


def _load_book_columns() -> None:
    """Execute `book_columns.py` as a module of its own, so its check runs.

    A fresh module object rather than `importlib.reload`, for `test_folding.py`'s
    reason: a reload would leave the real `book_columns` half initialised in this
    worker when the check raises, and every later test in the process reading a
    module with none of its sets in it.
    """
    spec = importlib.util.spec_from_file_location("book_columns_under_test", BOOK_COLUMNS)
    assert spec is not None and spec.loader is not None
    spec.loader.exec_module(importlib.util.module_from_spec(spec))


def _book_whose_table_has(names: list[str]) -> type:
    """A stand in for `Book` carrying exactly these column names.

    Built here and never mapped, so the real metadata is untouched. Only the
    names are read, so every column is an `Integer`.
    """
    metadata = MetaData()
    table = Table(
        "books",
        metadata,
        *(Column(name, Integer, primary_key=name == "id") for name in names),
    )
    return type("BookStandIn", (), {"__table__": table})


class TestEveryColumnOfBooksIsClassifiedExactlyOnce:
    def test_the_live_partition_covers_the_table_exactly(self):
        """The live pairing, which is what the import time refusal enforces."""
        assert book_columns._misfiled(book_columns.PARTITION, _columns()) == set()

    def test_nothing_is_reported_when_the_cells_partition_the_columns(self):
        """The baseline. Without it every arm below scores a pass it did not
        earn, because a check that reports everything reports these too."""
        cells = [["a", "b"], ["c"]]
        assert book_columns._misfiled(cells, ["a", "b", "c"]) == set()

    def test_a_column_in_no_cell_is_reported(self):
        """The arm that matters: a column added to the schema and to nothing
        else is written by no writer and says nothing."""
        assert book_columns._misfiled([["a", "b"]], ["a", "b", "shelf_mark"]) == {
            "shelf_mark"
        }

    def test_a_name_left_by_a_dropped_column_is_reported(self):
        """The other arm, which a containment check would pass. A cell naming a
        column that is gone is a claim about a write nobody can perform."""
        assert book_columns._misfiled([["a", "b"]], ["a"]) == {"b"}

    def test_a_column_in_two_cells_is_reported(self):
        """The half a symmetric difference cannot see. The union still equals
        the table, and the column is granted whatever the wrong cell grants."""
        assert book_columns._misfiled([["a", "b"], ["b"]], ["a", "b"]) == {"b"}

    def test_a_name_in_two_cells_that_is_not_a_column_is_reported_once(self):
        """Both faults on one name, and the report is a set of names rather
        than a count, so it stays one entry and stays actionable."""
        assert book_columns._misfiled([["a"], ["a"]], []) == {"a"}


class TestTheModuleRefusesToImport:
    def test_it_imports_against_the_real_table(self):
        """The baseline arm. A module that raised whatever it was handed would
        pass the test below and say nothing."""
        _load_book_columns()

    def test_it_refuses_when_a_column_is_classified_nowhere(self, monkeypatch):
        """At import, not at the first write.

        A check at the first write never fires for most of these: a writer that
        skips a column it has never heard of raises nothing and stores nothing,
        so the column is simply never carried by a merge, a copy or an import.
        This one stops the test run of whoever added the column.
        """
        monkeypatch.setattr(
            models, "Book", _book_whose_table_has([*_columns(), "shelf_mark"])
        )
        with pytest.raises(RuntimeError, match="shelf_mark"):
            _load_book_columns()

    def test_it_refuses_when_a_cell_names_a_column_that_is_gone(self, monkeypatch):
        """The symmetric half, through the import rather than the function."""
        monkeypatch.setattr(
            models, "Book", _book_whose_table_has([c for c in _columns() if c != "location"])
        )
        with pytest.raises(RuntimeError, match="location"):
            _load_book_columns()

    def test_it_names_the_column_and_says_what_to_do(self, monkeypatch):
        """A refusal that does not say what to do is one somebody comments out.

        It names the four columns a reader is most likely to think are exempt,
        because "this one is bookkeeping, it needs no home" is the reasoning the
        refusal exists to refuse.
        """
        monkeypatch.setattr(
            models, "Book", _book_whose_table_has([*_columns(), "shelf_mark"])
        )
        with pytest.raises(RuntimeError) as raised:
            _load_book_columns()
        message = str(raised.value)
        assert "shelf_mark" in message
        assert "exactly one" in message
        for name in ("id", "added_at", "deleted_at", "is_private"):
            assert name in message


class TestEachCellIsDerivableFromSomethingThatIsNotItself:
    """Presence is not correctness, and these are the arms that tell them apart.

    A column moved from the cell it belongs in to one beside it leaves the
    partition complete and disjoint, so every arm in the class above stays
    green. Each arm here asks a different source what the cell should hold.
    """

    def test_the_copy_facts_are_exactly_what_the_copy_payload_asks_for(self):
        """`CopyCreate` is the one place a member is asked what this object is,
        where it sits and what it cost, and it is asked precisely because no
        outside record and no other row can answer. A column in one and not the
        other means `routers/books.add_copy` writes something nobody classified,
        or asks for something a merge will not carry."""
        assert set(book_columns.COPY_DETAIL) == set(CopyCreate.model_fields)

    def test_nothing_an_outside_catalogue_asserts_is_filed_outside_the_work(self):
        """`BookMatch` is every scalar a catalogue may assert about a book.

        Containment rather than equality, and in this direction only: a
        catalogue may carry less than the work, but a column it *can* assert
        that this module calls a copy fact or row keeping is a contradiction.

        **The one work column outside `BookMatch` is `isbn`**, and it is outside
        by name rather than by absence: the model carries `isbn13`, because what
        a catalogue answers with is one printing and this row is one copy. The
        equality this arm deliberately does not assert would fail on that alone.
        """
        asserted = set(BookMatch.model_fields) & set(_columns())

        assert asserted <= WORK, f"{sorted(asserted - WORK)} are not work facts"

    def test_every_column_an_enrichment_writes_is_one_the_model_bounds(self):
        """The other direction on the same source, and it is the runtime bound.

        `google_books.merge_into` reads each of these off a `BookMatch` by name,
        `WORK_DETAIL` in its loop and `WORK_COVER` below it, so a column in
        either that the model does not carry raises `AttributeError` on the
        first enrichment. The arm above says a catalogue's columns are work
        facts; this one says the work cells a catalogue writes hold nothing else.
        """
        writable = set(book_columns.WORK_DETAIL) | set(book_columns.WORK_COVER)
        unbounded = sorted(writable - set(BookMatch.model_fields))

        assert unbounded == [], (
            f"{unbounded} are written out of a catalogue match and `BookMatch` "
            "does not carry them, so enrichment raises on the first one it "
            "reaches. A work fact no catalogue can assert belongs in "
            "`WORK_IDENTITY`; a column that is not a work fact belongs in a "
            "cell that is not written from a record."
        )

    def test_the_cover_is_what_the_copy_route_cannot_carry_in_the_constructor(self):
        """`WORK_COVER` is the columns `add_copy` has to write after the insert.

        Every other work fact goes in the `Book(...)` call. This one cannot: a
        cover this app holds is a file named by the new row's id, and that id
        does not exist until the row does, so the route inserts first and then
        calls `covers.duplicate`. That is the cell's stated reason, read back off
        the route rather than off the cell, and it is what closes the border with
        `WORK_DETAIL` in both directions: a cover moved into `WORK_DETAIL` leaves
        this set short, and any other column moved into `WORK_COVER` leaves it
        long.

        `& set(_columns())` drops `copy.tags`, which is a relationship rather
        than a column and is carried by the same post insert write for an
        unrelated reason.

        **The fragility, stated rather than found later**: moving the cover
        handling out of `add_copy` into a helper turns this red even though
        nothing about the columns changed. That is the same exposure
        `_sets_walked_by` carries three arms below, and the answer is the same,
        follow it to the new site rather than deleting the arm.
        """
        import routers.books

        assigned = _assigned_after_the_insert(routers.books, "add_copy", "Book")

        assert assigned & set(_columns()) == set(book_columns.WORK_COVER)

    def test_no_column_a_member_edits_as_a_detail_is_row_keeping_or_a_claim(self):
        """`BookDetailsUpdate` is the ordinary edit form. Nothing on it is about
        the row rather than the book, and nothing on it is a standing claim:
        privacy, ownership and the copy group each have an endpoint of their own
        because each is a different decision from correcting a publisher."""
        kept = set(book_columns.ROW_KEEPING + book_columns.COPY_STANDING)
        edited = set(BookDetailsUpdate.model_fields)

        assert edited & kept == set()

    def test_the_visibility_rule_owns_its_columns(self):
        """A column the privacy rule reads is about the row, never the book.

        All three are nullable or absent from every payload, so nothing else
        here would notice one of them being filed as a work fact, and a merge
        that absorbed one would hand the survivor a losing row's trash marker,
        its privacy or its attribution.

        Read off the compiled predicate rather than off `models.py`'s source,
        which makes it a second instrument: a rule rewritten to read a fourth
        column is followed without anybody editing this.
        """
        reads = {
            node.name
            for node in visitors.iterate(models.visible_to(0))
            if isinstance(node, Column) and node.table is _books_table()
        }

        assert reads, "the visibility predicate reads no column of `books`"
        assert reads <= set(book_columns.ROW_KEEPING)

    def test_a_column_pointing_at_a_user_is_row_keeping(self):
        """Who added a row is not a losing row's to hand over.

        `added_by_user_id` is nullable, is in no payload and is not unique, so
        every other arm here would pass it wherever it was filed; a merge that
        absorbed it would reattribute the survivor to whoever added the row that
        disappeared. Read off the foreign key graph rather than by name, and the
        target is what carries the meaning: `collection_id` is a foreign key too
        and a merge fills it, because which shelf a book is on is a fact about
        the book and who filed it is not.
        """
        pointing_at_a_user = {
            column.key
            for column in _books_table().c
            for key in column.foreign_keys
            if key.column.table.name == models.User.__tablename__
        }

        assert pointing_at_a_user, "no column of `books` points at a user"
        assert pointing_at_a_user <= set(book_columns.ROW_KEEPING)

    def test_every_column_a_merge_may_fill_is_nullable(self):
        """A gap fill writes only where the column is `None`, so a fillable
        column that cannot be null is a line that never runs.

        One direction only, deliberately. Nullable columns are fillable by
        nothing where each refusal is a decision rather than an omission, `isbn`
        and `copy_group` among them, each with the cell docstring saying what it
        would break. Asserting the converse would assert that no such decision
        may be taken, which is the accident the old tuples ran on rather than the
        rule replacing it. No count here: the set is the partition's to state.
        """
        not_null = {c.key for c in _books_table().c if not c.nullable}

        assert set(book_columns.FILLABLE_FROM_ANOTHER_ROW) & not_null == set()

    def test_no_column_a_merge_may_fill_is_uniquely_indexed(self):
        """A unique column cannot be filled from another row by assignment: the
        row it is taken from has to let go first, in its own flush, which is why
        `folding.fold` handles `isbn` ahead of everything else. A second unique
        column added to `FILLABLE_FROM_ANOTHER_ROW` would trip the index on the
        first merge that absorbed it."""
        unique = {
            column.name
            for index in _books_table().indexes
            if index.unique
            for column in index.columns
        }

        assert unique, "no unique index on `books`, so this arm asserts nothing"
        assert set(book_columns.FILLABLE_FROM_ANOTHER_ROW) & unique == set()


class TestTheDoorsAreWhatTheWritersWalk:
    """Asked for, not written out again.

    Identity rather than equality, which is the difference these are for: a
    writer that re-lists the same names at its own call site is equal to the
    module's tuple and is not the module's tuple, and that is precisely the
    arrangement this module replaced.

    **The MARC gap filler has no arm here**, deliberately. It builds a tuple by
    filtering on `WORK_DETAIL` rather than walking a set, so the only relation
    identity could be asserted on is one that holds by construction, and a test
    that cannot fail reads as coverage. Its ground is held by
    `tests/routers/test_imports_marc.py::TestAMatchedBookNeverGainsAnIsbn::test_the_gap_filter_drops_an_isbn_the_create_path_grew`,
    which drives the filter with a tuple the module does not produce, and by
    `tests/test_marc.py::TestEveryColumnTheImporterWritesIsBounded::test_every_column_the_importer_writes_is_a_work_fact`.
    """

    def test_the_merge_absorbs_the_fillable_set(self):
        import folding

        assert any(
            walked is book_columns.FILLABLE_FROM_ANOTHER_ROW
            for walked in _sets_walked_by(folding, "_absorb_fields")
        )

    def test_a_copy_takes_the_work_facts(self):
        import routers.books

        assert any(
            walked is book_columns.WORK_FACTS
            for walked in _sets_walked_by(routers.books, "add_copy")
        )

    def test_google_enrichment_fills_the_work_detail(self):
        import google_books

        assert any(
            walked is book_columns.WORK_DETAIL
            for walked in _sets_walked_by(google_books, "merge_into")
        )

    def test_nothing_outside_the_tests_reaches_past_those_three_names(self):
        """The four inert moves in this module's docstring rest on this arm.

        A move that leaves `WORK_DETAIL`, `WORK_FACTS` and
        `FILLABLE_FROM_ANOTHER_ROW` intact changes nothing any writer does, and
        that holds only while those are the only names read outside the tests. A
        module that started reading `COPY_STANDING` would turn four documented
        inert moves into observable ones with nothing going red; this is what
        goes red instead, which is the difference between a measurement somebody
        took once and a rule the tree can contradict.

        Containment rather than equality, because a reader going away is not a
        hazard and a new name being read is. The non emptiness assertion is what
        stops a scan that found nothing from passing.
        """
        read = _names_read_outside_the_tests()

        assert read, "the scan found no reader of `book_columns` anywhere"
        assert read <= REACHABLE, (
            f"{sorted(read - REACHABLE)} is read by a module that is not a test, "
            "so a column moved between cells can be observed where this module's "
            "docstring says it cannot. Either that reader takes a door, or the "
            "four inert moves recorded there need re-scoring against the suite."
        )
