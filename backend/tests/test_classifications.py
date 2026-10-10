"""What may be written to `classifications`, in what order, and what heals.

The ceiling and the drop rule are exercised through the routes in
`tests/routers/test_books_classifications.py`, which is where a member meets
them. What is pinned here is the module's own three rules: how a null kind is
read, which heading a full book loses, and the one path by which a row written
before the kind column existed is ever corrected.
"""

import ast
import pathlib
import re
import sys
import textwrap
from collections.abc import Iterable, Iterator, Mapping
from typing import Any
from xml.etree import ElementTree

import pytest
from sqlalchemy import insert
from sqlalchemy.exc import IntegrityError

import decoders
import marc_fields
import metadata
import targets
from catalogue import Heading
from classifications import KIND_ORDER, add_headings, bounded_headings, kind_of
from enums import ClassificationScheme, HeadingKind
from models import Book, Classification
from schemas import MAX_CLASSIFICATIONS_PER_BOOK
from schemas.classification import ClassificationIn
from tests.test_house_rules import _is_vendored


class TestReadingAKindOffARow:
    """`kind_of` is the only interpreter of the null, so it carries the fallback."""

    def test_a_row_no_record_ever_declared_for_is_a_subject(self):
        assert kind_of(None) is HeadingKind.SUBJECT

    @pytest.mark.parametrize("kind", list(HeadingKind))
    def test_every_member_reads_back_as_itself(self, kind):
        assert kind_of(kind) is kind

    def test_every_kind_has_a_rank(self):
        """`KIND_ORDER` is indexed rather than `get`, so a member added without
        a rank is a `KeyError` on the next lookup rather than a silent tie."""
        assert set(KIND_ORDER) == set(HeadingKind)


#: Every kind a writer may store: the enum, less the member that is the null.
#:
#: **Derived rather than listed**, and it is the derivation that is the point:
#: `models._enum_check` builds `ck_classifications_kind` off the same rule, so a
#: member added to `HeadingKind` with no revision behind it is refused by the
#: database and red here, rather than invisible to a list of literals.
_STORABLE = [kind for kind in HeadingKind if kind is not HeadingKind.SUBJECT]


class TestASubjectIsNeverAValueTheColumnHolds:
    """A subject is the null, and the two enforcements of that.

    Why a stored `subject` would be wrong is `enums.HeadingKind`'s argument.
    What is pinned here is that neither route can store one: the client facing
    one, which normalises, and the database, which refuses.
    """

    def test_a_client_posting_subject_gets_the_null_it_means(self):
        assert (
            ClassificationIn(scheme=ClassificationScheme.GND, number="4139307-7",
                             kind=HeadingKind.SUBJECT).kind
            is None
        )

    def test_every_other_kind_is_left_alone(self):
        """Anti vacuity: a validator returning None for everything would pass
        the test above and throw the feature away."""
        for kind in _STORABLE:
            assert (
                ClassificationIn(
                    scheme=ClassificationScheme.GND, number="4139307-7", kind=kind
                ).kind
                is kind
            )

    @pytest.mark.parametrize("stored", ["subject", "pwned", "SUBJECT", ""])
    def test_the_database_refuses_what_no_writer_should_send(self, db, stored):
        """`ck_classifications_kind`, against the route that has no validator.

        `backup.restore` inserts through Core, where neither a Pydantic model
        nor a `@validates` hook fires, so an archive decides this value. Without
        the constraint one such row raises inside `ClassificationOut`,
        `PublicClassificationOut` and `HeadingFacetOut` alike, which 500s the
        member listing, the facet endpoint and the unauthenticated public
        catalogue, for good. This is `b8e2f4c7a913`'s failure on a new column.
        """
        book = Book(title="Praxiswissen Docker")
        db.add(book)
        db.flush()

        with pytest.raises(IntegrityError):
            db.execute(
                insert(Classification).values(
                    book_id=book.id,
                    scheme=ClassificationScheme.GND,
                    number="4139307-7",
                    sort_key="4139307-7",
                    kind=stored,
                )
            )
        db.rollback()

    @pytest.mark.parametrize("stored", [*_STORABLE, None])
    def test_the_database_accepts_what_a_writer_does_send(self, db, stored):
        """The other side, so the constraint is not simply refusing everything,
        and the arm that asks the **migrated** database about a kind the enum
        offers. A member added to `HeadingKind` fails here until a revision
        widens the constraint to match `models._enum_check`'s text."""
        book = Book(title="Praxiswissen Docker")
        db.add(book)
        db.flush()
        db.execute(
            insert(Classification).values(
                book_id=book.id,
                scheme=ClassificationScheme.GND,
                number="4139307-7",
                sort_key="4139307-7",
                kind=stored,
            )
        )

        assert db.query(Classification).count() == 1


