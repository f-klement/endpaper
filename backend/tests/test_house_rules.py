"""House rules that are cheaper to enforce than to review for.

Each class here exists because the same defect was found by a person, twice or
in two places, and the finding was mechanical enough that nobody should have to
find it a third time. Adding one is the right answer to "a reviewer caught this
again".
"""

import ast
import re
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parent.parent


def _python_sources() -> list[Path]:
    """Every backend module, excluding the tests and the generated migrations."""
    return [
        path
        for path in BACKEND.rglob("*.py")
        if "tests" not in path.parts
        and "migrations" not in path.parts
        and ".venv" not in path.parts
        and "__pycache__" not in path.parts
    ]


def _test_sources() -> list[Path]:
    """Every file in the test tree. `_python_sources` deliberately excludes it."""
    return [
        path
        for path in (BACKEND / "tests").rglob("*.py")
        if "__pycache__" not in path.parts
    ]


def _docstring_nodes(tree: ast.Module) -> set[ast.AST]:
    """Every string constant that is a module, class or function docstring."""
    found: set[ast.AST] = set()
    for node in ast.walk(tree):
        if not isinstance(
            node, ast.Module | ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef
        ):
            continue
        first = node.body[0] if node.body else None
        if (
            isinstance(first, ast.Expr)
            and isinstance(first.value, ast.Constant)
            and isinstance(first.value.value, str)
        ):
            found.add(first.value)
    return found


#: The one helper allowed to turn foreign keys off, and the reason there is one.
#:
#: `database.py` sets its pragmas on the `connect` event, which SQLAlchemy fires
#: once per **physical** connection rather than per checkout. A connection given
#: back to the pool with foreign keys off keeps them off for whoever takes it
#: next, and for that test every `ForeignKey` and the `ON DELETE CASCADE` on
#: `book_tags` silently stop being enforced.
#:
#: The helper closes it by calling `connection.invalidate()` in a `finally`, so
#: the pool discards the connection instead of handing it on.
_FOREIGN_KEYS_OFF_HELPER = "_with_foreign_keys_off"


#: Callables that carry a validation bound, whatever the layer: a query
#: parameter, a path parameter, a header, a body field.
BOUNDING_CALLS = frozenset(
    {"Query", "Path", "PathParam", "Body", "Header", "Cookie", "Form", "Field"}
)
LOWER_BOUNDS = frozenset({"ge", "gt"})
UPPER_BOUNDS = frozenset({"le", "lt"})
ROUTE_METHODS = frozenset({"get", "post", "put", "patch", "delete"})


def _is_bounding_call(node: ast.AST) -> bool:
    """A call to one of the bounding helpers carrying both a floor and a
    ceiling. Both halves, because a floor alone is the older hole."""
    if not isinstance(node, ast.Call):
        return False
    func = node.func
    name = func.id if isinstance(func, ast.Name) else (
        func.attr if isinstance(func, ast.Attribute) else None
    )
    if name not in BOUNDING_CALLS:
        return False
    keywords = {keyword.arg for keyword in node.keywords if keyword.arg}
    return bool(keywords & LOWER_BOUNDS) and bool(keywords & UPPER_BOUNDS)


def _mentions_int(annotation: ast.AST | None) -> bool:
    """Whether an annotation carries an `int` anywhere inside it.

    `int`, `int | None` and `list[int]` all count. A name that merely *aliases*
    an int does not, which is why the alias table exists.
    """
    if annotation is None:
        return False
    return any(
        isinstance(child, ast.Name) and child.id == "int"
        for child in ast.walk(annotation)
    )


def _preceding_comment_block(lines: list[str], lineno: int) -> str:
    """The statement's line plus the contiguous comment lines above it.

    Walked upward rather than a fixed number of lines, so an opt-out reason can
    be as long as it needs to be. A fixed window is not a style choice here: the
    four-line one this replaced silently failed to see the `# unbounded ok:` on
    `BulkRequest.value`, whose reason runs to six lines, and the rule then
    reported a field that had been answered. `tests/test_models.py` walks
    upward for exactly this reason.
    """
    start = lineno - 1
    while start > 0 and lines[start - 1].lstrip().startswith("#"):
        start -= 1
    return "\n".join(lines[start:lineno])


