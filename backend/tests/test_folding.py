"""Folding two Books into one: the child tables it must not forget.

The behaviour of each policy is guarded where that table's own tests live. What
is here is the rule those ten tests cannot state between them: that the set of
tables a merge carries is the set of children `books` has, checked against the
schema rather than against a list somebody remembered to extend.

Before it, an eleventh child table was cascade deleted on every merge with
nothing red, and what stood in for a guard was seven test docstrings in seven
files each independently warning about the same thing.
"""

import ast
import importlib.util
import logging
from pathlib import Path

import pytest
from sqlalchemy import Column, ForeignKey, Integer, MetaData, Table

import folding
import models
from database import Base
from models import children_of_books
from schemas import MAX_CLASSIFICATIONS_PER_BOOK
from tests.test_shelf import _READING_METHODS

FOLDING = Path(__file__).resolve().parent.parent / "folding.py"


def _load_folding() -> None:
    """Execute `folding.py` as a module of its own, so its import time check runs.

    A fresh module object rather than `importlib.reload`, which would leave the
    real `folding` half initialised in this worker when the check raises, and
    every later test in the process reading a module with no `fold` in it.
    """
    spec = importlib.util.spec_from_file_location("folding_under_test", FOLDING)
    assert spec is not None and spec.loader is not None
    spec.loader.exec_module(importlib.util.module_from_spec(spec))


#: Narrowing calls. A chain is bounded by what one of these is **handed**, never
#: by a token appearing somewhere in it.
_NARROWING = frozenset({"filter", "where"})
#
# **`filter_by` is deliberately absent and was in here once.** The bound is read
# off the values a narrowing call is handed, and `filter_by`'s column is the
# keyword's **name** rather than any value, so no `filter_by` spelling could
# ever discharge it: `filter_by(book_id=fold.keeper.id)` was reported while the
# set advertised that it would be honoured. Listing a spelling a rule cannot
# honour is how the next reader concludes the rule is broken rather than strict.
# It is still reported, and `EVASIONS` now says so.


def _read_roots(source: str) -> list[tuple[ast.Call, ast.expr]]:
    """The innermost call of every chain in this module that could reach a table.

    Three ways in, and the second exists because the first is not enough.

    **Any call on the session.** `_READING_METHODS` is derived from `Query` and
    `Select` and so contains neither `execute` nor `scalars`, measured: the 2.0
    spellings `db.scalars(select(model))` and `db.execute(update(model))` are
    invisible to a rule keyed on that set, and the 2.0 style is live in this
    backend. The session is the only door to the database from this module, so
    every call through it is a root whatever it is called.

    **Any call whose method is in `_READING_METHODS`**, which catches a read
    that never touches the session on its way to being built:
    `transfer.table.select()` reads a whole table off a live `Table` object this
    module holds ten of.

    **Any call on a name this module imported from SQLAlchemy**, which catches
    the bare `select(model)` and `text(...)` spellings. Derived from the
    module's own imports rather than listed, so a builder imported tomorrow is a
    root the day it appears.

    Each answer is the root and the whole chain built on it: the root is what
    names the table, and the narrowing that bounds it is a later link.
    """
    tree = ast.parse(source)
    imported = {
        alias.asname or alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and (node.module or "").split(".")[0] == "sqlalchemy"
        for alias in node.names
    }
    parents = {
        id(child): node for node in ast.walk(tree) for child in ast.iter_child_nodes(node)
    }

    def outermost(node: ast.expr) -> ast.expr:
        while True:
            parent = parents.get(id(node))
            built_on_it = (isinstance(parent, ast.Attribute) and parent.value is node) or (
                isinstance(parent, ast.Call) and parent.func is node
            )
            if not built_on_it:
                return node
            assert isinstance(parent, ast.expr)
            node = parent

    def candidate(node: ast.Call) -> bool:
        func = node.func
        if isinstance(func, ast.Name):
            return func.id in imported
        return isinstance(func, ast.Attribute) and (
            func.attr in _READING_METHODS
            or func.attr in imported
            or _on_the_session(node)
        )

    chains: dict[int, ast.expr] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and candidate(node):
            chain = outermost(node)
            chains[id(chain)] = chain
    return sorted(
        ((_root_of(chain), chain) for chain in chains.values()),
        key=lambda pair: pair[0].lineno,
    )