class TestWhichHeadingAFullBookKeeps:
    """The kind outranks the scheme, which is what stops a disc winning."""

    def test_a_carrier_is_dropped_before_a_subject_from_any_scheme(self):
        """The case the ordering was changed for. A GND carrier used to sort
        ahead of an LCSH subject on the strength of `SCHEME_ORDER` alone, so a
        full book kept the disc and lost the heading."""
        entries = [
            Heading(ClassificationScheme.GND, "4139307-7", "CD-ROM", HeadingKind.CARRIER),
        ] + [
            Heading(ClassificationScheme.LCSH, f"Treasure troves {index}")
            for index in range(MAX_CLASSIFICATIONS_PER_BOOK)
        ]

        kept = bounded_headings(entries)

        assert len(kept) == MAX_CLASSIFICATIONS_PER_BOOK
        assert "4139307-7" not in {heading.number for heading in kept}

    def test_a_content_type_is_kept_ahead_of_a_carrier(self):
        entries = [
            Heading(ClassificationScheme.GND, "4139307-7", "CD-ROM", HeadingKind.CARRIER),
            Heading(
                ClassificationScheme.GND,
                "1071854844",
                "Fiktionale Darstellung",
                HeadingKind.CONTENT,
            ),
        ]

        assert [heading.number for heading in bounded_headings(entries)] == [
            "1071854844",
            "4139307-7",
        ]

    def test_a_content_type_survives_a_book_full_of_subject_headings(self):
        """The heading `#162` names as the reason not to refuse the content
        vocabulary, and the case a rank of its own would have lost.

        `CONTENT` ties with `SUBJECT` rather than sitting between it and
        `CARRIER`, so a content type falls through to `SCHEME_ORDER`, where GND
        already outranked LCSH. Given its own rank it would be dropped before
        every Library of Congress subject, which is a heading the ticket
        protects being lost by the change that was meant to protect it.
        """
        entries = [
            Heading(
                ClassificationScheme.GND,
                "1071854844",
                "Fiktionale Darstellung",
                HeadingKind.CONTENT,
            )
        ] + [
            Heading(ClassificationScheme.LCSH, f"Treasure troves {index}")
            for index in range(MAX_CLASSIFICATIONS_PER_BOOK)
        ]

        kept = {heading.number for heading in bounded_headings(entries)}

        assert "1071854844" in kept

    def test_the_scheme_still_decides_within_one_kind(self):
        """The old rule is unchanged where the kind does not separate two
        entries, which is every heading a record does not mark."""
        entries = [
            Heading(ClassificationScheme.LCSH, "Treasure troves"),
            Heading(ClassificationScheme.DDC, "004"),
        ]

        assert [heading.scheme for heading in bounded_headings(entries)] == [
            ClassificationScheme.DDC,
            ClassificationScheme.LCSH,
        ]

    def test_a_declared_carrier_sorts_below_an_undeclared_heading(self):
        """Two headings under one scheme, separated by the kind alone.

        **This does not pin where a null sorts**, and an earlier version of this
        docstring claimed it did. The carrier is the only kind ranked below any
        other, so the assertion holds whatever a null reads as; what pins that
        is `kind_of(None) is HeadingKind.SUBJECT` above. What this separates is a
        declared carrier from an undeclared heading, with `SCHEME_ORDER` held
        constant so it cannot be the thing deciding.
        """
        entries = [
            Heading(ClassificationScheme.GND, "4139307-7", "CD-ROM", HeadingKind.CARRIER),
            Heading(ClassificationScheme.GND, "4026894-9", "Informatik"),
        ]

        assert [heading.number for heading in bounded_headings(entries)] == [
            "4026894-9",
            "4139307-7",
        ]


class TestCorrectingAHeadingWrittenBeforeTheKindExisted:
    """The only route by which anything already stored is ever put right.

    No migration can do it: a stored row does not record the `$2` it came from,
    and the two vocabularies do not enumerate, which the revision
    `a1e7c93b60df` measures. So the record that declares is the only source of
    the answer, and this is what reads it.
    """

    def _book(self, db):
        book = Book(title="Praxiswissen Docker")
        db.add(book)
        db.flush()
        return book

    def test_a_declared_kind_fills_in_the_null_a_stored_row_carries(self, db):
        book = self._book(db)
        db.add(
            Classification(
                book=book,
                scheme=ClassificationScheme.GND,
                number="4139307-7",
                label="CD-ROM",
            )
        )
        db.flush()

        changed = add_headings(
            book,
            bounded_headings(
                [
                    Heading(
                        ClassificationScheme.GND,
                        "4139307-7",
                        "CD-ROM",
                        HeadingKind.CARRIER,
                    )
                ]
            ),
            db,
        )
        db.flush()

        assert changed == ["4139307-7"]
        assert book.classifications[0].kind == HeadingKind.CARRIER
        assert len(book.classifications) == 1

    def test_the_correction_counts_as_a_change_so_the_session_is_committed(
        self, db
    ):
        """`apply_enrichment` commits only `if updated:` and `get_db` closes
        without committing, so a fill-in this did not report would be rolled
        back and the row would stay wrong with nothing to see. The same reason
        a filled in caption is reported."""
        book = self._book(db)
        db.add(
            Classification(
                book=book,
                scheme=ClassificationScheme.GND,
                number="1071854844",
                label="Fiktionale Darstellung",
            )
        )
        db.flush()

        assert add_headings(
            book,
            bounded_headings(
                [
                    Heading(
                        ClassificationScheme.GND,
                        "1071854844",
                        "Fiktionale Darstellung",
                        HeadingKind.CONTENT,
                    )
                ]
            ),
            db,
        ) == ["1071854844"]

    def test_a_stored_kind_is_never_overwritten(self, db):
        """A heading already stored came from a catalogue too, and the last
        writer is not the better one. The same rule the caption obeys."""
        book = self._book(db)
        db.add(
            Classification(
                book=book,
                scheme=ClassificationScheme.GND,
                number="4139307-7",
                label="CD-ROM",
                kind=HeadingKind.CARRIER,
            )
        )
        db.flush()

        changed = add_headings(
            book,
            bounded_headings(
                [
                    Heading(
                        ClassificationScheme.GND,
                        "4139307-7",
                        "CD-ROM",
                        HeadingKind.CONTENT,
                    )
                ]
            ),
            db,
        )
        db.flush()

        assert changed == []
        assert book.classifications[0].kind == HeadingKind.CARRIER

    def test_the_correction_deposits_no_second_row(self, db):
        """The whole reason the kind is a column and not two more
        `ClassificationScheme` members. Under new members the pair
        `uq_classifications_book_scheme_number` is on would have changed, so
        this book would carry the concept twice, once right and once wrong."""
        book = self._book(db)
        db.add(
            Classification(
                book=book,
                scheme=ClassificationScheme.GND,
                number="4139307-7",
                label="CD-ROM",
            )
        )
        db.flush()

        add_headings(
            book,
            bounded_headings(
                [
                    Heading(
                        ClassificationScheme.GND,
                        "4139307-7",
                        "CD-ROM",
                        HeadingKind.CARRIER,
                    )
                ]
            ),
            db,
        )
        db.flush()

        assert (
            db.query(Classification).filter(Classification.book_id == book.id).count()
            == 1
        )


#: `backend/`, whose modules the derivation below walks.
BACKEND = pathlib.Path(__file__).resolve().parent.parent

#: Directories under `backend/` the walk does not read, because they are this
#: application's own and are still not source a catalogue reaches.
#:
#: `tests` holds fixtures that construct a `Heading` to arrange a case, which is
#: not a source building one. `migrations` is a historical record: a revision
#: describes the data as it was on the day it ran and is not a code path any
#: catalogue reaches.
_NOT_THIS_APP = frozenset({"tests", "migrations"})