def _is_route_handler(node: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    """Decorated `@<something>.get/post/put/patch/delete(...)`."""
    for decorator in node.decorator_list:
        call = decorator.func if isinstance(decorator, ast.Call) else decorator
        if isinstance(call, ast.Attribute) and call.attr in ROUTE_METHODS:
            return True
    return False


class TestEveryNumericQueryParamIsBoundedBothWays:
    """A numeric `Query()` needs `le` as well as `ge`.

    Python integers have no ceiling and SQLite's does: a value above 2**63-1
    reaches the driver and raises `OverflowError`, which lands in
    `unhandled_exception_handler` and answers **500**. That is the app calling
    its own code buggy over a value a caller chose.

    Measured: `POST /api/books/covers/backfill?after_id=9999999999999999999999`
    was a 500 for every member, from one query parameter, until `le` was added.
    Every other numeric parameter in the tree was already bounded at both ends,
    which is exactly why the missing one was easy to miss.

    A parameter may opt out with a `# unbounded ok:` comment giving the reason.

    **Kept beside the wider rule below rather than folded into it**, because the
    two catch different things and this one is the narrower. It fires on any
    numeric `Query` with a floor and no ceiling, whatever the type, so it still
    covers a float. It cannot fire on a parameter with no bound at all, and it
    never looked at `Path`, which is how twelve path ids stayed bare: that is
    what `TestEveryIntParameterFromTheOutsideIsBounded` is for.
    """

    #: Keywords that make a parameter numeric. A `str` bound by `pattern` or
    #: `max_length` is a different question and not this one.
    NUMERIC_BOUNDS = ("ge", "gt", "le", "lt")

    def test_every_numeric_query_parameter_has_an_upper_bound(self) -> None:
        offenders: list[str] = []

        for path in _python_sources():
            source = path.read_text()
            tree = ast.parse(source)
            lines = source.splitlines()

            for node in ast.walk(tree):
                if not isinstance(node, ast.Call):
                    continue
                name = node.func.id if isinstance(node.func, ast.Name) else (
                    node.func.attr if isinstance(node.func, ast.Attribute) else None
                )
                if name != "Query":
                    continue

                keywords = {k.arg for k in node.keywords if k.arg}
                # Not a numeric constraint at all, so not this rule's business.
                if not (keywords & {"ge", "gt"}):
                    continue
                if keywords & {"le", "lt"}:
                    continue

                line = lines[node.lineno - 1] if node.lineno <= len(lines) else ""
                nearby = "\n".join(lines[max(0, node.lineno - 4) : node.lineno])
                if "unbounded ok:" in nearby or "unbounded ok:" in line:
                    continue

                offenders.append(f"{path.relative_to(BACKEND)}:{node.lineno}")

        assert not offenders, (
            "These numeric Query parameters have a lower bound and no upper one, so a "
            "caller-supplied value can overflow SQLite's INTEGER and turn into a 500:\n  "
            + "\n  ".join(offenders)
            + "\nAdd `le=...`, or a `# unbounded ok:` comment saying why not."
        )


class TestEveryIntParameterFromTheOutsideIsBounded:
    """Every int a **caller** supplies is bounded at both ends, wherever it
    arrives from.

    This is the same defect as the class above and it has now been found three
    times in two days, each time in a place the previous lint could not see. A
    Python int has no ceiling and SQLite's does, so an unbounded one passes
    validation, reaches the driver and raises `OverflowError` from inside the
    query: a **500** answered to a value the caller chose.

    The two holes this class exists to close, both real:

    * The rule above only inspects `Query(...)`, so it could not see a **path**
      parameter at all. `GET /api/books/{id}`, `DELETE /api/books/tags/{id}` and
      both new collection routes each answered 500 to `2**63`.
    * It only fires on a parameter that has a lower bound and no upper one, so a
      parameter with **no bounds whatsoever** passed it silently. That is the
      shape every path parameter had.

    What counts as bounded: a bounding call (`Query`, `Path`, `PathParam`, ...)
    carrying one of `ge`/`gt` **and** one of `le`/`lt`, in the annotation or in
    the default; or an annotation naming a module-level alias that is itself
    bounded that way, which is how `dependencies.RowId` passes.

    What is inspected: route handlers (anything decorated `@<name>.get`,
    `.post`, `.put`, `.patch` or `.delete`) and every function named inside a
    `Depends(...)`, because a dependency's parameters are request parameters
    too: `book_for_read(book_id)` is where `{book_id}` is actually declared.

    A parameter may opt out with a `# unbounded ok:` comment giving the reason.
    """

    def _int_aliases(self, trees: dict[Path, ast.Module]) -> dict[str, bool]:
        """Module-level `Annotated[...]` aliases **that carry an int**, and
        whether each one is bounded at both ends.

        Two facts and not one, and collecting only the bounded ones is the bug
        this signature exists to prevent. `book_id: RowId` is `Name('RowId')`,
        which mentions no `int` at all, so a scope test that only looks for the
        literal name skips the parameter entirely: the alias then passes because
        it is never examined, and loosening `RowId` itself to `ge=1` leaves the
        whole lint green over twelve ids. The name has to bring the parameter
        **into** scope, and boundedness has to be the separate answer.

        Restricted to aliases whose value mentions `int`, or every
        `Annotated[User, Depends(...)]` in `dependencies.py` would be dragged
        into scope and reported for having no numeric bound.

        Collected across the whole tree rather than per file, because the alias
        is declared once (`dependencies.RowId`) and used in five other modules.

        **Resolved to a fixed point**, because `Loose2 = Loose` carries no `int`
        of its own: registering only what mentions `int` literally leaves the
        second name unknown, so a parameter annotated with it is skipped and the
        rule goes quiet again. That is the same hole as the dead branch above,
        one indirection further out, and a loop is the whole of the fix. It
        terminates because both facts only ever grow: a name is never
        un-registered, and `bounded` only moves False to True as more aliases
        become known.

        An alias of a bounded alias **inherits the bound**. `Tight2 = Tight` is
        as bounded as `Tight`, and saying otherwise would report a name that is
        in fact safe.
        """
        assignments: list[tuple[list[str], ast.expr]] = []
        for tree in trees.values():
            for node in tree.body:
                if isinstance(node, ast.Assign):
                    targets, value = node.targets, node.value
                elif isinstance(node, ast.AnnAssign) and node.value is not None:
                    targets, value = [node.target], node.value
                else:
                    continue
                names = [t.id for t in targets if isinstance(t, ast.Name)]
                if names:
                    assignments.append((names, value))

        aliases: dict[str, bool] = {}
        changed = True
        while changed:
            changed = False
            for names, value in assignments:
                named = {
                    child.id for child in ast.walk(value) if isinstance(child, ast.Name)
                }
                if not (_mentions_int(value) or named & aliases.keys()):
                    continue
                bounded = any(
                    _is_bounding_call(child) for child in ast.walk(value)
                ) or any(aliases.get(name, False) for name in named)
                for name in names:
                    if aliases.get(name) is not bounded:
                        aliases[name] = bounded
                        changed = True
        return aliases

    def _depends_targets(self, trees: dict[Path, ast.Module]) -> set[str]:
        """Every function named inside a `Depends(...)`."""
        names: set[str] = set()
        for tree in trees.values():
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call):
                    continue
                func = node.func
                called = func.id if isinstance(func, ast.Name) else (
                    func.attr if isinstance(func, ast.Attribute) else None
                )
                if called != "Depends":
                    continue
                for argument in node.args:
                    if isinstance(argument, ast.Name):
                        names.add(argument.id)
        return names

    def _offenders(self, sources: dict[Path, str]) -> list[str]:
        """The rule itself, over source text rather than over the tree.

        Separated so the guard tests below drive **this** function rather than
        its helpers. Asserting on `_is_bounding_call` and `_mentions_int`
        individually is what let the alias branch sit unreachable while every
        helper it depended on passed its own test.
        """
        trees = {path: ast.parse(text) for path, text in sources.items()}
        aliases = self._int_aliases(trees)
        dependencies = self._depends_targets(trees)
        offenders: list[str] = []

        for path, tree in trees.items():
            lines = sources[path].splitlines()
            for node in ast.walk(tree):
                if not isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
                    continue
                if not (_is_route_handler(node) or node.name in dependencies):
                    continue

                arguments = node.args.args + node.args.kwonlyargs
                defaults = dict(
                    zip(
                        node.args.args[len(node.args.args) - len(node.args.defaults):],
                        node.args.defaults,
                        strict=True,
                    )
                )
                for argument in arguments:
                    annotation = argument.annotation
                    if annotation is None:
                        continue
                    named = {
                        child.id
                        for child in ast.walk(annotation)
                        if isinstance(child, ast.Name)
                    }
                    # In scope when the annotation carries an int itself **or**
                    # names an int alias. The second half is what makes the
                    # acceptance below reachable at all.
                    if not (_mentions_int(annotation) or named & aliases.keys()):
                        continue
                    if any(
                        _is_bounding_call(child) for child in ast.walk(annotation)
                    ):
                        continue
                    if any(aliases.get(name, False) for name in named):
                        continue
                    default = defaults.get(argument)
                    if default is not None and _is_bounding_call(default):
                        continue

                    if "unbounded ok:" in _preceding_comment_block(
                        lines, argument.lineno
                    ):
                        continue
                    offenders.append(
                        f"{path.relative_to(BACKEND)}:{argument.lineno} ({node.name}.{argument.arg})"
                    )

        return sorted(offenders)

    def test_every_caller_supplied_int_is_bounded_at_both_ends(self) -> None:
        offenders = self._offenders(
            {path: path.read_text() for path in _python_sources()}
        )

        assert not offenders, (
            "These int parameters come from a caller and are not bounded at both ends, "
            "so a value past SQLite's INTEGER reaches the driver and turns into a 500:\n  "
            + "\n  ".join(offenders)
            + "\nAnnotate them `RowId` (dependencies.py), or with a Query/Path carrying "
            "ge and le, or add an `# unbounded ok:` comment saying why not."
        )

    #: A route handler and its alias declaration, as two files, because the
    #: alias really is declared in another module in this tree.
    PROBE = BACKEND / "probe.py"
    ALIASES = BACKEND / "probe_aliases.py"

    def _probe(self, annotation: str, alias: str | None = None) -> list[str]:
        sources = {
            self.PROBE: (
                "@router.get('/{book_id}')\n"
                f"def probe(book_id: {annotation}) -> None: ...\n"
            )
        }
        if alias is not None:
            sources[self.ALIASES] = f"{alias}\n"
        return self._offenders(sources)

    def test_the_guard_would_notice_a_bare_path_parameter(self) -> None:
        """A guard that cannot fail is not a guard. This is the exact shape
        every path parameter in this app had until it was measured: a bare
        `int`, on a real route, with nothing to stop `2**63` reaching the
        driver."""
        assert self._probe("int") == ["probe.py:2 (probe.book_id)"]

    def test_the_guard_would_notice_an_alias_that_lost_its_ceiling(self) -> None:
        """**The mutation that discriminates**, and the one this class failed
        before it was written.

        Loosening the shared alias is the realistic regression: it is one edit,
        in a file nobody associates with twelve routes, and every id annotated
        with it silently stops being bounded. A scope test that only looks for
        the literal name `int` skips `book_id: RowId` before ever asking whether
        the alias is bounded, so the whole acceptance branch was dead and the
        lint stayed green through exactly this change.
        """
        assert self._probe(
            "LooseId", "LooseId = Annotated[int, PathParam(ge=1)]"
        ) == ["probe.py:2 (probe.book_id)"]

    def test_the_guard_accepts_a_bounded_alias(self) -> None:
        """The other half, or the rule above could be satisfied by rejecting
        every alias, which would make `RowId` unusable."""
        assert (
            self._probe("TightId", "TightId = Annotated[int, PathParam(ge=1, le=9)]")
            == []
        )

    def test_the_guard_would_notice_an_alias_of_a_loosened_alias(self) -> None:
        """One hop further out than the case above, and invisible without the
        fixed point: `Loose2 = Loose` mentions no `int` itself, so a collector
        that registers only what carries one literally never learns the second
        name, and the parameter annotated with it is skipped exactly as
        `book_id: RowId` used to be."""
        assert self._probe(
            "Loose2",
            "Loose = Annotated[int, PathParam(ge=1)]\nLoose2 = Loose",
        ) == ["probe.py:2 (probe.book_id)"]

    def test_the_guard_accepts_an_alias_of_a_bounded_alias(self) -> None:
        """The other half: an alias of a bounded alias inherits the bound, or
        the rule above would be satisfied by reporting every indirection."""
        assert (
            self._probe(
                "Tight2",
                "Tight = Annotated[int, PathParam(ge=1, le=9)]\nTight2 = Tight",
            )
            == []
        )

    def test_the_guard_leaves_a_non_numeric_alias_alone(self) -> None:
        """`CurrentUser` and `DbSession` are `Annotated[..., Depends(...)]` with
        no int in them. Dragging every alias into scope rather than only the int
        ones would report each of them for having no numeric bound."""
        assert (
            self._probe("CurrentUser", "CurrentUser = Annotated[User, Depends(get_it)]")
            == []
        )