def _root_of(chain: ast.expr) -> ast.Call:
    """Descend a chain to the call that names the table."""
    node = chain
    while (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and isinstance(node.func.value, ast.Call)
    ):
        node = node.func.value
    assert isinstance(node, ast.Call)
    return node


def _on_the_session(call: ast.Call) -> bool:
    """Whether this call is made on the request's `Session`.

    Read off the receiver's last segment, which is `db` at every call site in
    this backend. A session spelled anything else falls out of the session arm
    and into `NOT_A_DATABASE_READ`, where it fails until somebody writes down
    what it is: wrong in the safe direction.
    """
    return (
        isinstance(call.func, ast.Attribute)
        and ast.unparse(call.func.value).rsplit(".", 1)[-1] == "db"
    )


def _reads_nothing(root: ast.Call) -> bool:
    """Session calls that cannot name a table, and why each cannot.

    **No arguments at all**: `flush`, `commit` and `rollback` take none, and a
    call that names nothing can read nothing. Structural rather than a list of
    method names, so a fourth no argument session call is covered the day it
    appears.

    **`delete` with one positional argument**: `Session.delete(obj)` takes a row
    already in hand. It is here because `Query.delete()` shares the name and
    `_READING_METHODS` is derived, and it is keyed on the method because
    `execute(stmt)` has the same shape and does read. `db.query(...).delete()`
    is not this: that chain is rooted at the `query`, which has to be bounded
    like any other.
    """
    if not _on_the_session(root):
        return False
    if not root.args and not root.keywords:
        return True
    assert isinstance(root.func, ast.Attribute)
    return root.func.attr == "delete" and len(root.args) == 1 and not root.keywords


def _subjects(root: ast.Call) -> set[str]:
    """The names the root call hands to the database, which a bound must be on.

    `db.query(model)` is bounded by a clause on `model` and by nothing else. A
    clause on some other entity narrows another table and leaves this one whole,
    which is one of the evasions below.
    """
    return {
        node.id
        for argument in [*root.args, *(keyword.value for keyword in root.keywords)]
        for node in ast.walk(argument)
        if isinstance(node, ast.Name)
    }


def _links(chain: ast.expr) -> list[ast.Call]:
    """The calls of one chain, outermost inward.

    **Never a call inside an argument, and that makes the 2.0 path a ban rather
    than a bound.** `db.scalars(select(model).where(...))` builds its statement
    inside the session call's argument, so the `where` is not a link here and the
    read is reported whatever it carries. That is the intended behaviour and is
    stated here because the obvious repair is wrong: descending into the root's
    arguments would re-admit `scalars(select(model))`,
    `execute(update(model).values(...))`, `execute(text(...))` and
    `execute(transfer.table.select())`, which is four of this file's fixtures and
    the whole of the second defect both critic seats reported.

    A bounded 2.0 read is refused too, and
    `test_a_bounded_two_zero_read_is_refused_as_well` is what says so, so nobody
    meets a red on one and reads it as a gap.
    """
    found = []
    node = chain
    while isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
        found.append(node)
        node = node.func.value
    return found