#: English for the small numbers this repository's prose spells out.
_NUMERALS = {
    "two": 2, "three": 3, "four": 4, "five": 5, "six": 6,
    "seven": 7, "eight": 8, "nine": 9, "ten": 10, "eleven": 11, "twelve": 12,
}


def _catalogues_stated_in(prose: str) -> int | None:
    """The count a sentence spells out, or None where it no longer says.

    **Whitespace is collapsed before matching, because the sentence is wrapped
    prose and the wrap moves.** Re-flowing the paragraph put the newline between
    the number and its noun and the guard went red on a docstring that said
    exactly the right thing. A guard nobody can re-wrap around is one somebody
    eventually deletes rather than fixes.
    """
    found = re.search(r"concatenated up to (\w+) catalogues", " ".join(prose.split()))
    return _NUMERALS.get(found.group(1)) if found else None


def _is_this_app(parts: tuple[str, ...], root: pathlib.Path = BACKEND) -> bool:
    """Whether a path under `backend/` is this application's own source.

    **`root` is the tree the parts are relative to**, and it is here so that
    `_modules` can be driven against a constructed tree by the diagonal in
    `test_house_rules.py`. Asked with the parts of one tree and the root of
    another, this would answer about neither: the predicate has to move with
    the walk that calls it.

    **What is not ours is `test_house_rules._is_vendored`**, which is where the
    incident this used to recount is written down: this file named `.venv` and
    nothing else, CI sets `UV_CACHE_DIR` to `.uv-cache` **inside `backend/`**,
    and the derivation then reported **every catalogue in the roster** as
    feeding a heading against a docstring that says seven. It passed locally and
    failed only in CI, which is the worst shape a guard can have.

    **The dot rule this held is a subset of that one**, and the difference is
    not academic: an environment's directory need not carry a dot, and this
    walk read `site-packages` under one that did not until the shared predicate
    grew that name. What is left here is the half that is genuinely this
    file's: two directories that **are** ours and are still not source a
    catalogue reaches.
    """
    if _NOT_THIS_APP & set(parts):
        return False
    return not _is_vendored(root.joinpath(*parts), root)


def _modules(root: pathlib.Path = BACKEND) -> list[pathlib.Path]:
    found = [
        path
        for path in root.rglob("*.py")
        if _is_this_app(path.relative_to(root).parts, root)
    ]
    # The packages it must cover rather than a number, which is the floor its
    # three sibling walks carry and this one did not: the anti-vacuity beside
    # it is `assert walked` and `assert builds`, and one surviving file
    # satisfies both. See `test_accounts._sources` for the mutation that left
    # two guards of this shape green.
    assert {"routers", "schemas"} <= {path.parent.name for path in found}, found
    return found


def _module_name(path: pathlib.Path, root: pathlib.Path = BACKEND) -> str:
    """The name `import` gives a module under `backend/`, which is `__module__`."""
    parts = path.relative_to(root).with_suffix("").parts
    return ".".join(parts[:-1] if parts[-1] == "__init__" else parts)


def _qualified(function: Any) -> str:
    """A function's node in the graph: the dotted name Python itself gives it."""
    return f"{function.__module__}.{function.__qualname__}"


#: What a construction site calls, as `_qualified` names it.
_HEADING = _qualified(Heading)

_FUNCTION = ast.FunctionDef | ast.AsyncFunctionDef

#: The receiver `_edges` writes for an attribute called on a value it cannot type.
_UNTYPED = "<untyped>"

#: One scope's names, each to the dotted name it denotes, or to None where it
#: holds a value the graph cannot follow.
_Scope = dict[str, str | None]


def _own_nodes(body: Iterable[ast.AST]) -> Iterator[ast.AST]:
    """Every node one scope evaluates itself.

    A nested function, class or lambda is yielded, and so are its decorators,
    defaults and bases, which run where it is defined; its body is another
    scope's.
    """
    pending = list(body)
    while pending:
        node = pending.pop()
        yield node
        if isinstance(node, _FUNCTION | ast.Lambda):
            pending.extend(node.args.defaults)
            pending.extend(d for d in node.args.kw_defaults if d is not None)
        if isinstance(node, _FUNCTION | ast.ClassDef):
            pending.extend(node.decorator_list)
        if isinstance(node, ast.ClassDef):
            pending.extend([*node.bases, *node.keywords])
        elif not isinstance(node, _FUNCTION | ast.Lambda):
            pending.extend(ast.iter_child_nodes(node))


def _definitions(
    body: Iterable[ast.AST], prefix: str
) -> Iterator[tuple[str, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef]]:
    """Every function and class under `prefix`, by the `__qualname__` Python gives it."""
    for node in _own_nodes(body):
        if isinstance(node, _FUNCTION | ast.ClassDef):
            name = f"{prefix}.{node.name}"
            yield name, node
            local = isinstance(node, _FUNCTION)
            yield from _definitions(node.body, f"{name}.<locals>" if local else name)


def _imported(node: ast.Import | ast.ImportFrom) -> Iterator[tuple[str, str]]:
    """The names one import statement binds, each to the dotted name it denotes."""
    for alias in node.names:
        if isinstance(node, ast.ImportFrom):
            if alias.name != "*":
                yield alias.asname or alias.name, f"{node.module}.{alias.name}"
        elif alias.asname:
            yield alias.asname, alias.name
        else:
            head = alias.name.split(".")[0]
            yield head, head