class TestEveryRequestBodyRowIdIsBounded:
    """The same rule again, through the door the parameter lint cannot see.

    A row id in a **pydantic body field** is neither a handler parameter nor a
    dependency, so `TestEveryIntParameterFromTheOutsideIsBounded` walks straight
    past it. Three endpoints answered **500** to `2**63` for exactly that
    reason, all member reachable and all older than collections:
    `POST /api/books/bulk`, `POST /api/books/merge` and `POST /api/loans`.

    **Scoped to models a route actually accepts**, not to every model under
    `schemas/`. Response models are full of ints that come from the database
    rather than from a caller (`BookOut.id`, `Page.total`, every `count`), and
    bounding those would be noise standing in front of the rule. A model is in
    scope when a route handler annotates a parameter with it, plus any model
    reached from an in-scope model's own fields, which is how a nested body
    would be caught.

    What counts as bounded is what counts everywhere else: a `Field(...)` or
    equivalent carrying one of `ge`/`gt` and one of `le`/`lt`, directly or
    through `RowIdField`. `# unbounded ok:` opts out, and `BulkRequest.value`
    uses it: it is genuinely not a row id, and its handlers range-check per verb.

    Only int-shaped fields are the question. A `str` bound by `max_length` is a
    different rule, and a `float` cannot overflow the driver.

    Measured on the tree as it stands: **69** models under `schemas/`, **28** of
    them reachable from a request.

    Those two numbers are read back out of this paragraph by
    `test_the_stated_model_counts_are_the_measured_ones`, because the previous
    pair (54 and 22) was stale by the time anybody noticed: it had drifted
    silently through at least two features before a reviewer recomputed it. A
    number in prose that nothing checks is a number that is eventually wrong,
    and this file exists precisely to stop a defect being found a third time by
    a person.
    """

    def _model_bases(self, node: ast.ClassDef) -> set[str]:
        return {base.id for base in node.bases if isinstance(base, ast.Name)}

    def _schema_models(self, sources: dict[Path, str]) -> dict[str, ast.ClassDef]:
        """Every pydantic model under `schemas/`, by name.

        **A subclass of a model is a model**, resolved to a fixed point, and
        that is not hypothetical tidiness: `CollectionUpdate(CollectionCreate)`
        is the body of `PATCH /api/collections/{id}` and has `BaseModel` nowhere
        in its bases, so a literal test for that name leaves it out of the rule
        entirely. It carries one string today, which is the only reason nothing
        escaped through it.

        Same shape as the alias chain above and the same fix. It terminates for
        the same reason: the set only grows.
        """
        candidates: dict[str, ast.ClassDef] = {}
        for path, text in sources.items():
            if "schemas" not in path.parts:
                continue
            for node in ast.walk(ast.parse(text)):
                if isinstance(node, ast.ClassDef):
                    candidates[node.name] = node

        models: dict[str, ast.ClassDef] = {}
        changed = True
        while changed:
            changed = False
            for name, node in candidates.items():
                if name in models:
                    continue
                bases = self._model_bases(node)
                if "BaseModel" in bases or bases & models.keys():
                    models[name] = node
                    changed = True
        return models

    def _body_models(
        self, sources: dict[Path, str], models: dict[str, ast.ClassDef]
    ) -> set[str]:
        """Models a route handler takes as a parameter, transitively.

        Transitive through **fields**, because a body model may hold another one
        and a field on the inner model is as reachable from a request as a field
        on the outer; and through **bases**, because a subclass body inherits
        every field its parent declares and those arrive in the same JSON.
        Nothing in the tree nests one today; the worklist is three lines and the
        alternative is a rule that silently stops applying the first time
        somebody does.
        """
        reached: set[str] = set()
        pending: list[str] = []

        for _path, text in sources.items():
            for node in ast.walk(ast.parse(text)):
                if not isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
                    continue
                if not _is_route_handler(node):
                    continue
                for argument in node.args.args + node.args.kwonlyargs:
                    for child in ast.walk(argument.annotation) if argument.annotation else ():
                        if isinstance(child, ast.Name) and child.id in models:
                            pending.append(child.id)

        while pending:
            name = pending.pop()
            if name in reached:
                continue
            reached.add(name)
            pending.extend(self._model_bases(models[name]) & models.keys())
            for statement in models[name].body:
                if not isinstance(statement, ast.AnnAssign) or statement.annotation is None:
                    continue
                for child in ast.walk(statement.annotation):
                    if isinstance(child, ast.Name) and child.id in models:
                        pending.append(child.id)
        return reached

    def _offenders(self, sources: dict[Path, str]) -> list[str]:
        """The rule itself, over source text rather than over the tree.

        Separated for the reason the parameter rule was: the guards below have
        to drive **this**, not its collectors. Asserting that a collector holds
        a name is how the first hole survived a test that passed.
        """
        models = self._schema_models(sources)
        in_scope = self._body_models(sources, models)
        offenders: list[str] = []

        for path, text in sources.items():
            if "schemas" not in path.parts:
                continue
            lines = text.splitlines()
            for node in ast.walk(ast.parse(text)):
                if not isinstance(node, ast.ClassDef) or node.name not in in_scope:
                    continue
                for statement in node.body:
                    if not isinstance(statement, ast.AnnAssign):
                        continue
                    annotation = statement.annotation
                    if not _mentions_int(annotation):
                        continue
                    named = {
                        child.id
                        for child in ast.walk(annotation)
                        if isinstance(child, ast.Name)
                    }
                    if "RowIdField" in named:
                        continue
                    assigned = statement.value
                    if any(
                        _is_bounding_call(child) for child in ast.walk(annotation)
                    ) or (assigned is not None and _is_bounding_call(assigned)):
                        continue
                    if "unbounded ok:" in _preceding_comment_block(
                        lines, statement.lineno
                    ):
                        continue
                    field = statement.target
                    label = field.id if isinstance(field, ast.Name) else "?"
                    offenders.append(
                        f"{path.relative_to(BACKEND)}:{statement.lineno} ({node.name}.{label})"
                    )
        return sorted(offenders)

    def test_the_stated_model_counts_are_the_measured_ones(self) -> None:
        """The docstring's two numbers, recomputed.

        The same habit as `test_serialisation.py`'s
        `test_the_number_in_the_docstring_is_the_number_it_costs`, which reads
        its count back out of the docstring rather than trusting it.
        Growing either number is fine; growing it without updating the sentence
        a reader believes is not.
        """
        sources = {path: path.read_text() for path in _python_sources()}
        models = self._schema_models(sources)
        in_scope = self._body_models(sources, models)

        stated = re.search(
            r"\*\*(\d+)\*\* models under `schemas/`, \*\*(\d+)\*\* of\s+them reachable",
            self.__doc__ or "",
        )
        assert stated is not None, "the class docstring no longer states both counts"
        assert (int(stated.group(1)), int(stated.group(2))) == (
            len(models),
            len(in_scope),
        ), (
            f"the docstring says {stated.group(1)} models and "
            f"{stated.group(2)} reachable; the tree has "
            f"{len(models)} and {len(in_scope)}"
        )

    def test_every_int_a_request_body_carries_is_bounded(self) -> None:
        offenders = self._offenders(
            {path: path.read_text() for path in _python_sources()}
        )

        assert not offenders, (
            "These request-body ints are unbounded, so a value past SQLite's INTEGER "
            "reaches the driver and turns into a 500:\n  "
            + "\n  ".join(offenders)
            + "\nUse `RowIdField` (schemas/common.py) for a row id, a Field with ge and "
            "le otherwise, or add an `# unbounded ok:` comment saying why not."
        )

    #: A router module and a schemas module, because a model is declared in one
    #: and accepted in the other, which is what the two fixed points are for.
    ROUTER = BACKEND / "probe_router.py"
    SCHEMAS = BACKEND / "schemas" / "probe_schemas.py"

    def _probe(self, models: str, body: str = "Body") -> list[str]:
        return self._offenders(
            {
                self.SCHEMAS: models + "\n",
                self.ROUTER: (
                    "@router.post('/thing')\n"
                    f"def probe(payload: {body}) -> None: ...\n"
                ),
            }
        )

    def test_the_guard_would_notice_an_unbounded_body_int(self) -> None:
        """A guard that cannot fail is not a guard. This is the shape three
        endpoints had when they answered 500 to `2**63`."""
        assert self._probe("class Body(BaseModel):\n    book_id: int") == [
            "schemas/probe_schemas.py:2 (Body.book_id)"
        ]

    def test_the_guard_would_notice_one_inherited_from_a_model_subclass(self) -> None:
        """The case the fixed point exists for. `Body(Parent)` names no
        `BaseModel`, so a literal test for that base leaves the body out of
        scope altogether and every field it declares goes unchecked. This is
        `CollectionUpdate(CollectionCreate)`, which is a real request body.
        """
        assert self._probe(
            "class Parent(BaseModel):\n    pass\n\n"
            "class Body(Parent):\n    book_id: int"
        ) == ["schemas/probe_schemas.py:5 (Body.book_id)"]

    def test_the_guard_checks_the_fields_a_body_inherits(self) -> None:
        """The other direction of the same edge: a subclass body arrives
        carrying its parent's fields, so the parent is in scope too even though
        no handler names it."""
        assert self._probe(
            "class Parent(BaseModel):\n    book_id: int\n\n"
            "class Body(Parent):\n    pass"
        ) == ["schemas/probe_schemas.py:2 (Parent.book_id)"]

    def test_the_guard_accepts_a_bounded_body_int(self) -> None:
        """Or the rule above could be satisfied by reporting every field."""
        assert (
            self._probe(
                "class Body(BaseModel):\n    book_id: int = Field(ge=1, le=9)"
            )
            == []
        )

    def test_the_guard_leaves_a_response_model_alone(self) -> None:
        """No handler takes it as a parameter, so its ints come from the
        database rather than from a caller. Scoping this wrongly would bury the
        rule in `BookOut.id` and every count in the app."""
        assert (
            self._probe(
                "class Body(BaseModel):\n    pass\n\n"
                "class Out(BaseModel):\n    id: int"
            )
            == []
        )

    def test_the_guard_sees_the_models_a_route_takes(self) -> None:
        """The scope is the load-bearing half: too narrow and the rule inspects
        nothing, which is a green test that checks the empty set."""
        sources = {path: path.read_text() for path in _python_sources()}
        models = self._schema_models(sources)
        in_scope = self._body_models(sources, models)

        assert {
            "BulkRequest",
            "MergeRequest",
            "LoanCreate",
            "BookCreate",
            # Subclass of `CollectionCreate`, and absent from this set until the
            # base-class fixed point landed.
            "CollectionUpdate",
        } <= in_scope
        # And not the response models, which is what keeps the rule readable.
        assert "BookOut" not in in_scope
        assert "Page" not in in_scope