def _bounds_to_the_books(node: ast.expr, subjects: set[str], carry: str) -> bool:
    """Whether this predicate confines a read to Books somebody already resolved.

    Two forms and no others: `<subject>.book_id.in_(<carry>....)` and
    `<subject>.book_id == <carry>....`. **Stated as what is allowed rather than
    what is refused**, because the refusals are open: `notin_` is a one character
    typo away from the first and inverts it, `isnot(None)` matches every row, and
    a column named in an `order_by` narrows nothing at all. A third safe form
    added tomorrow fails here and is somebody's decision, which is the direction
    a guard may be wrong in.

    **Both halves are checked, the column and the value it is handed.** Checking
    the column alone made widening an existing bound free: measured on the
    committed source, `model.book_id.in_(range(1, 10 ** 9))` left every shape arm
    green and `READ_ROOTS` unmoved at 11 while every note, quote and progress row
    in the Library was repointed onto the keeper. The count restores "somebody
    must look at a new read"; this restores "somebody must look at a changed
    bound", which is what the `BOOK_OWNED_READERS` entries did by pinning the
    argument verbatim in a positional fragment.

    `carry` is the name the read's own session was reached through, so the value
    has to come off the Books this fold is holding rather than out of anywhere
    else. Derived from the statement rather than written down: a bound computed
    into a local is refused too, which is strict and is the safe direction.
    """
    if (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "in_"
        and len(node.args) == 1
    ):
        return _is_the_book_column(node.func.value, subjects) and _off_the_carry(
            node.args[0], carry
        )
    if isinstance(node, ast.Compare) and len(node.ops) == 1 and isinstance(node.ops[0], ast.Eq):
        return _is_the_book_column(node.left, subjects) and _off_the_carry(
            node.comparators[0], carry
        )
    return False


def _is_the_book_column(node: ast.expr, subjects: set[str]) -> bool:
    return (
        isinstance(node, ast.Attribute)
        and node.attr == "book_id"
        and isinstance(node.value, ast.Name)
        and node.value.id in subjects
    )


def _off_the_carry(node: ast.expr, carry: str) -> bool:
    """Whether this value is read off the Books the fold is holding.

    An attribute chain and nothing else: `fold.loser_ids` and `fold.keeper.id`
    are the four live bounds, a literal range is not, and neither is a name some
    line above assigned.
    """
    if not isinstance(node, ast.Attribute):
        return False
    while isinstance(node, ast.Attribute):
        node = node.value
    return isinstance(node, ast.Name) and node.id == carry


def _carry_of(root: ast.Call) -> str | None:
    """The name this read reached its `Session` through, or None off the session.

    `fold.db.query(...)` is held by `fold`, which is where a legitimate bound
    comes from. A read that never touches the session has no fold to be bounded
    by and is refused: that is `transfer.table.select()`.
    """
    if not _on_the_session(root):
        return None
    assert isinstance(root.func, ast.Attribute)
    node: ast.expr = root.func.value
    while isinstance(node, ast.Attribute):
        node = node.value
    return node.id if isinstance(node, ast.Name) else None


def _unbounded_reads(source: str) -> list[int]:
    """Reads here that are not confined to the Books being folded.

    **This module is invisible to the fourth pass in `tests/test_shelf.py`**,
    which finds a read of a Book owned table by the entity's name appearing
    inside a reading call. Every read here is built on the model its transfer
    was constructed with, so the name is in an argument and that pass sees
    nothing where it used to see three allowlisted statements.

    **What it sees is the argument a narrowing call is handed, never a token in
    the chain.** The first version of this rule asked whether `"book_id"`
    appeared anywhere in the chain's source, and eight spellings satisfied it
    while reading every row of a child table for every Book in the Library: the
    filter dropped with an `order_by(model.book_id)` left beside it, `notin_`,
    `isnot(None)`, a clause on another entity's `book_id`, and `order_by` handed
    the column name as a string. Each is a fixture below.

    **What this does not do is make anybody look.** The three
    `BOOK_OWNED_READERS` entries it replaced were enforced by a count and a
    positional fragment, so a fourth read appearing at all, in any spelling,
    failed until a person wrote a sentence about it. A shape rule refuses a
    shape and asks nobody anything, so `READ_ROOTS` below carries the count and
    `NOT_A_DATABASE_READ` carries the sentences.
    """
    offences = []
    for root, chain in _read_roots(source):
        if _reads_nothing(root):
            continue
        if not _on_the_session(root) and ast.unparse(root) in dict(NOT_A_DATABASE_READ):
            continue
        subjects = _subjects(root)
        carry = _carry_of(root)
        if carry is None or not any(
            _bounds_to_the_books(argument, subjects, carry)
            for link in _links(chain)
            if isinstance(link.func, ast.Attribute) and link.func.attr in _NARROWING
            for argument in [*link.args, *(k.value for k in link.keywords)]
        ):
            offences.append(root.lineno)
    return sorted(set(offences))