def _bindings(
    body: Iterable[ast.AST], prefix: str, outer: Iterable[_Scope] = ()
) -> _Scope:
    """The names one scope binds, under Python's rule that any binding makes it local.

    A definition or an import is followed. So is a name bound by `name = <expr>`
    or `type name = <expr>`, to whatever `_named` makes of the expression read
    in this scope and in source order: `fields = marc_fields.Fields(record)`
    types `fields`, `alias = fields` on a later line types `alias` the same,
    and a PEP 695 alias types an annotation spelled through it. Where a name
    has two such bindings, one of them types it; mypy's strict mode refuses a
    rebinding to another type. A name bound only some other way holds a value
    and shadows whatever an outer scope calls by it. A name declared `global`
    or `nonlocal` is the outer scope's.
    """
    bound: _Scope = {}
    declared: set[str] = set()
    held: dict[str, ast.expr] = {}
    for node in _own_nodes(body):
        if isinstance(node, _FUNCTION | ast.ClassDef):
            bound[node.name] = f"{prefix}.{node.name}"
        elif isinstance(node, ast.Import | ast.ImportFrom):
            bound.update(_imported(node))
        elif isinstance(node, ast.Global | ast.Nonlocal):
            declared.update(node.names)
        elif isinstance(node, ast.Name) and not isinstance(node.ctx, ast.Load):
            bound.setdefault(node.id, None)
        elif isinstance(node, ast.ExceptHandler | ast.MatchAs | ast.MatchStar) and node.name:
            bound.setdefault(node.name, None)
        if isinstance(node, ast.TypeAlias):
            held[node.name.id] = node.value
        elif (
            isinstance(node, ast.Assign)
            and len(node.targets) == 1
            and isinstance(target := node.targets[0], ast.Name)
        ):
            held[target.id] = node.value
    # `_own_nodes` yields a body from its end, so without the sort `alias =
    # fields` is read before `fields` is typed and stays untyped itself.
    in_source_order = sorted(
        held.items(), key=lambda item: (item[1].lineno, item[1].col_offset)
    )
    for name, value in in_source_order:
        if bound.get(name) is None:
            bound[name] = _named(value, [*outer, bound])
    return {name: value for name, value in bound.items() if name not in declared}


def _named(expr: ast.expr | None, scopes: list[_Scope]) -> str | None:
    """The dotted name an expression denotes where it is read, or None.

    A name, attributes off one, or a call of one denotes something: `C(...)`
    is read as `C`, the type of the object it constructs. A subscript or a
    literal is a value the graph cannot type. `X | None` is read as `X`, so an
    optional annotation types its parameter too.
    """
    if isinstance(expr, ast.BinOp) and isinstance(expr.op, ast.BitOr):
        sides = [
            side
            for side in (expr.left, expr.right)
            if not (isinstance(side, ast.Constant) and side.value is None)
        ]
        expr = sides[0] if len(sides) == 1 else None
    parts: list[str] = []
    while isinstance(expr, ast.Attribute | ast.Call):
        if isinstance(expr, ast.Call):
            # What a function returns is no attribute of it, so `f(...).m`
            # names a `f.m` that `_graph_of` finds nowhere, and it reaches only
            # what `_graph_of` follows the name `m` to.
            expr = expr.func
        else:
            parts.insert(0, expr.attr)
            expr = expr.value
    if not isinstance(expr, ast.Name):
        return None
    head = next((scope[expr.id] for scope in reversed(scopes) if expr.id in scope), None)
    return None if head is None else ".".join([head, *parts])


def _parameters(arguments: ast.arguments) -> list[ast.arg]:
    """Every parameter a signature binds, of every kind."""
    every = [
        *arguments.posonlyargs,
        *arguments.args,
        arguments.vararg,
        *arguments.kwonlyargs,
        arguments.kwarg,
    ]
    return [parameter for parameter in every if parameter is not None]


def _signature(
    node: ast.FunctionDef | ast.AsyncFunctionDef, scopes: list[_Scope], owner: str | None
) -> _Scope:
    """A function's parameters, each to the class its annotation names, or None.

    A method's first parameter denotes its class, unless the method is static.
    """
    bound = {
        parameter.arg: _named(parameter.annotation, scopes)
        for parameter in _parameters(node.args)
    }
    positional = [*node.args.posonlyargs, *node.args.args]
    static = any(
        isinstance(decorator, ast.Name) and decorator.id == "staticmethod"
        for decorator in node.decorator_list
    )
    if owner is not None and positional and not static:
        bound[positional[0].arg] = owner
    return bound


def _edges(tree: ast.Module, module: str) -> dict[str, set[str]]:
    """What each function one module defines calls, as the dotted name each call denotes.

    A name is resolved as Python resolves it: through the enclosing function
    scopes, then the module's definitions and imports. So a parameter or a
    local shadows the module function it spells, and an aliased import is
    followed. An attribute is followed off a module, a class, a method's first
    parameter, a parameter annotated with a class (`fields:
    marc_fields.Fields` is how both MARC readers reach their headings), a
    constructed object, and a name `_bindings` types. A decorator is a call
    the function makes, since what it wraps is what gets registered.

    **An attribute called on a receiver it cannot type**, such as a subscript,
    a loop variable or an unannotated parameter, **is written with the
    receiver `_UNTYPED`**, and `_graph_of` decides what that reaches. An
    enclosing function owns every call its nested functions make.

    Callees are as written here; `_graph_of` follows a re-export and keeps
    those that land on a function.
    """
    names = {id(node): name for name, node in _definitions(tree.body, module)}
    calls: dict[str, set[str]] = {}

    def walk(
        body: Iterable[ast.AST],
        scopes: list[_Scope],
        owners: tuple[str, ...],
        cls: str | None,
    ) -> None:
        for node in _own_nodes(body):
            if isinstance(node, ast.Call) and owners:
                callee = _named(node.func, scopes)
                if callee is None and isinstance(node.func, ast.Attribute):
                    callee = f"{_UNTYPED}.{node.func.attr}"
                if callee is not None:
                    for owner in owners:
                        calls.setdefault(owner, set()).add(callee)
            elif isinstance(node, _FUNCTION):
                name = names[id(node)]
                # A decorator replaces the function, so what it reaches is the
                # function's own: `@with_headings(scheme)` on an entry.
                for decorator in node.decorator_list:
                    wrapper = _named(decorator, scopes)
                    if wrapper is not None:
                        calls.setdefault(name, set()).add(wrapper)
                given = _signature(node, scopes, cls)
                local = {
                    **_bindings(node.body, f"{name}.<locals>", [*scopes, given]),
                    **given,
                }
                walk(node.body, [*scopes, local], (*owners, name), None)
            elif isinstance(node, ast.ClassDef):
                # A class body's names are not visible to its methods.
                walk(node.body, scopes, owners, names[id(node)])
            elif isinstance(node, ast.Lambda):
                shadowed: _Scope = {p.arg: None for p in _parameters(node.args)}
                walk([node.body], [*scopes, shadowed], owners, None)

    walk(tree.body, [_bindings(tree.body, module)], (), None)
    return calls