class TestProvenanceColumnsAreNeverRead:
    """A column recorded only so somebody can be asked later is never consulted
    by code.

    One entry, and it is here because three places in the tree say of
    `collections.created_by_user_id` that "no query consults it, which is what
    keeps that true rather than merely intended" while nothing kept it true. A
    claim of mechanism with no mechanism is worse than no claim: the next reader
    believes it.

    What it protects is the separation the collections feature turns on. A
    collection is shelving and never permission, and the way that quietly stops
    being true is somebody filtering or authorising on who made one. The privacy
    rule itself is pinned by `tests/test_models.py`; this pins the weaker
    promise beside it.

    **Attribute access is the test**, not the name. Writing the column is a
    keyword argument (`Collection(created_by_user_id=...)`) and declaring it is
    an assignment target, so neither is an `ast.Attribute`; every read of it,
    whether `row.created_by_user_id` or `Collection.created_by_user_id` in a
    filter, is one. If a genuine reason to read one ever arrives, delete the
    entry here and the three sentences it stands for, in the same commit.
    """

    #: Column, and where the promise about it is written down.
    #: The match is by **name, across the whole tree**, and deliberately so: an
    #: instance read (`row.created_by_user_id`) has no statically resolvable
    #: owner, so keying on the model would miss the dominant shape. The cost is
    #: that a second model given this conventional column name inherits the rule
    #: and fails with a message pointing at `Collection`. That is a rename or an
    #: entry here, not a bug, and knowing it is the difference between a
    #: two-minute fix and an afternoon.
    PROVENANCE_COLUMNS = {
        "created_by_user_id": "models.Collection, docs/decisions.md, docs/data-model.md",
    }

    def test_no_module_reads_a_provenance_column(self) -> None:
        offenders: list[str] = []

        for path in _python_sources():
            tree = ast.parse(path.read_text())
            for node in ast.walk(tree):
                if not isinstance(node, ast.Attribute):
                    continue
                if node.attr not in self.PROVENANCE_COLUMNS:
                    continue
                offenders.append(f"{path.relative_to(BACKEND)}:{node.lineno} ({node.attr})")

        assert not offenders, (
            "These read a column recorded as provenance only, and something in the tree "
            "promises nothing does:\n  "
            + "\n  ".join(sorted(offenders))
            + "\nEither stop reading it, or delete the promise where "
            + "; ".join(f"{column}: {where}" for column, where in self.PROVENANCE_COLUMNS.items())
            + "."
        )

    def test_the_column_is_still_there_to_be_unread(self) -> None:
        """The rule above passes just as well if somebody deletes the column, so
        this says which absence would be the wrong one."""
        from models import Collection

        assert "created_by_user_id" in Collection.__table__.columns