#: How many calls in `folding.py` could reach a table, bounded or not.
#:
#: **The half of the old arrangement a shape rule does not replace.** The three
#: `BOOK_OWNED_READERS` entries this module's reads used to carry were enforced
#: by a count and a positional fragment: a fourth read appearing at all, in any
#: spelling, failed that pass until a person described it. `_unbounded_reads`
#: refuses a shape and asks nobody to look, so the looking is this number's job.
#:
#: Eleven: four queries, two `Session.delete`s of a row in hand, three `flush`es
#: and the two plain Python calls in `NOT_A_DATABASE_READ`.
READ_ROOTS = 11

#: Calls the derived reading set matches that touch no table, and why.
#:
#: Keyed on the call as `ast.unparse` writes it and checked by **equality** in
#: line order, which is a rung above the `in` test `BOOK_OWNED_READERS` uses:
#: an entry cannot drift onto a neighbouring statement that happens to contain
#: its fragment.
#:
#: Both are here because `_READING_METHODS` is derived from `Query` and `Select`
#: and is deliberately over broad. Neither is a session call.
NOT_A_DATABASE_READ = [
    (
        "kept.get(token)",
        "a dict lookup. `Query.get` shares the name; this is the local map of "
        "the keeper's own rows, built two lines above out of a relationship on "
        "the Book the route resolved.",
    ),
    (
        "{loan.id: loan for loan in [*on_keeper, *moved]}.values()",
        "deduplicates two lists of Loan objects already in hand. `Query.values` "
        "shares the name; this reads a dict comprehension.",
    ),
]


def _extra_child() -> Table:
    """A child of `books` that no policy names. Built here, never mapped."""
    metadata = MetaData()
    Table("books", metadata, Column("id", Integer, primary_key=True))
    return Table(
        "shelf_marks",
        metadata,
        Column("id", Integer, primary_key=True),
        Column("book_id", Integer, ForeignKey("books.id")),
    )


class TestEveryChildOfBooksHasAPolicy:
    def test_the_declared_set_is_exactly_the_children_of_books(self):
        """The live pairing, which is what the import time refusal enforces."""
        declared = {transfer.table for transfer in folding.TRANSFERS}
        assert declared == children_of_books(Base.metadata)

    def test_a_child_with_no_policy_is_reported(self):
        """The arm that matters: a table added to the schema and to nothing
        else loses every row it holds on the first merge."""
        extra = _extra_child()
        undeclared = folding._undeclared(
            folding.TRANSFERS,
            {transfer.table for transfer in folding.TRANSFERS} | {extra},
        )
        assert undeclared == {extra}

    def test_a_policy_left_behind_by_a_removed_table_is_reported(self):
        """The other arm, which a containment check would pass. A transfer for a
        table that is gone is a claim about a merge nobody can read."""
        remaining = {transfer.table for transfer in folding.TRANSFERS}
        dropped = folding.TRANSFERS[0].table
        undeclared = folding._undeclared(folding.TRANSFERS, remaining - {dropped})
        assert undeclared == {dropped}

    def test_nothing_is_reported_when_the_two_agree(self):
        """The baseline. Without it every arm above scores a pass it did not
        earn, because a check that reports everything reports these too."""
        assert (
            folding._undeclared(
                folding.TRANSFERS, {transfer.table for transfer in folding.TRANSFERS}
            )
            == set()
        )


class TestTheModuleRefusesToImport:
    def test_it_imports_against_the_real_schema(self):
        """The baseline arm. A module that raised whatever it was handed would
        pass the test below and say nothing."""
        _load_folding()

    def test_it_refuses_when_a_child_has_no_policy(self, monkeypatch):
        """At import, not at the first merge.

        The failure being replaced is the silent destruction of Members' rows. A
        check at the first merge fires in production, on somebody's library,
        after the deploy; this one stops the test run of whoever added the
        table.
        """
        extra = _extra_child()
        monkeypatch.setattr(
            models,
            "children_of_books",
            lambda metadata: children_of_books(metadata) | {extra},
        )
        with pytest.raises(RuntimeError, match="shelf_marks"):
            _load_folding()

    def test_it_names_the_table_and_says_what_the_cascade_does(self, monkeypatch):
        """A refusal that does not say what to do is one somebody comments out."""
        extra = _extra_child()
        monkeypatch.setattr(
            models,
            "children_of_books",
            lambda metadata: children_of_books(metadata) | {extra},
        )
        with pytest.raises(RuntimeError) as raised:
            _load_folding()
        message = str(raised.value)
        assert "shelf_marks" in message
        assert "cascade deleted" in message
        assert "TRANSFERS" in message