def _graph_of(trees: Mapping[str, ast.Module]) -> tuple[dict[str, set[str]], set[str]]:
    """Every function the modules define, what it calls, and which build a Heading.

    **Keyed by module and qualified name, so two functions sharing a name are
    two nodes.** A callee naming something one of these modules re-exports
    (`schemas.BookOut`) is followed to where it is defined.

    **A callee that lands on no function is followed by its last name, but only
    to a function that builds a Heading itself or a method that reaches one**,
    whatever the receiver was: one `_edges` could not type, a class the method
    is inherited into, `super()`, an attribute of an attribute. The targets grow
    until the reach stops moving, since a method reached this way can be what
    the next caller needs. The guess errs toward reaching, so a wrong one reds
    the stated count rather than leaving it stale. Leaving out a module
    function that only reaches one is what keeps `.read()` on an upload off
    `marc.read`, which reaches a heading but builds none itself.

    What draws no edge: a module function that reaches a heading only through
    another function, called on such a receiver; a parameter annotated with a
    `Protocol`, which lands on the protocol's `...` stub and not on an
    implementation; and a function handed over by reference rather than
    called, as `functools.partial` or a dict of callables hands it over.
    """
    functions: set[str] = set()
    classes: set[str] = set()
    known = set(trees)
    imports: dict[str, dict[str, str]] = {}
    for module, tree in trees.items():
        for name, node in _definitions(tree.body, module):
            known.add(name)
            if isinstance(node, _FUNCTION):
                functions.add(name)
            else:
                classes.add(name)
        imports[module] = {
            name: target
            for node in _own_nodes(tree.body)
            if isinstance(node, ast.Import | ast.ImportFrom)
            for name, target in _imported(node)
        }

    def defined(dotted: str, hops: int = 0) -> str:
        parts = dotted.split(".")
        cut = next(
            (i for i in range(len(parts), 0, -1) if ".".join(parts[:i]) in trees), 0
        )
        # The bound is a re-export cycle, which would otherwise not end.
        if not cut or hops > len(trees):
            return dotted
        current = ".".join(parts[:cut])
        for part in parts[cut:]:
            following = f"{current}.{part}"
            if following not in known and part in imports.get(current, {}):
                following = defined(imports[current][part], hops + 1)
            current = following
        return current

    calls: dict[str, set[str]] = {}
    builds: set[str] = set()
    unplaced: dict[str, set[str]] = {}
    for module, tree in trees.items():
        for function, callees in _edges(tree, module).items():
            for callee in map(defined, callees):
                if callee == _HEADING:
                    builds.add(function)
                elif callee in functions:
                    calls.setdefault(function, set()).add(callee)
                else:
                    unplaced.setdefault(function, set()).add(callee.rsplit(".", 1)[-1])
    methods = {name for name in functions if name.rsplit(".", 1)[0] in classes}
    targets: set[str] = set()
    while (widened := builds | (_reaching(calls, builds) & methods)) != targets:
        targets = widened
        for function, attributes in unplaced.items():
            for target in targets:
                if target.rsplit(".", 1)[-1] in attributes:
                    calls.setdefault(function, set()).add(target)
    return calls, builds


def _call_graph() -> tuple[dict[str, set[str]], set[str]]:
    """`_graph_of` this application."""
    return _graph_of(
        {_module_name(path): ast.parse(path.read_text()) for path in _modules()}
    )


def _reaching(calls: dict[str, set[str]], builds: set[str]) -> set[str]:
    """The functions that build a Heading, plus everything that can call one."""
    reaching = set(builds)
    moved = True
    while moved:
        moved = False
        for function, callees in calls.items():
            if function not in reaching and callees & reaching:
                reaching.add(function)
                moved = True
    return reaching


def _table_holding_modules() -> list[Any]:
    """Every module of this application that is loaded, found rather than named.

    **Naming `metadata` was the rule until a decoder lived somewhere else.** It
    read `vars(metadata)` alone, which was right while every decoder was a
    catalogue's; `opds.py` is the import family's first, so a walk keyed on one
    module reported `Reader.OPDS_ATOM` as answered by nothing. Naming two
    modules would be the enumerating shape this file already refuses one level
    down, so the module set is derived the same way the table set is.

    **The exclusion, stated rather than an inclusion list**: this backend's own
    `.py` files, minus anything under `tests/`, because a test may build a
    reader keyed dict of its own and `test_a_reader_registered_in_a_new_table`
    does exactly that. A vendored environment is excluded by the same path test.

    A module is only found if something imported it. `conftest.py` imports
    `main`, which reaches every router and every module a router reaches, so
    that is the whole application; `test_the_walk_reaches_more_than_one_module`
    is what fails if it ever stops being.
    """
    found = []
    for module in list(sys.modules.values()):
        path = getattr(module, "__file__", None)
        if path is None:
            continue
        resolved = pathlib.Path(path).resolve()
        if resolved.is_relative_to(BACKEND) and "tests" not in resolved.parts:
            found.append(module)
    return found


def _dispatch_tables() -> list[dict[decoders.Reader, Any]]:
    """Every reader keyed dispatch table in this application, found rather than named.

    **A list of five attribute names is the shape this whole file refuses.** It
    was one, and a sixth table wiring an already registered reader to a heading
    builder passed all thirteen tests: the reader is not missing, so
    `test_every_reader_is_answered_by_something` stays green, and the derived
    count stays one short of the truth. Measured 2026-09-06 by adding
    `{Reader.DUBLIN_CORE: _dnb_record}` to `metadata` and running this class.

    The shape is the rule: a non empty `dict` whose every key is a `Reader` and
    whose every value can be called. **The callable half is not decoration**: a
    `dict[Reader, str]` of per reader labels is not a dispatch table, and
    admitting one would put a value with no `__qualname__` into the walk, where the
    only honest thing left to do with it is skip it silently.

    Which modules are searched is `_table_holding_modules`, and it is derived
    for this function's own reason one level up.
    """
    return [
        value
        for module in _table_holding_modules()
        for value in vars(module).values()
        if isinstance(value, dict)
        and value
        and all(isinstance(key, decoders.Reader) for key in value)
        and all(callable(decoder) for decoder in value.values())
    ]


def _registered_entries() -> dict[decoders.Reader, set[str]]:
    """Which function each reader is answered by, read off the tables themselves."""
    entries: dict[decoders.Reader, set[str]] = {}
    for table in _dispatch_tables():
        for reader, decoder in table.items():
            # `_qualified` rather than a `getattr` default, so anything
            # the walk cannot name raises here instead of contributing an empty
            # name nothing can match. Two kinds reach this: a value the shape
            # rule should not have admitted, and a callable with no `__qualname__`,
            # which a `functools.partial` in a table would legitimately be.
            entries.setdefault(reader, set()).add(_qualified(decoder))
    return entries