class TestTheBoundsActuallyRefuse:
    """The rule above is a lint; these are the behaviours it stands for.

    Both were 500s before the bound existed, and a 500 is the app calling its
    own code buggy over a value the caller chose. 422 is the honest answer.
    """

    def test_an_absurd_page_number_is_refused_not_a_500(self, client, admin) -> None:
        response = client.get(
            "/api/books",
            params={"page": 9_999_999_999_999_999_999_999},
            headers=admin["headers"],
        )
        assert response.status_code == 422

    #: A path segment past SQLite's INTEGER. Every one of these answered **500**
    #: before the parameters were bounded, measured on the runner.
    TOO_BIG = 9_223_372_036_854_775_808

    #: One case per route rather than a loop, so a failure names the route in
    #: the test id instead of stopping at the first one and hiding the rest.
    #: Worth the four lines: this exact test was reported failing in a whole
    #: file run and passing alone, and a loop makes that report unactionable.
    @pytest.mark.parametrize(
        ("method", "path"),
        [
            ("get", "/api/books/{id}"),
            ("delete", "/api/books/tags/{id}"),
            ("patch", "/api/collections/{id}"),
            ("delete", "/api/collections/{id}"),
        ],
    )
    def test_a_path_id_past_the_databases_range_is_refused_not_a_500(
        self, client, admin, method: str, path: str
    ) -> None:
        """Each id reaches `db.get()` or a filter, and an int past 2**63-1
        raises `OverflowError` from inside it. Two of these predate collections
        and were found by the same review."""
        url = path.format(id=self.TOO_BIG)
        request = getattr(client, method)
        response = (
            request(url, json={"name": "Ebooks"}, headers=admin["headers"])
            if method == "patch"
            else request(url, headers=admin["headers"])
        )

        assert response.status_code == 422, response.text

    def test_the_largest_accepted_id_still_reaches_the_handler(
        self, client, admin
    ) -> None:
        """The bound must refuse what the database cannot hold and nothing else.
        No row has this id, so the honest answer is 404, not 422."""
        from schemas.common import MAX_ROW_ID

        response = client.get(f"/api/books/{MAX_ROW_ID}", headers=admin["headers"])

        assert response.status_code == 404

    #: `{book}` is filled in with a real book's id where the route needs one.
    #: Parametrised for the reason above.
    @pytest.mark.parametrize(
        ("url", "payload"),
        [
            (
                "/api/books/bulk",
                {"book_ids": [TOO_BIG], "action": "set_status", "value": "read"},
            ),
            ("/api/books/merge", {"book_ids": ["{book}", TOO_BIG], "keep_id": "{book}"}),
            ("/api/loans", {"book_id": TOO_BIG, "loaned_to_name": "a neighbour"}),
            ("/api/books/{book}/enrich/apply", {"title": "Dune", "year": TOO_BIG}),
        ],
    )
    def test_a_body_row_id_past_the_databases_range_is_refused_not_a_500(
        self, client, admin, make_book, url: str, payload: dict
    ) -> None:
        """The other door. Each of these was measured as an `OverflowError` and
        a 500, reachable by any member, and none of them is a path parameter or
        a query parameter, so the lint above walks straight past them."""
        book = make_book(admin["headers"], title="Dune")
        filled = {
            key: (
                book["id"]
                if value == "{book}"
                else [book["id"] if item == "{book}" else item for item in value]
                if isinstance(value, list)
                else value
            )
            for key, value in payload.items()
        }

        response = client.post(
            url.format(book=book["id"]), json=filled, headers=admin["headers"]
        )

        assert response.status_code == 422, response.text

    def test_the_largest_accepted_page_still_works(self, client, admin) -> None:
        from dependencies import MAX_PAGE_NUMBER

        response = client.get(
            "/api/books", params={"page": MAX_PAGE_NUMBER}, headers=admin["headers"]
        )
        assert response.status_code == 200
        assert response.json()["items"] == []