class TestTheCeilingDropIsLogged:
    def test_the_overflow_names_the_table_it_came_from(
        self, client, admin, db, caplog
    ):
        """The drop is a loss: nothing regenerates a heading a Member's
        catalogue supplied. One log site serves three tables now, so the line
        carries the table rather than a sentence written per site.
        """
        keeper = client.post(
            "/api/books",
            json={
                "title": "Docker",
                "classifications": [
                    {"scheme": "ddc", "number": f"{index}00"}
                    for index in range(1, MAX_CLASSIFICATIONS_PER_BOOK + 1)
                ],
            },
            headers=admin["headers"],
        ).json()
        loser = client.post(
            "/api/books",
            json={"title": "Docker", "classifications": [{"scheme": "ddc", "number": "990"}]},
            headers=admin["headers"],
        ).json()

        with caplog.at_level(logging.INFO, logger="endpaper.folding"):
            client.post(
                "/api/books/merge",
                json={"book_ids": [keeper["id"], loser["id"]], "keep_id": keeper["id"]},
                headers=admin["headers"],
            )

        dropped = [record.getMessage() for record in caplog.records]
        assert any("classifications ceiling" in line and "990" in line for line in dropped), dropped


#: Reads that must be reported. Every one of them repoints or exposes every row
#: of a child table, for every Book in the Library.
#:
#: **Chosen by the two critic seats rather than by this rule's author**, which
#: is why they are here: the negative fixture this file shipped with planted
#: `model.id.in_(ids)`, a chain containing no `book_id` at all, so the mutation
#: picked the case the rule already covered and came back clean.
EVASIONS = {
    "the filter dropped, an order_by left beside it": (
        "rows = fold.db.query(model).order_by(model.book_id).all()\n"
    ),
    "the same, inside a wholesale move": (
        "for row in fold.db.query(model).order_by(model.book_id).all():\n"
        "    row.book_id = fold.keeper.id\n"
    ),
    "the same, on the loans": (
        "moved = fold.db.query(Loan).order_by(Loan.book_id).all()\n"
    ),
    "a negated membership test": (
        "rows = fold.db.query(model).filter(model.book_id.notin_(fold.loser_ids)).all()\n"
    ),
    "a null test": (
        "rows = fold.db.query(model).filter(model.book_id.isnot(None)).all()\n"
    ),
    "the book column of a different table": (
        "rows = fold.db.query(Note).filter(Quote.book_id.in_(ids)).all()\n"
    ),
    "the column handed to order_by as a string": (
        "rows = fold.db.query(model).order_by('book_id').all()\n"
    ),
    "a filter on the row id": (
        "rows = fold.db.query(model).filter(model.id.in_(ids)).all()\n"
    ),
    "the 2.0 scalars spelling": (
        "from sqlalchemy import select\n\nrows = fold.db.scalars(select(model)).all()\n"
    ),
    "the 2.0 execute spelling": (
        "from sqlalchemy import update\n\n"
        "fold.db.execute(update(model).values(book_id=fold.keeper.id))\n"
    ),
    "raw SQL through the session": (
        "from sqlalchemy import text\n\n"
        "fold.db.execute(text('UPDATE notes SET book_id = 1'))\n"
    ),
    "a Table read straight off the registry": (
        "rows = fold.db.execute(transfer.table.select()).all()\n"
    ),
    "the bound widened to every Book there is": (
        "rows = fold.db.query(model).filter(model.book_id.in_(range(1, 10 ** 9))).all()\n"
    ),
    "the bound taken from a local instead of the fold": (
        "rows = fold.db.query(model).filter(model.book_id.in_(ids)).all()\n"
    ),
    "filter_by, whose column is a keyword's name and not a value": (
        "rows = fold.db.query(model).filter_by(book_id=fold.keeper.id).all()\n"
    ),
}