def _marc_probe(reader: decoders.Reader, extra: str) -> bool:
    """Whether one MARC reader builds a heading out of a record, by asking it."""
    record = ElementTree.fromstring(
        '<record xmlns="http://www.loc.gov/MARC21/slim">'
        '<datafield tag="245" ind1="1" ind2="0">'
        "<subfield code=\"a\">Praxiswissen Docker</subfield></datafield>"
        f"{extra}</record>"
    )
    built = metadata._marc_build(
        decoders.Decoding(source="probe", reader=reader),
        marc_fields.Fields(record),
        "9783960092353",
    )
    return built is not None and bool(built.headings)


#: A MARC record carrying both of the things a MARC reader can make a heading
#: from: an `082` Dewey number and a `650` with a GND identifier on it.
_CLASSIFIED = (
    '<datafield tag="082" ind1="0" ind2="4">'
    "<subfield code=\"a\">004</subfield></datafield>"
    '<datafield tag="650" ind1=" " ind2="7">'
    "<subfield code=\"a\">Informatik</subfield>"
    '<subfield code="0">(DE-588)4026894-9</subfield>'
    "<subfield code=\"2\">gnd</subfield></datafield>"
)


def _parsed(source: str) -> ast.Module:
    return ast.parse(textwrap.dedent(source))


class TestTheCallGraphResolvesACallTheWayPythonDoes:
    """`_edges` and `_graph_of`, on constructed modules, one resolution each."""

    def test_a_call_to_a_function_of_this_module_is_an_edge_to_it(self):
        tree = _parsed("""
            def load():
                return read()

            def read():
                pass
            """)

        assert _edges(tree, "m") == {"m.load": {"m.read"}}

    def test_an_imported_name_is_an_edge_to_where_it_was_imported_from(self):
        tree = _parsed("""
            import isbn
            from marc import read as read_marc

            def load():
                read_marc()
                isbn.parse()
            """)

        assert _edges(tree, "m") == {"m.load": {"marc.read", "isbn.parse"}}

    def test_a_parameter_shadows_the_module_name_it_spells(self):
        tree = _parsed("""
            from marc import read, ask, more, key, rest

            def walk(read, /, ask, *more, key, **rest):
                read(); ask(); more(); key(); rest(); parse()

            def parse():
                pass
            """)

        assert _edges(tree, "m") == {"m.walk": {"m.parse"}}

    def test_an_attribute_on_a_parameter_is_followed_only_through_its_annotation(self):
        tree = _parsed("""
            import marc_fields

            def load(upload, fields: marc_fields.Fields | None):
                upload.read()
                fields.ddc_headings()
            """)

        assert _edges(tree, "m") == {
            "m.load": {f"{_UNTYPED}.read", "marc_fields.Fields.ddc_headings"}
        }

    def test_a_method_s_first_parameter_is_its_class_unless_the_method_is_static(self):
        tree = _parsed("""
            class C:
                def m(self):
                    pass

                def load(self):
                    self.m()

                @staticmethod
                def build(record):
                    record.m()
            """)

        assert _edges(tree, "m") == {
            "m.C.load": {"m.C.m"},
            "m.C.build": {f"{_UNTYPED}.m"},
        }

    def test_a_constructed_object_has_the_type_of_its_class(self):
        tree = _parsed("""
            import marc_fields

            def load(record):
                fields = marc_fields.Fields(record)
                fields.ddc_headings()
                marc_fields.Fields(record).controlled_subjects()
            """)

        assert _edges(tree, "m") == {
            "m.load": {
                "marc_fields.Fields",
                "marc_fields.Fields.ddc_headings",
                "marc_fields.Fields.controlled_subjects",
            }
        }

    def test_an_alias_of_a_typed_local_has_its_type(self):
        tree = _parsed("""
            import marc_fields

            def load(record):
                fields = marc_fields.Fields(record)
                alias = fields
                alias.ddc_headings()
            """)

        assert _edges(tree, "m") == {
            "m.load": {"marc_fields.Fields", "marc_fields.Fields.ddc_headings"}
        }

    def test_a_type_alias_types_an_annotation_spelled_through_it(self):
        tree = _parsed("""
            import marc_fields

            type Fields = marc_fields.Fields

            def load(fields: Fields):
                fields.ddc_headings()
            """)

        assert _edges(tree, "m") == {"m.load": {"marc_fields.Fields.ddc_headings"}}

    def test_a_decorator_is_a_call_the_function_makes(self):
        tree = _parsed("""
            def with_headings(scheme):
                pass

            @with_headings("LCSH")
            def load():
                pass
            """)

        assert _edges(tree, "m") == {"m.load": {"m.with_headings"}}

    def test_an_untyped_receiver_reaches_a_builder_by_its_name_and_nothing_else(self):
        trees = {
            "marc": _parsed("""
                from catalogue import Heading

                def ddc_headings(record):
                    return Heading()

                def read(record):
                    return ddc_headings(record)
                """),
            "user": _parsed("""
                def load(upload):
                    upload.read()

                def classify(parser):
                    parser.ddc_headings()
                """),
        }

        assert _reaching(*_graph_of(trees)) == {
            "marc.ddc_headings",
            "marc.read",
            "user.classify",
        }

    @pytest.mark.parametrize(
        "load",
        [
            """
            def load(record):
                as_fields(record).headings()
            """,
            """
            def load(record):
                for fields in [marc_fields.Fields(record)]:
                    fields.headings()
            """,
            """
            def load(record):
                fields: marc_fields.Fields = as_fields(record)
                fields.headings()
            """,
        ],
        ids=["a helper's result", "a loop variable", "an annotated local"],
    )
    def test_an_untyped_receiver_reaches_a_method_that_only_delegates(self, load):
        """A method building nothing itself is followed by name as well, so a
        reader delegating through one is not dropped for the spelling of its
        receiver."""
        trees = {
            "marc_fields": _parsed("""
                from catalogue import Heading

                class Fields:
                    def ddc_headings(self):
                        return Heading()

                    def headings(self):
                        return self.ddc_headings()
                """),
            "user": _parsed(
                textwrap.dedent("""
                    import marc_fields

                    def as_fields(record) -> marc_fields.Fields:
                        return marc_fields.Fields(record)
                    """)
                + textwrap.dedent(load)
            ),
        }

        assert _reaching(*_graph_of(trees)) == {
            "marc_fields.Fields.ddc_headings",
            "marc_fields.Fields.headings",
            "user.load",
        }

    def test_a_name_defined_in_two_modules_is_two_nodes(self):
        trees = {
            "a": _parsed("""
                from catalogue import Heading

                def read():
                    return Heading()
                """),
            "b": _parsed("""
                def read():
                    return None
                """),
            "c": _parsed("""
                from b import read

                def load():
                    return read()
                """),
        }

        assert _reaching(*_graph_of(trees)) == {"a.read"}

    def test_a_call_through_a_re_export_lands_on_the_definition(self):
        trees = {
            "pkg": _parsed("from pkg.inner import parse"),
            "pkg.inner": _parsed("""
                def parse():
                    pass
                """),
            "user": _parsed("""
                import pkg

                def load():
                    pkg.parse()
                """),
        }

        calls, _ = _graph_of(trees)

        assert calls == {"user.load": {"pkg.inner.parse"}}