#: The names an `HTTPException` can be constructed under in this tree.
#:
#: `main.py` and `errors.py` both import Starlette's under an alias, so a rule
#: matching the bare name sees neither.
_HTTP_EXCEPTION_NAMES = frozenset({"HTTPException", "StarletteHTTPException"})


def _http_exception_aliases(tree: ast.Module) -> set[str]:
    """Every local name in one module that means an HTTP exception class.

    Resolves `from fastapi import HTTPException as HE` the way
    `test_shelf.py::_book_aliases` resolves the `Book` model, which is the
    resolver this one is copied from. The attribute form
    (`fastapi.HTTPException(...)`) is handled at the call instead, since it
    binds no local name.
    """
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import | ast.ImportFrom):
            for alias in node.names:
                if alias.name in _HTTP_EXCEPTION_NAMES:
                    names.add(alias.asname or alias.name)
    return names


def _walk_outside_lambdas(node: ast.AST):
    """Every node inside this expression, not entering a `Lambda` body.

    A lambda body runs per call, exactly as a function body does, so an
    exception built inside one is fresh each time.
    """
    pending: list[ast.AST] = [node]
    while pending:
        current = pending.pop()
        yield current
        # Not descended into, and the check is on `current` rather than on its
        # children because the assigned value can itself be the lambda:
        # `_MK = lambda: HTTPException(404)` hands this function the `Lambda`
        # node directly.
        if isinstance(current, ast.Lambda):
            continue
        pending.extend(ast.iter_child_nodes(current))


def _constructs_http_exception(node: ast.AST, names: set[str]) -> bool:
    """Whether an expression constructs an HTTP exception anywhere inside it.

    **Anywhere**, not just at the top: `_ERRORS = {"nf": HTTPException(...)}`
    and `_A, _B = HTTPException(...), HTTPException(...)` both hide the call
    one level down, and both share the instance exactly as a bare assignment
    does.
    """
    # A `Lambda` is not descended into: `_MK = lambda: HTTPException(404)` is a
    # factory that builds a fresh instance per call, which is the approved
    # shape, and walking through it reported the approved shape as an offence.
    for child in _walk_outside_lambdas(node):
        if not isinstance(child, ast.Call):
            continue
        func = child.func
        if isinstance(func, ast.Name) and func.id in names:
            return True
        if isinstance(func, ast.Attribute) and func.attr in _HTTP_EXCEPTION_NAMES:
            return True
    return False


def _executed_once(tree: ast.Module):
    """Every statement that runs once, at import or at class definition.

    The module body and the class bodies inside it, descending through `if`,
    `try` and `with` but never into a function. A statement inside a function
    runs per call, and an exception built there is fresh each time.
    """
    pending: list[ast.AST] = list(tree.body)
    while pending:
        node = pending.pop()
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            continue
        yield node
        if isinstance(node, ast.ClassDef):
            pending.extend(node.body)
            continue
        pending.extend(
            child for child in ast.iter_child_nodes(node) if isinstance(child, ast.stmt)
        )
        # An `except` clause is an `ExceptHandler`, not a statement, so the
        # filter above drops it and its whole body with it. Measured: the body
        # of a module level `try` was inspected and its handler was not, while
        # the docstring and the fixture both claimed `try` was covered.
        if isinstance(node, ast.Try):
            pending.extend(
                statement for handler in node.handlers for statement in handler.body
            )