#: Reads that must **not** be reported, so the rule cannot be satisfied by
#: reporting everything. The first three are the shapes `folding.py` ships.
NOT_OFFENCES = {
    "a wholesale move": (
        "for row in fold.db.query(model).filter(model.book_id.in_(fold.loser_ids)).all():\n"
        "    row.book_id = fold.keeper.id\n"
    ),
    "a deduplicated move": (
        "rows = (fold.db.query(model)\n"
        "        .filter(model.book_id.in_(fold.loser_ids))\n"
        "        .order_by(model.id).all())\n"
    ),
    "the keeper's own loans": (
        "on_keeper = fold.db.query(Loan).filter(Loan.book_id == fold.keeper.id).all()\n"
    ),
    "deleting a row already in hand": "fold.db.delete(row)\n",
    "a flush": "db.flush()\n",
}


class TestEveryReadIsBoundedToTheBooksBeingFolded:
    def test_no_read_here_looks_past_the_Books_in_hand(self):
        """A merge may read a child table because the ids came off Books the
        route resolved through the Shelf. Nothing here may read one otherwise.
        """
        assert _unbounded_reads(FOLDING.read_text()) == []

    @pytest.mark.parametrize("spelling", sorted(EVASIONS), ids=sorted(EVASIONS))
    def test_every_evasion_is_reported(self, spelling):
        assert _unbounded_reads(EVASIONS[spelling]) != []

    @pytest.mark.parametrize("spelling", sorted(NOT_OFFENCES), ids=sorted(NOT_OFFENCES))
    def test_a_bounded_read_is_not_reported(self, spelling):
        assert _unbounded_reads(NOT_OFFENCES[spelling]) == []

    def test_a_query_delete_is_not_the_session_delete(self):
        """The exemption is keyed on the session, not on the word. A `delete`
        terminating a chain is that chain's read and is bounded like any other.
        """
        assert _unbounded_reads("fold.db.query(model).delete()\n") == [1]

    def test_a_bounded_two_zero_read_is_refused_as_well(self):
        """The 2.0 path is a **ban**, not a bound, and this is what says so.

        A statement built inside the session call's argument is refused whatever
        it carries, because `_links` does not descend into an argument. Somebody
        meeting a red on a correctly bounded 2.0 read has the widening as the
        obvious repair, and the widening re-admits four of the fixtures above.
        """
        source = (
            "from sqlalchemy import select\n\n"
            "rows = fold.db.scalars("
            "select(model).where(model.book_id.in_(fold.loser_ids))).all()\n"
        )

        assert _unbounded_reads(source) != []

    def test_a_session_call_with_an_argument_is_not_a_flush(self):
        """The other edge of the same exemption: what makes a `flush` safe is
        that it names nothing, so anything handed an argument is a read."""
        assert _unbounded_reads("rows = fold.db.execute(statement)\n") == [1]

    def test_the_number_of_reads_here_is_the_pinned_one(self):
        """The half a shape rule cannot do: make somebody look.

        A read added in any spelling moves this number, and the person who
        added it has to say which arm it belongs in. That is what the three
        `BOOK_OWNED_READERS` entries this replaced did with a count and a
        positional fragment.
        """
        roots = _read_roots(FOLDING.read_text())
        assert len(roots) == READ_ROOTS, (
            "a call that could reach a table was added to or removed from "
            "folding.py. Confirm it is bounded to the Books being folded, then "
            f"move this number: {[ast.unparse(root) for root, _ in roots]}"
        )

    def test_every_matched_call_off_the_session_is_described(self):
        """The derived reading set is over broad on purpose, so the calls it
        matches that touch no table are written down with a reason each.
        """
        off_session = [
            ast.unparse(root)
            for root, _ in _read_roots(FOLDING.read_text())
            if not _on_the_session(root)
        ]
        assert off_session == [call for call, _ in NOT_A_DATABASE_READ]