class TestHowManyCataloguescanFeedOneBooksHeadings:
    """`#206`: the count is derived from the code, not restated beside it.

    `bounded_headings` says a merge has concatenated up to *n* catalogues,
    "which is every catalogue whose reader builds a `Heading`", and that *n* was
    wrong twice in two days. Both corrections were made by a reader noticing,
    which is the weakest instrument here and the one this repository has
    repeatedly recorded as insufficient. The clause was wrong too, and in a way
    no count could catch: it said every **source**, where `marc._record` builds
    headings out of an uploaded file that no catalogue ever saw.

    **Deliberately not a census assertion.** The roster census already holds a
    row of hand maintained figures, and a seventh would put this number under
    the same class of guard it has twice demonstrated it cannot survive:
    something a person states. This walks instead, from the `Heading`
    construction sites, to the functions that can reach one, to the readers
    those functions answer for, to the rows in `targets.SEEDED` naming those
    readers. Add a catalogue on a heading building reader and the derived number
    moves with it, so the assertion is about the relationship and the literal in
    the prose is the only thing that can be stale.

    **Two instruments, because two careful readings are one instrument twice.**
    The walk is static and cannot see which branch of a dispatcher a reader
    takes, so any reader sharing an entry function with another is asked
    directly instead. Today that is the two MARC readers and no others, which is
    checked rather than assumed.

    **What neither instrument sees, stated because a blind spot left implicit is
    the one nobody looks for.** The probe enters at `metadata._marc_build`,
    which is one call below the registered entries `_marc_lookup` and
    `_marc_search`. A change that stripped headings **between** the entry and
    `_marc_build`, a `decoders.Decoding` flag say, is invisible to the walk,
    which sees the call, and to the probe, which starts underneath it. Probing
    the entries themselves is not a smaller fix: they take a whole SRU response
    and return a `Lookup`, so the fixture would be a response per reader and the
    thing under test would become the transport.
    """

    def _derived(self) -> set[decoders.Reader]:
        calls, builds = _call_graph()
        reaching = _reaching(calls, builds)
        return {
            reader
            for reader, names in _registered_entries().items()
            if names & reaching
        }

    def test_a_tooling_directory_is_not_read_however_a_tool_names_it(self):
        """The evasion that broke this guard in CI, kept as a test.

        The exclusion named `.venv` and nothing else, and CI sets `UV_CACHE_DIR`
        to `.uv-cache` under `backend/`, so the walk read every vendored wheel
        and reported **every catalogue in the roster** as feeding a heading,
        where the docstring says seven. **This passed locally throughout**, because uv caches
        outside the tree here.

        So the rule is the leading dot rather than a list, and this fails if
        anybody puts it back to a list: the third case is a name no list could
        have held, because no tool has invented it yet.
        """
        assert not _is_this_app((".venv", "lib", "site.py"))
        assert not _is_this_app((".uv-cache", "pkg", "vendored.py"))
        assert not _is_this_app((".a-cache-no-tool-has-invented-yet", "x.py"))
        assert _is_this_app(("metadata.py",))
        assert _is_this_app(("routers", "books.py"))

    def test_the_walk_applies_that_rule_to_this_checkout(self):
        """The live half: that `_modules` **applies** the rule, not what it says.

        **Asked against the unfiltered tree, because asking the filtered one
        answers itself.** `_modules` excludes on the same predicate, so a check
        that re-tests its output for a dotted part is empty by construction and
        cannot go red on any checkout. Two versions of this were: one reading
        the absolute path, which also went red wherever the checkout itself sat
        under a dotted directory, and one reading the relative path, which was
        simply vacuous.

        What is left for it to catch is a `_modules` that stops filtering while
        `_is_this_app` stays right, which the pure test above cannot see. The
        count would eventually go red too, saying the number is wrong rather
        than saying this walk read a virtualenv.
        """
        below = [path.relative_to(BACKEND) for path in BACKEND.rglob("*.py")]
        tooling = [
            path
            for path in below
            if any(part.startswith(".") for part in path.parts)
        ]
        if not tooling:
            pytest.skip("no tooling directory in this checkout to exclude")

        walked = {path.relative_to(BACKEND) for path in _modules()}

        assert walked
        assert not walked & set(tooling)

    def test_the_walk_finds_the_construction_sites_at_all(self):
        """Anti vacuity, and the first thing to break if `Heading` is renamed or
        the module layout moves: with an empty set every assertion below passes
        by finding nothing."""
        _, builds = _call_graph()

        assert builds

    def test_a_sixth_dispatch_table_is_found_rather_than_missed(self, monkeypatch):
        """The evasion that passed all thirteen tests, kept as a test.

        A reader already registered in one of the tables, registered again in a
        new one pointing at a decoder that builds headings, moved nothing:
        `test_every_reader_is_answered_by_something` compares key sets and the
        reader was not missing, so the derived count stayed one short and the
        docstring it is checked against stayed right by accident.

        Both halves are asserted, because the second alone would pass against a
        walk that credited every reader. **Whichever reader builds nothing
        today**, rather than a named one: naming it would fail the day that
        reader legitimately starts building headings, which says nothing about
        what this is guarding.
        """
        builds_nothing = sorted(set(decoders.Reader) - self._derived())
        assert builds_nothing, "every reader builds a heading, so this checks nothing"
        reader = builds_nothing[0]
        # The other half of the patched dict carries an assumption too, so it
        # fails with its own reason rather than as "discovery is broken".
        assert _qualified(metadata._dnb_record) in _reaching(*_call_graph()), (
            "the decoder this patches in no longer reaches a Heading, so the "
            "test would prove nothing about discovery"
        )

        monkeypatch.setattr(
            metadata,
            "_A_TABLE_THIS_TEST_ADDED",
            {reader: metadata._dnb_record},
            raising=False,
        )

        assert reader in self._derived()

    def test_every_registered_entry_is_a_function_the_walk_defines(self):
        """`_derived` joins the tables to the graph by name, so an entry the graph
        has no function for, a lambda or a class, would drop its reader in
        silence."""
        functions = {
            name
            for path in _modules()
            for name, node in _definitions(
                ast.parse(path.read_text()).body, _module_name(path)
            )
            if isinstance(node, _FUNCTION)
        }
        registered = set().union(*_registered_entries().values())

        assert registered <= functions, registered - functions

    def test_every_reader_is_answered_by_something(self):
        """A reader missing from every dispatch table would be excluded silently
        rather than counted as building nothing, so the count would fall with no
        finding anywhere. `metadata.resolve` raises on this for a target
        in the seeded roster; this is the same rule asked of the closed set."""
        assert set(_registered_entries()) == set(decoders.Reader)

    def test_the_walk_reaches_more_than_one_module(self):
        """The control the row above needs since the walk stopped naming
        `metadata`.

        `_table_holding_modules` finds only what something has imported, so a
        conftest that stopped importing the application would make the test
        above pass over a smaller closed set without saying so. Asserted as a
        count of **modules holding a table** rather than of modules loaded,
        because the second is true of a run that found no table at all.
        """
        holders = {
            module.__name__
            for module in _table_holding_modules()
            if any(
                isinstance(value, dict)
                and value
                and all(isinstance(key, decoders.Reader) for key in value)
                and all(callable(decoder) for decoder in value.values())
                for value in vars(module).values()
            )
        }

        assert len(holders) > 1, holders

    def test_the_walk_separates_readers_rather_than_admitting_all_of_them(self):
        """The other half of anti vacuity. A walk that answered "every reader"
        would also produce the right total, for the wrong reason."""
        assert self._derived() < set(decoders.Reader)

    def test_only_the_marc_readers_share_an_entry_the_walk_cannot_split(self):
        """The walk's blind spot, named and checked rather than commented on.

        `_marc_lookup` serves both MARC readers and dispatches inside
        `_marc_build`, so the static walk credits both with whatever either can
        build. That is the right answer today and it is not the walk that makes
        it right. If a third reader ever shares an entry function, this fails
        and the reader below has to be asked the way the MARC pair is.
        """
        entries = _registered_entries()
        shared = {
            reader
            for reader, names in entries.items()
            if any(
                names & other
                for another, other in entries.items()
                if another is not reader
            )
        }

        assert shared == {decoders.Reader.MARC_GND, decoders.Reader.MARC_PLAIN}

    @pytest.mark.parametrize(
        "reader", [decoders.Reader.MARC_GND, decoders.Reader.MARC_PLAIN]
    )
    def test_each_marc_reader_builds_a_heading_when_asked(self, reader):
        """The second instrument. Both are counted, so both have to earn it on
        their own rather than through the dispatcher they share."""
        assert _marc_probe(reader, _CLASSIFIED)

    @pytest.mark.parametrize(
        "reader", [decoders.Reader.MARC_GND, decoders.Reader.MARC_PLAIN]
    )
    def test_the_probe_can_answer_no(self, reader):
        """Sensitivity for the pair above: a probe that answered yes on a record
        with nothing to classify would prove nothing about either reader."""
        assert not _marc_probe(reader, "")

    def test_the_sentence_is_read_wherever_the_wrap_falls(self):
        """The evasion that broke this guard, kept as a test.

        Editing the surrounding paragraph moved the newline between the number
        and its noun, and the extraction reported that the docstring no longer
        made the claim at all. Loud rather than silent, but red for a reason
        that has nothing to do with what the code does.

        **One of these spells the phrase unwrapped and the rest break it**,
        which is not only economy: the roster census scans this file too, and
        every number beside a roster noun in it needs a verdict saying what it
        counts. One fixture sentence carrying one, adjudicated as fixture prose,
        is cheaper to keep true than four.
        """
        assert _catalogues_stated_in("concatenated up to seven catalogues") == 7
        assert _catalogues_stated_in("concatenated up to seven\n    catalogues") == 7
        assert _catalogues_stated_in("concatenated up\n to seven\n catalogues,") == 7
        assert _catalogues_stated_in("a merge concatenated several catalogues") is None

    def test_the_stated_count_is_the_derived_one(self):
        """The claim itself. Read out of `__doc__` rather than off the source
        literal, because a docstring is dedented and its literal is not, so a
        guard comparing one against the other reports a mismatch that is not
        there."""
        derived = {
            source
            for source, target in targets.SEEDED.items()
            if target.reader in self._derived()
        }
        stated = _catalogues_stated_in(bounded_headings.__doc__ or "")

        assert stated is not None, (
            "`bounded_headings` no longer says how many catalogues a merge can "
            "have concatenated"
        )
        assert stated == len(derived), (
            f"the docstring says {stated} catalogues; the readers that "
            f"build a Heading are fed by {len(derived)}: "
            f"{sorted(source.value for source in derived)}. A rise for a reader "
            "nobody touched means a new builder or delegating method shares a "
            "name with a method that reader calls on a value the graph cannot "
            "type, which `_graph_of` follows by that name"
        )

    def test_the_data_model_states_the_same_count(self):
        """The same sentence lives in a published document, and a figure written
        twice is a figure that stops being re-derived. Both are checked against
        the derivation rather than against each other."""
        derived = sum(
            target.reader in self._derived() for target in targets.SEEDED.values()
        )
        stated = _catalogues_stated_in(
            (BACKEND.parent / "docs" / "data-model.md").read_text()
        )

        assert stated is not None, (
            "`docs/data-model.md` no longer states how many catalogues a merge "
            "can have concatenated"
        )
        assert stated == derived