class TestNoExceptionInstanceIsShared:
    """House rule: an `HTTPException` is constructed where it is raised.

    A shared instance re-raised per request appends a frame to its
    `__traceback__` at **every** raise and never releases it, so each refusal
    permanently pins that frame's locals. On the routes this was found on that
    meant a `Session` and a `User` row, password hash included, per 404.
    Measured on the author route: 20 requests took the traceback from 0 to 180
    frames and retained 20 handler frames. Sync handlers also run in a
    threadpool, so two concurrent refusals mutate one object's `__traceback__`
    and `__cause__`.

    Found by a critic on `routers/books.py`, where a refactor had just
    introduced one, and `dependencies.py` turned out to have had the same
    defect at three higher traffic sites since it was written. Writing the rule
    then found a **third** in `routers/covers.py` with five raise sites, which
    is the worst of them: a cover 404 is ordinary rather than exceptional. That
    is why this is a rule rather than two fixes.

    **Its blind spots**, because a guard whose limits are undocumented is read
    as a guarantee it never made:

    * A factory decorated with `@lru_cache` returns one instance forever and
      looks exactly like the approved fix. Nothing here can see that.
    * An instance built at import time and stashed on something this rule does
      not walk: a class attribute reached through a call, a module `__getattr__`,
      a mutable default mutated later.
    * Any exception class this rule does not name. It tests HTTP exceptions
      because those are the ones raised per request; a shared `ValueError`
      raised in a loop has the same defect and is not covered, and so is a
      subclass (`class NotFound(HTTPException)`).
    * A `global` assigned from an `_init()` that import time calls, or a helper
      that returns one instance. Both are the `@lru_cache` case by another
      route.
    * A decorator argument, and a walrus inside a bare expression statement.
      Measured by the security seat as the only two remaining shapes it could
      construct; neither is a shape anybody writes, and widening the walk to
      reach them was refused on that.

    Both fixtures below guard the other direction, because a rule that reports
    the approved shape is worse than no rule: a factory `def` and a `lambda`
    both build fresh per call and must stay silent.
    """

    #: Shapes that must be reported. Asserted per shape, because a rule with no
    #: test that fails when it is removed is not enforced: mistyping the class
    #: name would leave every assertion below green against a clean tree.
    #:
    #: Ten of these eleven passed the first version of this rule, which matched
    #: `ast.Name` at `tree.body` only. Measured by the security seat.
    EVASIONS = {
        "bare name": "from fastapi import HTTPException\n_NF = HTTPException(404)\n",
        "attribute form": "import fastapi\n_NF = fastapi.HTTPException(404)\n",
        "import alias": "from fastapi import HTTPException as HE\n_NF = HE(404)\n",
        "starlette alias": (
            "from starlette.exceptions import HTTPException as StarletteHTTPException\n"
            "_NF = StarletteHTTPException(404)\n"
        ),
        "inside a dict": "from fastapi import HTTPException\n_E = {'nf': HTTPException(404)}\n",
        "tuple unpacking": (
            "from fastapi import HTTPException\n_A, _B = HTTPException(404), HTTPException(403)\n"
        ),
        "annotated": (
            "from fastapi import HTTPException\n_NF: HTTPException = HTTPException(404)\n"
        ),
        "class attribute": (
            "from fastapi import HTTPException\nclass E:\n    NOT_FOUND = HTTPException(404)\n"
        ),
        "default argument": (
            "from fastapi import HTTPException\ndef f(exc=HTTPException(404)):\n    raise exc\n"
        ),
        "inside a try": (
            "from fastapi import HTTPException\ntry:\n    _NF = HTTPException(404)\n"
            "except Exception:\n    _NF = None\n"
        ),
        "inside a list": "from fastapi import HTTPException\n_E = [HTTPException(404)]\n",
        "inside an except handler": (
            "from fastapi import HTTPException\ntry:\n    x = 1\n"
            "except Exception:\n    _NF = HTTPException(404)\n"
        ),
    }

    @staticmethod
    def _offenders(name: str, source: str) -> list[str]:
        """Statements that build an exception **once** and hand it out repeatedly.

        Only nodes that execute once are inspected: the module body, class
        bodies inside it, and the default arguments of any function. A function
        **body** is deliberately not walked, because a local built there is
        fresh on every call, which is the approved fix. `auth.py:201,247` are
        exactly that shape and were reported by a version of this rule that
        walked everything.
        """
        tree = ast.parse(source)
        names = _http_exception_aliases(tree)
        found = []

        for node in _executed_once(tree):
            if (
                isinstance(node, ast.Assign | ast.AnnAssign)
                and node.value is not None
                and _constructs_http_exception(node.value, names)
            ):
                found.append(f"{name}:{node.lineno}")

        # Anywhere, including nested: a default argument is evaluated once when
        # the `def` runs, so an exception built there is as shared as a global.
        for node in ast.walk(tree):
            if not isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
                continue
            defaults = [d for d in [*node.args.defaults, *node.args.kw_defaults] if d]
            if any(_constructs_http_exception(d, names) for d in defaults):
                found.append(f"{name}:{node.lineno}")

        return sorted(set(found))

    @pytest.mark.parametrize("shape", sorted(EVASIONS))
    def test_the_rule_catches_every_shape_that_shares_an_instance(self, shape: str) -> None:
        assert self._offenders("probe.py", self.EVASIONS[shape]), f"{shape} evades the rule"

    #: Shapes that build fresh per call and must never be reported. A rule that
    #: reports the approved fix is worse than no rule.
    APPROVED = {
        "factory function": (
            "from fastapi import HTTPException\n"
            "def _not_found() -> HTTPException:\n"
            "    return HTTPException(404)\n"
        ),
        "lambda factory": "from fastapi import HTTPException\n_MK = lambda: HTTPException(404)\n",
        "local in a function": (
            "from fastapi import HTTPException\n"
            "def f():\n"
            "    exc = HTTPException(404)\n"
            "    raise exc\n"
        ),
    }

    @pytest.mark.parametrize("shape", sorted(APPROVED))
    def test_the_rule_does_not_report_a_shape_that_builds_fresh(self, shape: str) -> None:
        assert self._offenders("probe.py", self.APPROVED[shape]) == [], shape

    def test_no_module_shares_an_http_exception_instance(self) -> None:
        offenders = [
            hit
            for path in _python_sources()
            for hit in self._offenders(path.name, path.read_text())
        ]
        assert offenders == [], (
            "These modules hold an HTTPException instance rather than building one "
            "at the raise. Raising a shared one grows its traceback forever and pins "
            f"the locals of every frame it passed through: {offenders}"
        )


class TestNoDatabaseFoldIsComparedAgainstAPythonFold:
    """`func.lower(Column) == value` is one comparison written as two different
    functions.

    Measured: `lower('Ästhetik')` is `'Ästhetik'` in SQLite and `'ästhetik'` in
    Python. Three instances of this have been found by hand, two of them 500s
    (`importing.Import`, `routers/books.create_tag`) and one a quiet duplicate
    that needed a migration to undo (`routers/collections`, issue #77). Every
    one was mechanically visible, which is why it is a test now.

    **A comparison is the test, not the call.** `func.lower` in an `ORDER BY`
    is fine: it decides sort order rather than identity, and no fold moves an
    accented letter anyway. Folding both sides in Python and comparing a stored
    column is the shape that replaced all three.
    """

    #: SQL functions that fold case. `upper` is here because the mirror image
    #: is the same defect, and cheaper to forbid now than to find later.
    FOLDING_FUNCTIONS = frozenset({"lower", "upper"})

    def _folds_in_sql(self, node: ast.AST) -> bool:
        for child in ast.walk(node):
            if not isinstance(child, ast.Call):
                continue
            called = child.func
            if not isinstance(called, ast.Attribute):
                continue
            if called.attr not in self.FOLDING_FUNCTIONS:
                continue
            owner = called.value
            if isinstance(owner, ast.Name) and owner.id == "func":
                return True
        return False

    def test_no_module_compares_a_sql_fold(self) -> None:
        offenders: list[str] = []

        for path in _python_sources():
            tree = ast.parse(path.read_text())
            for node in ast.walk(tree):
                if not isinstance(node, ast.Compare):
                    continue
                sides = [node.left, *node.comparators]
                if any(self._folds_in_sql(side) for side in sides):
                    offenders.append(f"{path.relative_to(BACKEND)}:{node.lineno}")

        assert not offenders, (
            "These compare a fold the database performs, which is ASCII only, against a "
            "value folded somewhere else. Fold both sides in Python, or compare a stored "
            f"folded column: {sorted(offenders)}"
        )

    def test_an_order_by_is_not_reported(self) -> None:
        """The rule has to leave `list_collections` alone, which still orders by
        `func.lower(Collection.name)` on purpose."""
        tree = ast.parse("rows = query.order_by(func.lower(Collection.name)).all()")

        assert not any(
            isinstance(node, ast.Compare) and self._folds_in_sql(node.left)
            for node in ast.walk(tree)
        )

    def test_the_rule_reports_the_shape_it_exists_for(self) -> None:
        """A rule nothing can fail is a rule nobody notices deleting."""
        tree = ast.parse("query.filter(func.lower(Collection.name) == name.lower())")

        comparisons = [node for node in ast.walk(tree) if isinstance(node, ast.Compare)]

        assert comparisons and self._folds_in_sql(comparisons[0].left)


class TestOnlyOneHelperTurnsForeignKeysOff:
    """`PRAGMA foreign_keys=OFF` on a pooled connection leaks to the next test.

    This cost a full suite run to find, and the reason it was expensive is the
    reason this rule exists rather than a comment. The suite runs `-n 2` with
    per-test distribution, so whether the polluted connection reaches
    `TestSqlitePragmas` is chance: every file passed on its own, and the full
    run failed two tests that neither change had touched.

    A grep would not do, because the defect is not writing the pragma, it is
    writing it **without discarding the connection afterwards**. Requiring the
    one helper is the cheap way to say that: the helper owns the `invalidate()`,
    and anything spelling the pragma inline has by definition not called it.

    **Blind spots, listed rather than left to be found.** The scan reads string
    literals, so a pragma assembled at runtime dodges it: `"foreign_keys" + "=0"`
    is two `ast.Constant` nodes and neither carries the match, which is how
    `KEY` and `OFF` are written here without tripping the rule. So does a name
    passed in from elsewhere, and so does any spelling SQLite accepts that this
    does not enumerate.

    That is deliberate rather than unnoticed. The failure mode being guarded is
    a future test copying the line already in the tree, and the cost of an
    evasion is a test running with foreign keys unenforced, which is fidelity
    rather than a hole in the app: no production path writes this pragma off,
    and `database.py` sets it `ON` on every connect. A rule that caught every
    spelling would need to run SQL rather than read source.
    """

    #: Squeezed and lowercased before matching, and written apart so this file
    #: does not trip its own rule.
    KEY = "foreign_keys"
    #: Everything SQLite accepts as off. `= 0` is exactly as silent as `=OFF`.
    OFF = ("off", "0", "false", "no")
    #: Both separators SQLite takes: `PRAGMA foreign_keys=0` and the function
    #: form `PRAGMA foreign_keys(0)`.
    SEPARATORS = ("=", "(")

    def _turns_foreign_keys_off(self, value: str) -> bool:
        squeezed = "".join(value.split()).lower()
        return any(
            self.KEY + separator + off in squeezed
            for separator in self.SEPARATORS
            for off in self.OFF
        )

    def test_no_test_writes_the_pragma_outside_the_helper(self) -> None:
        offenders: list[str] = []
        for path in _test_sources():
            tree = ast.parse(path.read_text())
            allowed = {
                node
                for parent in ast.walk(tree)
                if isinstance(parent, ast.FunctionDef | ast.AsyncFunctionDef)
                and parent.name == _FOREIGN_KEYS_OFF_HELPER
                for node in ast.walk(parent)
            }
            # Docstrings are prose, not statements, and a rule that cannot be
            # written down without tripping itself gets deleted rather than
            # obeyed. This class's own docstring names the pragma.
            allowed |= _docstring_nodes(tree)
            # And the class stating the rule, whose fixtures are six spellings
            # of the very thing it forbids. It opens no connection, so there is
            # nothing here for the rule to catch; the exclusion is the same
            # shape as the allowlist in `test_shelf.py`, named rather than
            # implicit.
            allowed |= {
                node
                for parent in ast.walk(tree)
                if isinstance(parent, ast.ClassDef)
                and parent.name == type(self).__name__
                for node in ast.walk(parent)
            }
            for node in ast.walk(tree):
                if (
                    isinstance(node, ast.Constant)
                    and isinstance(node.value, str)
                    and self._turns_foreign_keys_off(node.value)
                    and node not in allowed
                ):
                    offenders.append(f"{path.relative_to(BACKEND)}:{node.lineno}")

        assert not offenders, (
            f"These turn foreign keys off on a pooled connection. Use "
            f"{_FOREIGN_KEYS_OFF_HELPER}, which discards the connection "
            f"afterwards, or the next test to check it out runs with every "
            f"foreign key unenforced: {sorted(offenders)}"
        )

    def test_the_helper_still_discards_the_connection(self) -> None:
        """The rule points every caller at one helper, so the helper doing the
        discarding is the whole of what makes it safe."""
        source = (BACKEND / "tests" / "test_schema.py").read_text()
        tree = ast.parse(source)
        helper = next(
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.FunctionDef)
            and node.name == _FOREIGN_KEYS_OFF_HELPER
        )

        assert any(
            isinstance(node, ast.Attribute) and node.attr == "invalidate"
            for node in ast.walk(helper)
        )

    @pytest.mark.parametrize(
        "spelling",
        [
            "PRAGMA foreign_keys=OFF",
            "PRAGMA foreign_keys = OFF",
            "PRAGMA foreign_keys=0",
            "pragma foreign_keys=off",
            "PRAGMA main.foreign_keys=OFF",
            "PRAGMA foreign_keys(0)",
        ],
    )
    def test_the_rule_reports_every_spelling_it_exists_for(self, spelling) -> None:
        """A rule nothing can fail is a rule nobody notices deleting, and a
        rule matching one spelling of six is a rule that reads as enforcement
        and is not. Every one of these leaves the pragma at 0."""
        assert self._turns_foreign_keys_off(spelling)

    def test_turning_them_back_on_is_not_reported(self) -> None:
        """The rule has to leave `database.py`'s own `PRAGMA foreign_keys=ON`
        alone, and `on` starts with neither `off` nor a digit."""
        assert not self._turns_foreign_keys_off("PRAGMA foreign_keys=ON")
        assert not self._turns_foreign_keys_off("PRAGMA foreign_keys = 1")
