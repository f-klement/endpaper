"""`COVERAGE.md` states what the run reading it collected.

**The register is checked against the suite it describes, never recounted.** Its
headline, its shortfall and every row's count were maintained by hand until
2026-09-20, and on that day the headline was 102 out, one row 3 out and the
shortfall 99 out, on a tree whose last commit said all three had just been
recounted off one run with two instruments. Three parties recounted this file in
two days and each left a different figure wrong. The defect is none of those
numbers: it is that a register whose whole purpose is to be checkable was
maintained by retyping figures.

**The instrument is the run itself**, which is why nothing here shells out to a
second pytest and no figure is written down below. `session.items` is the
collection this process is executing, so a file's count cannot disagree with the
run unless something narrowed it, and the `whole_tree` fixture refuses the
comparison when that has happened.

**The descriptions are the point of the register and are never generated.** What
each file covers is what a person writes and is most of what the document is
worth. So the row set is read out of the document and only the column beside it
is recomputed, which is the arrangement the generated depth table in this
repository's architecture decisions already uses.

**Some of the collected files may appear in the register nowhere**, because the
publish gate strips them and a published file that points at a stripped path
fails the gate. How many is in the generated block and not in this sentence,
which is the rule this file exists to enforce, applied to itself. That number
is derived from the declaration an internal file carries, which the gate
refuses to publish, rather than from a list of names this published file could
not carry either.

**A file this engine cannot run is a third destination, spelled as a row of 0.**
`DATABASE_SSL_MODE` against a real server is a property of Postgres, so that file
ends its own collection on SQLite and is in the tree with nothing in the run. It
carries a description like any other row and states the count the run took, which
is none. **It counts among the rows, adds nothing to their sum, and is not among
the files the headline counts**, because the headline counts what was collected.

**Those are two questions crossed rather than three slots in a row**: may this
register name the file, and does this engine run it. The fourth cell is a file
the register may not name that this engine does not run, which can carry no row
because a published register naming a stripped path fails the publish gate. It
is read off the file instead, in `_excused`.
"""

from __future__ import annotations

import ast
import json
import os
import re
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from fnmatch import fnmatch
from pathlib import Path

import pytest

from tests.test_house_rules import _test_sources
from tests.test_roster_counts import declares_itself_internal

TESTS = Path(__file__).resolve().parent
REGISTER = TESTS / "COVERAGE.md"

#: The generated block's fences, spelled as the depth table's are, because a
#: reader who has seen one should recognise the other.
BEGIN = "<!-- measured: begin -->"
END = "<!-- measured: end -->"

#: A row of the table: a backticked path in the first cell, a count in the
#: second. Both are matched inside their own cell, which is the distinction the
#: roster census had to learn the hard way: a number reached across a `|` is a
#: claim about the next column.
_ROW = re.compile(r"^\|[ \t]*`([^`]+)`[ \t]*\|[ \t]*(\d+)[ \t]*\|", re.MULTILINE)


def rows(text: str) -> list[tuple[str, int]]:
    """Every row of the register's table, in the document's own order."""
    return [(path, int(count)) for path, count in _ROW.findall(text)]


def _rows_of_zero(table: list[tuple[str, int]]) -> frozenset[str]:
    """Which rows of a read table state 0.

    One home, because `render` had the same comprehension written out again
    and the two were free to drift.
    """
    return frozenset(path for path, count in table if count == 0)


def not_collected_here(text: str) -> frozenset[str]:
    """The files the register records as collecting nothing on this engine.

    **A row of 0, which is the count such a file honestly has here.** It is a
    statement in the document rather than a property of the run, which is what
    keeps `_refusal` from having to recognise a way a run can be narrowed.
    Two arms outside that gate hold the document to it.
    """
    return _rows_of_zero(rows(text))


#: The `pytest` functions a module body can call to end its own collection.
#:
#: **Closed, so this is a completed set rather than the enumeration this file
#: otherwise refuses.** `skip` and `importorskip` are the whole module level
#: pair: `exit` ends the session rather than the module, and a marker leaves
#: the file collected and its tests reported. Nothing a reader adds here
#: reaches a spelling the parse below cannot see, which is why no comment here
#: offers this tuple as a remedy for one. The sentence that did was false for
#: every spelling that can occur.
_ENDS_COLLECTION = ("skip", "importorskip")


def _pytest_bindings(tree: ast.Module) -> tuple[frozenset[str], dict[str, str]]:
    """What this module calls `pytest`, and what it calls `pytest`'s own skips.

    **The names the module binds, read off its imports, never the receiver
    written at the call.** `node.func.value.id == "pytest"` stood here and
    answered False for `import pytest as pt`, for `from pytest import skip`
    and for either of those under an alias. Every one of them ends a module's
    collection and none of them writes `pytest` at the call, so no edit to
    `_ENDS_COLLECTION` could ever have reached one.

    The first set is the names bound to the module itself. The second maps
    every name bound straight out of `pytest` onto the attribute it is, so an
    alias is read under the name it aliases. **Every name and not only the
    skips**, because the fixture marker is read through the same two
    spellings and a second walk for it would be the same rule twice.
    """
    modules: set[str] = set()
    functions: dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules |= {
                alias.asname or alias.name
                for alias in node.names
                if alias.name == "pytest"
            }
        elif (
            isinstance(node, ast.ImportFrom)
            and node.module == "pytest"
            and not node.level
        ):
            functions |= {
                alias.asname or alias.name: alias.name for alias in node.names
            }
    return frozenset(modules), functions


def _skip_called(
    node: ast.AST, modules: frozenset[str], functions: dict[str, str]
) -> str | None:
    """Which of `_ENDS_COLLECTION` this node calls under this module's names.

    **`allow_module_level` is required of `skip`, and requiring it is what
    makes the answer about collection.** Without it pytest raises `Failed:
    Using pytest.skip outside of a test is not allowed`, which ends the run
    rather than the module, so such a file is a red run and not a row of 0.
    The predicate answered True for it, which is a false accept rather than a
    miss: it would have let a row of 0 excuse a file that breaks the run.

    A literal `False` for that keyword is the same error as omitting it, so it
    is refused here too; any other value is accepted, because what it resolves
    to is not in this parse.
    """
    if not isinstance(node, ast.Call):
        return None
    func = node.func
    if (
        isinstance(func, ast.Attribute)
        and isinstance(func.value, ast.Name)
        and func.value.id in modules
    ):
        name = func.attr if func.attr in _ENDS_COLLECTION else None
    elif isinstance(func, ast.Name) and functions.get(func.id) in _ENDS_COLLECTION:
        name = functions[func.id]
    else:
        name = None
    if name != "skip":
        return name
    allowed = next(
        (word.value for word in node.keywords if word.arg == "allow_module_level"),
        None,
    )
    if allowed is None or (isinstance(allowed, ast.Constant) and not allowed.value):
        return None
    return name


def _can_end_its_own_collection(path: Path) -> bool:
    """Whether this file's module body can stop itself being collected.

    **The module body only.** The same call inside a test is a test skipping
    itself, which `test_nothing_collected_is_skipped_or_left_expected_to_fail`
    refuses, and reading the two as one would let that refusal be evaded by
    writing the skip one level out.

    **Off the parse, and it raises rather than answering False on a file it
    cannot read.** A `False` there would report a clean tree out of a broken
    instrument, and the only files asked are ones the walk just found.

    **What no parse of one file can answer is a call to a helper that skips**,
    whether the helper is in this file's imports or three modules away: the
    name bound at the call is the helper's, and what the helper does is not in
    this parse. Such a file answers False, so a row of 0 for it is refused
    rather than accepted, which is the direction that fails loud at the line
    where somebody writes the row. None is in this tree.
    """
    tree = ast.parse(path.read_text(encoding="utf-8"))
    modules, functions = _pytest_bindings(tree)
    return any(
        _skip_called(node, modules, functions) is not None
        for statement in tree.body
        if not isinstance(
            statement, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)
        )
        for node in ast.walk(statement)
    )


def _collector_reads(name: str, patterns: Sequence[str]) -> bool:
    """Whether the collector would read this name under those patterns.

    **Prefix first and glob second, which is pytest's own rule and not
    `fnmatch` alone.** `python_functions` defaults to `test`, with no glob
    character in it, so an `fnmatch` here matches only a function called
    exactly `test` and reports a file full of tests as holding none. Measured:
    that spelling reddened
    `test_a_row_of_zero_names_a_file_this_engine_cannot_run` on a correct tree,
    which is a fix refusing something that was never broken.
    """
    return any(
        name.startswith(pattern)
        or (any(mark in pattern for mark in "*?[") and fnmatch(name, pattern))
        for pattern in patterns
    )


def _switched_off(body: list[ast.stmt]) -> bool:
    """Whether this body sets `__test__` to anything but a truthy constant.

    The collector asks it of a module, a class and an instance alike, as the
    first line of `PyCollector.collect` and again in `Class.collect`, and a
    falsy answer removes everything under it.

    **Anything that is not a truthy constant counts as off**, including a name
    this parse cannot resolve. That refuses a file whose declaration is
    computed, which is the loud direction: it reds at the line where somebody
    writes a row of 0 rather than excusing a file that collects nothing.
    """
    for statement in body:
        if isinstance(statement, ast.Assign):
            targets: list[ast.expr] = list(statement.targets)
            value: ast.expr | None = statement.value
        elif isinstance(statement, ast.AnnAssign):
            targets, value = [statement.target], statement.value
        else:
            continue
        if value is None:
            continue
        for target in targets:
            if (
                isinstance(target, ast.Name)
                and target.id == "__test__"
                and not (isinstance(value, ast.Constant) and value.value)
            ):
                return True
    return False


def _has_a_constructor(body: list[ast.stmt]) -> bool:
    """Whether this class body defines `__init__` or `__new__`.

    `Class.collect` refuses such a class outright, with a warning and no
    items, so a test inside one is a test nothing runs anywhere. **It is one
    of the six ways a name the collector reads still collects nothing**, every
    one of which this predicate answered True for until two review seats drove
    collection against planted files.

    **A constructor inherited from a base class in another module is outside
    this parse**, and `hasinit` sees one. Such a class answers True here and
    its tests are counted, which is the accepting direction; closing it needs
    the imported object rather than the syntax.
    """
    return any(
        isinstance(statement, (ast.FunctionDef, ast.AsyncFunctionDef))
        and statement.name in {"__init__", "__new__"}
        for statement in body
    )


def _is_a_fixture(
    node: ast.FunctionDef | ast.AsyncFunctionDef,
    modules: frozenset[str],
    functions: dict[str, str],
) -> bool:
    """Whether a decorator on this function is pytest's fixture marker.

    `istestfunction` requires `getfixturemarker(obj) is None`, so a fixture
    whose name the collector would otherwise read is collected as nothing.
    Read through the same bindings the skip predicate uses, bare or called,
    so an alias and a `from` import are both seen. **A marker a third party
    package re-exports is not**, because the name it binds comes from
    somewhere this parse does not read.
    """
    for decorator in node.decorator_list:
        named = decorator.func if isinstance(decorator, ast.Call) else decorator
        if isinstance(named, ast.Name) and functions.get(named.id) == "fixture":
            return True
        if (
            isinstance(named, ast.Attribute)
            and isinstance(named.value, ast.Name)
            and named.value.id in modules
            and named.attr == "fixture"
        ):
            return True
    return False


def _rooted_at(node: ast.expr) -> str | None:
    """The name a decorator expression is rooted at, or `None`.

    `@pytest.mark.parametrize(...)` is rooted at `pytest`, through a call, an
    attribute and an attribute. Anything not ending at a plain name has no
    root here and is therefore not recognised, which is the refusing
    direction.
    """
    while True:
        if isinstance(node, ast.Call):
            node = node.func
        elif isinstance(node, (ast.Attribute, ast.Subscript)):
            node = node.value
        else:
            break
    return node.id if isinstance(node, ast.Name) else None


def _decorated_past_recognition(
    node: ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef,
    modules: frozenset[str],
    functions: dict[str, str],
) -> bool:
    """Whether a decorator here is rooted outside this module's own `pytest`.

    **A decorator replaces the name it decorates with whatever it returns**,
    so a decorated class the collector would otherwise read can collect
    nothing while every rule in this file passes. Measured by collection: a
    decorated test class collects none, and so does a decorated module level
    test function. **The whitelist did not see it**, because definitions were
    skipped by kind with no look at their decorators, and a planted file
    holding the guarded skip and one decorated class took the whole arm set
    green.

    **Read from the bindings rather than from a literal**, as the skip
    predicate is, so an alias of the module is recognised and a third party
    decorator is not.

    **Where it applies, and why it stops there.** A class at any depth and a
    top level function: censused free, every decorator on such a definition
    in this tree is rooted at `pytest` and no nested protected class carries
    one at all. **Not a test method**, where the same rule would refuse 70
    decorators in this corpus, property based generation and a transport
    mock among them. A method whose decorator returns something the collector
    does not read is therefore still accepted, and is named in the residue
    at `_declares_a_test`.
    """
    recognised = modules | set(functions)
    return any(
        _rooted_at(decorator) not in recognised for decorator in node.decorator_list
    )


def _defined_more_than_once(
    body: list[ast.stmt],
) -> list[ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef]:
    """Definitions after the first of any name a module body binds twice.

    The second wins and the first is gone, so a class redefined under a name
    the collector reads can lose its tests to a later definition that carries
    a falsy declaration. Measured by collection, and censused free: no file
    in this corpus defines a top level name twice.
    """
    seen: set[str] = set()
    repeats: list[ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef] = []
    for statement in _reachable_definitions(body):
        if statement.name in seen:
            repeats.append(statement)
        seen.add(statement.name)
    return repeats


def _reachable_definitions(
    body: list[ast.stmt],
) -> list[ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef]:
    """Definitions a module body reaches, through conditionals and `try`.

    The same traversal `_unrecognised` makes, so a definition it reads
    through is a definition this counts.
    """
    found: list[ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef] = []
    for statement in body:
        if isinstance(
            statement, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)
        ):
            found.append(statement)
        elif isinstance(statement, ast.If):
            found += _reachable_definitions(statement.body)
            found += _reachable_definitions(statement.orelse)
        elif isinstance(statement, ast.Try):
            for section in (
                statement.body,
                statement.orelse,
                statement.finalbody,
                *(handler.body for handler in statement.handlers),
            ):
                found += _reachable_definitions(section)
    return found


def _declared_tests(
    body: list[ast.stmt],
    names: Sequence[str],
    classes: Sequence[str],
    modules: frozenset[str],
    functions: dict[str, str],
    *,
    top_level: bool = True,
) -> Iterator[str]:
    """Every function in this body the collector would read as a test.

    Module level and inside a class the collector would read, which is where
    it looks. A `def test_x` written inside a helper function is not a test
    and is not yielded.

    **The name is where the collector starts and not where it stops**, so a
    class it refuses for its constructor or its own declaration is not
    descended, and a fixture is not yielded.

    **Dotted, so each test carries the module level name that owns it.** A
    bare method name cannot say whose it is, and the module level statement
    that disowns a class has to take the class's tests with it: without the
    prefix, rebinding a `Test` class left its methods counted and a planted
    file answered True with nothing collectable in it. Found by this file's
    own probe one round after the six it was written for.
    """
    for statement in body:
        if isinstance(statement, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if (
                _collector_reads(statement.name, names)
                and not _is_a_fixture(statement, modules, functions)
                and not (
                    top_level
                    and _decorated_past_recognition(statement, modules, functions)
                )
            ):
                yield statement.name
        elif isinstance(statement, ast.ClassDef) and _collector_reads(
            statement.name, classes
        ):
            if (
                _switched_off(statement.body)
                or _has_a_constructor(statement.body)
                or _decorated_past_recognition(statement, modules, functions)
            ):
                continue
            for inner in _declared_tests(
                statement.body, names, classes, modules, functions, top_level=False
            ):
                yield f"{statement.name}.{inner}"


def _disowned(body: list[ast.stmt], owners: set[str]) -> set[str]:
    """Module level names a later statement puts out of the collector's reach.

    The collector reads the module's `__dict__` after the module has run, so
    a `def test_one` rebound afterwards is not there, and `test_one.__test__ =
    False` is read off the object the name now holds. Both are ordinary
    module level assignments and neither changes how the `def` is spelled.

    **Any rebinding counts, not only one to a non test.** Rebinding to another
    function would leave a test collected, and nothing in this parse can say
    which; refusing is the direction that reds at the row rather than
    excusing a file.

    **A test method is rebound the same way its owner is**, so the attribute
    is what the special case is about rather than the ownership:
    `TestThing.test_one = None` collects nothing, measured by collection, and
    the first version of this read only `__test__` there and answered that
    the file declares a test. The declared names are dotted for this reason,
    so an attribute rebinding joins the set under `owner.attribute` and the
    bare owner is left alone.
    """
    gone: set[str] = set()
    for statement in body:
        if not isinstance(statement, (ast.Assign, ast.AnnAssign)):
            continue
        targets = (
            statement.targets if isinstance(statement, ast.Assign) else [statement.target]
        )
        for target in targets:
            if isinstance(target, ast.Name) and target.id in owners:
                gone.add(target.id)
            elif (
                isinstance(target, ast.Attribute)
                and isinstance(target.value, ast.Name)
                and target.value.id in owners
            ):
                if target.attr != "__test__":
                    gone.add(f"{target.value.id}.{target.attr}")
                elif not (
                    isinstance(statement.value, ast.Constant) and statement.value.value
                ):
                    gone.add(target.value.id)
    return gone


def _declares_a_test(path: Path, names: Sequence[str], classes: Sequence[str]) -> bool:
    """Whether this file defines anything the collector reads as a test.

    **The half of a row of 0 that is about the file rather than the engine.**
    The row says this engine does not run the file; a file with nothing in it
    runs nowhere, and the 0 then buys it a permanent excuse. Driven by a review
    seat before this existed: a planted `test_*.py` holding a module level skip
    and no tests took a row of 0, opened the gate, ran all three count arms,
    and left the whole suite green with nothing anywhere saying so.

    **Both name rules come from the collector's own configuration**, the way
    `Census.of` reads `python_files`, rather than from `test` and `Test`
    written here.

    **The name is not the whole of the collector's question, and reading only
    the name reproduced the same fail open at exit 0.** Two review seats drove
    collection against planted files and found six spellings a name rule
    passes and the collector collects nothing from: a class with `__init__`,
    a class with `__new__`, `__test__` falsy on the module, on the class or on
    the function, a declared name rebound afterwards, and the fixture marker.
    One of them, a module level skip beside a `Test` class carrying
    `__test__ = False`, took a whole planted suite green with its row of 0
    unchallenged. Each is refused above.

    **What still needs the object rather than the syntax**, and is accepted
    here: an abstract class, which `Class.collect` asks `inspect.isabstract`;
    a constructor inherited from a base class in another module; a plugin's
    own collector; and a test a hook generates or a base class supplies,
    which is declared nowhere in this file and is refused instead. The first
    three are the accepting direction and are not closable by a parse.

    **Two more that are accepted here, and both are conceded rather than
    overlooked.** A builtin that reaches the namespace is refused by name in
    an assignment's value, and reaching one through a string subscript walks
    past that rule, because the rule reads names and attributes and the
    builtin is then spelled as a constant. The two cheap tightenings cost
    more than the door: refusing a subscript in a value hits 26 assignments
    in this corpus and refusing a call hits 250, so neither is paid for.
    And a **test method** whose decorator returns something the collector
    does not read, where the rule that covers a class and a top level
    function would refuse 70 decorators here, property based generation and
    a transport mock among them. **What that one costs, stated rather than
    implied**: a file whose only test is such a method collects nothing,
    raises no refusal anywhere, takes a row of 0, opens the gate, runs the
    three count arms and leaves the suite green. A concession that
    understates what it concedes is not one.

    **The difference between those and a decorator on a class is the whole
    rule for reading this list.** A gap the prose already concedes has a
    witness; a gap nothing anywhere mentioned is a finding. Nothing said a
    definition's decorators went unexamined, which is why that one was
    blocking and these two are written down.

    **The declaration is read in three places and only one of its two
    directions is.** A falsy value empties a module, a class or a function
    here; a **truthy** one on a name the pattern does not read makes the
    collector take it anyway, and this answers False for that. A class or a
    function named outside `python_classes` and `python_functions` and
    switched on by hand is therefore refused rather than counted, which is
    the loud direction. Censused: no module in this tree names that attribute
    at all, so the family is empty rather than handled.
    """
    tree = ast.parse(path.read_text(encoding="utf-8"))
    if _switched_off(tree.body):
        return False
    modules, functions = _pytest_bindings(tree)
    declared = set(_declared_tests(tree.body, names, classes, modules, functions))
    # A module level statement reaches a module level name, so each test is
    # asked about under the name that owns it rather than its own.
    gone = _disowned(tree.body, {name.split(".")[0] for name in declared})
    return any(
        name not in gone and name.split(".")[0] not in gone for name in declared
    )


#: Builtins that reach a module's own namespace, so a statement naming one of
#: them is refused rather than read further. **Closed and small on purpose**:
#: what it bounds is the reach of an ordinary expression, and a miss here is
#: the accepting direction, which is why the whitelist below does not rest on
#: it alone.
_REACHES_THE_NAMESPACE = frozenset(
    {"setattr", "delattr", "globals", "vars", "locals", "exec", "eval", "__dict__"}
)


def _names_written_down(node: ast.expr) -> set[str]:
    """Every name and attribute this expression spells."""
    return {
        inner.id if isinstance(inner, ast.Name) else inner.attr
        for inner in ast.walk(node)
        if isinstance(inner, (ast.Name, ast.Attribute))
    }


def _reaches(node: ast.expr | None) -> str | None:
    """The module level name a target or an argument is rooted at.

    Through attributes and subscripts, so `TestThing.x[0].y` is rooted at
    `TestThing`, and through a call, so `globals()[...]` is rooted at
    `globals`.
    """
    return None if node is None else _rooted_at(node)


def _written_to(tree: ast.Module, protected: set[str]) -> list[str]:
    """Every place in this module that binds or writes a protected name.

    **The whole module, at any depth, and this is what closes the family.**
    The whitelist reads containers: the module body, both branches of a
    conditional, all four sections of a `try`, and a protected class body,
    refusing `for`, `while`, `with`, `match` and `try` star by kind. Two
    containers it does not read, because reading them would refuse almost
    every helper this tree has: a non protected class body and a function
    body. Both execute at import with the whole module namespace in reach,
    and five instances were driven to nothing collected, nothing refused and
    silenced true: a helper class rebinding a test, a helper function doing
    it under a bare assignment, the same reached by a decorator on an
    unprotected function, a helper class body rebinding a nested protected
    class, and the helper called from a default argument.

    **So this rule is not about containers at all.** A mutation has to be
    written somewhere as a binding, and the ways Python binds a name are a
    closed set the grammar gives. Enumerated against it:

    | how a name is bound | here |
    |---|---|
    | assignment, annotated, augmented, deletion | the target's root, below |
    | a walrus | the target, below |
    | an import, with an alias or without | the name it binds, below |
    | a star import | refused outright, below, because what it binds is unreadable here |
    | an `except` handler's name | below |
    | `global` or `nonlocal`, then any binding form | the declaration, below |
    | a call that writes a namespace, `setattr` and its kin | below |
    | a `for`, `with` or `match` target, at module level | the container, refused by kind |
    | a parameter or a comprehension target | binds where nothing collects, accepted |
    | a local, or an unprotected class's attribute, shadowing one | refused, a false refusal |
    | a `def` or a `class` | the definition rules and `_defined_more_than_once` |
    | a `type` statement | refused by kind, like any other unrecognised one |
    | a type parameter | binds in the definition's own scope |

    **The walrus was in this table discharged by a sentence and the sentence
    was wrong.** It read that the value rule catches one, which holds only
    where the walrus sits inside a statement that rule scans. A definition is
    accepted by kind, and its default arguments, its decorator arguments and
    its base expressions are scanned by nothing while all three evaluate at
    import in module scope. Driven: a walrus in a default argument and in a
    decorator argument each gave no refusal and a silenced file, and so did
    one in a class base, which rebinds rather than raising. It is a refusal
    now rather than a discharge.

    **The rows still discharged rather than refused each have a driven
    witness**, because a row discharged by prose is exactly what the walrus
    was: `test_a_container_that_can_rebind_is_refused_by_kind` and
    `test_a_binding_the_collector_never_reads_leaves_the_test`, the second
    reading the module's own namespace after executing it rather than this
    file's parse of it.

    **And writing that second witness split its row, which is the same
    lesson a third time.** The row said a parameter, a comprehension target
    and a local all bind where the collector never reads. The first two do
    and are accepted. A **local** assignment is an assignment, so this walk
    refuses it when it shadows a protected name, and so is an attribute of
    an unprotected class. That is a false refusal rather than a discharge:
    it is censused free and it is loud. **The row was wrong and the witness
    found it**, where reading it twice had not.

    **Telling a local from a module write needs a scope aware walk, and the
    reason not to write one is the failure direction rather than the cost.**
    Cost is an argument the first reader overturns when the machinery looks
    cheap. What does not move is that a syntactic refusal is wrong **loudly**
    and a scope analysis is wrong **silently**, because its whole job is to
    decide that a binding does not reach module scope. That decision has been
    wrong eight times on this branch, three of them in rows this table had
    already discharged. Trading a loud false refusal for an analysis whose
    errors are silent inverts the one property holding all of this up.

    **Censused over every collected module: no offender of any kind**, the
    walrus included at 29 of them, none binding a protected name.

    **What is left open after this is not a container and not a binding.** It
    is the expression boundary, a namespace builtin reached as a string
    rather than named, which `_declares_a_test` already concedes with its
    cost. That is a different shape, and it is the difference between closing
    an instance and closing a class.

    **What the witnesses buy is that each row is falsifiable, not that the
    table is right.** A row that stops holding now goes red on its own
    rather than waiting for somebody to disbelieve the sentence under it.
    What they cannot do is say the list is complete, so the residue is not
    that a row might be wrong, it is that **a row might be missing**. That is
    not a theoretical worry: the star import row was missing, and it was
    found by planting one round after this paragraph first claimed the list
    was closed.

    **How it was found is the part worth copying, because it is the method
    and not the warning.** Nobody reasoned their way to the star import by
    thinking harder about this table. It turned up by planting against a
    population the author had not thought to vary: every earlier plant bound
    a name the planter chose, and this one let the import decide what it
    bound. So the way to find the next missing row is to vary the thing the
    table takes for granted, not to re-read the rows that already have
    witnesses.
    """
    found: list[str] = []
    for node in ast.walk(tree):
        at = getattr(node, "lineno", 0)
        if isinstance(node, (ast.Assign, ast.AnnAssign, ast.AugAssign, ast.Delete)):
            targets = (
                node.targets
                if isinstance(node, (ast.Assign, ast.Delete))
                else [node.target]
            )
            flat: list[ast.expr] = []
            for target in targets:
                flat += (
                    list(target.elts)
                    if isinstance(target, (ast.Tuple, ast.List))
                    else [target]
                )
            found += [
                f"a write to {_reaches(target)} at line {at}"
                for target in flat
                if _reaches(target) in protected | _REACHES_THE_NAMESPACE
            ]
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            found += [
                f"an import binding {alias.asname or alias.name} at line {at}"
                for alias in node.names
                if (alias.asname or alias.name.split(".")[0]) in protected
            ]
            # **A star import binds names this file cannot read**, so there is
            # nothing to compare against the protected set: the clause above
            # reads the alias or the first segment, which for a star is the
            # star. Refused outright wherever a protected name exists, which
            # is the only honest answer when the binding is unreadable.
            if protected and any(alias.name == "*" for alias in node.names):
                found += [f"a star import at line {at}"]
        elif (
            isinstance(node, ast.NamedExpr)
            and isinstance(node.target, ast.Name)
            and node.target.id in protected
        ):
            found += [f"a walrus binding {node.target.id} at line {at}"]
        elif isinstance(node, ast.ExceptHandler) and node.name in protected:
            found += [f"an except handler binding {node.name} at line {at}"]
        elif isinstance(node, (ast.Global, ast.Nonlocal)):
            found += [
                f"a global declaration of {name} at line {at}"
                for name in node.names
                if name in protected
            ]
        elif isinstance(node, ast.Call) and _rooted_at(node.func) in _REACHES_THE_NAMESPACE:
            found += [
                f"a namespace call on {_reaches(argument)} at line {at}"
                for argument in node.args
                if _reaches(argument) in protected
            ]
    return found


def _members_the_collector_reads(
    cls: ast.ClassDef, names: Sequence[str], classes: Sequence[str]
) -> set[str]:
    """What a protected class body must not rebind: its tests and its nested
    protected classes."""
    return {
        statement.name
        for statement in cls.body
        if (
            isinstance(statement, (ast.FunctionDef, ast.AsyncFunctionDef))
            and _collector_reads(statement.name, names)
        )
        or (
            isinstance(statement, ast.ClassDef)
            and _collector_reads(statement.name, classes)
        )
    }


def _unrecognised(
    body: list[ast.stmt],
    modules: frozenset[str],
    functions: dict[str, str],
    protected: set[str],
    names: Sequence[str],
    classes: Sequence[str],
) -> list[ast.stmt]:
    """Statements in a module body this file does not recognise.

    **A whitelist, because the thing it bounds has no last member.** Four
    earlier rounds each closed the way of putting a test out of the
    collector's reach that had just been demonstrated, and the next round
    found another: a rebinding, an attribute rebinding, a tuple target, a
    deletion, a dynamic set, an alias, a nested class, a namespace write.
    Measured by collection, eleven spellings and no reason to think that is
    all of them. An enumeration of ways to disown cannot be finished; an
    enumeration of ways to declare can.

    So a module body that may carry a row of 0 is a docstring, imports,
    definitions, `pass`, a guarded skip, and assignments that touch nothing
    the collector will look for. A conditional and a `try` are read through,
    so their contents are held to the same rule rather than excused by it.

    **The one permissive kind is constrained by the names it touches rather
    than by a list of ways to misuse it**, which is what keeps this from
    being the blacklist again: every target must be a plain name or a tuple
    of them, none of those names may be a test or an owner of one, and the
    value may name neither. An attribute target, a subscript target, a
    deletion and a bare call are refused by kind.

    **The one collision worth naming, because the refusal reads as a defect
    in the reader's own code otherwise.** A class body that derives a set
    from another class's namespace, which is this repository's own *derive
    it and assert it* idiom, names a namespace builtin and is refused here.
    It only bites if that file is given a row of 0, which needs it to stop
    collecting on this engine, and the one file in that shape has no engine
    dependency at all. Nothing in that file mentions this rule, so this
    sentence is the only place the two meet.

    **A protected class body is read the same way**, with its own tests and
    nested protected classes added to the set no statement may touch. It was
    skipped by kind, which is the construction that has now blocked twice: a
    class body holds exactly the statements this list refuses at module
    level, and measured by collection a test assigned, deleted or replaced
    after its own `def` collects nothing, raises no refusal and answers
    silenced.

    **Measured over the whole collected corpus**, five files hold a statement
    this does not recognise: a type alias, two module level assertions, a
    class body aliasing another test class, and a derived frozenset reading
    another class's namespace. None of them carries a row of 0, and the
    refusal arrives at the line where somebody writes one, which is where the
    recognised set gets extended by whoever needs it. No count of the corpus
    stands here: it moves with every file added and would be read as current
    long after it stopped being so.
    """
    found: list[ast.stmt] = []
    for statement in body:
        if isinstance(
            statement,
            (ast.Import, ast.ImportFrom, ast.FunctionDef, ast.AsyncFunctionDef, ast.Pass),
        ):
            continue
        if isinstance(statement, ast.ClassDef):
            # A class the collector does not read holds nothing it will look
            # for, so its body is not this rule's business. One it does read
            # is entered with its own members added to the protected set.
            if _collector_reads(statement.name, classes):
                found += _unrecognised(
                    statement.body,
                    modules,
                    functions,
                    protected | _members_the_collector_reads(statement, names, classes),
                    names,
                    classes,
                )
            continue
        if isinstance(statement, ast.Expr):
            if isinstance(statement.value, ast.Constant) and isinstance(
                statement.value.value, str
            ):
                continue
            if _skip_called(statement.value, modules, functions) is not None:
                continue
        elif isinstance(statement, ast.If):
            if _names_written_down(statement.test) & (
                protected | _REACHES_THE_NAMESPACE
            ):
                found.append(statement)
                continue
            found += _unrecognised(
                statement.body, modules, functions, protected, names, classes
            )
            found += _unrecognised(
                statement.orelse, modules, functions, protected, names, classes
            )
            continue
        elif isinstance(statement, ast.Try):
            for section in (
                statement.body,
                statement.orelse,
                statement.finalbody,
                *(handler.body for handler in statement.handlers),
            ):
                found += _unrecognised(
                    section, modules, functions, protected, names, classes
                )
            continue
        elif isinstance(statement, (ast.Assign, ast.AnnAssign)):
            targets = (
                statement.targets
                if isinstance(statement, ast.Assign)
                else [statement.target]
            )
            bound: list[str] = []
            plain = True
            for target in targets:
                for part in (
                    target.elts
                    if isinstance(target, (ast.Tuple, ast.List))
                    else [target]
                ):
                    if isinstance(part, ast.Name):
                        bound.append(part.id)
                    else:
                        plain = False
            touched = (
                _names_written_down(statement.value)
                if statement.value is not None
                else set()
            )
            if (
                plain
                and not set(bound) & protected
                and not touched & (protected | _REACHES_THE_NAMESPACE)
            ):
                continue
        found.append(statement)
    return found


def _statements_that_could_reach_a_test(
    path: Path, names: Sequence[str], classes: Sequence[str]
) -> list[str]:
    """What a module body carrying a row of 0 may not hold, named by line.

    The gate for a row of 0; `_disowned` is the reason for it rather than
    the gate. That branch answers precisely for the three spellings anybody
    writes and keeps `_declares_a_test` honest on its own terms, and this is
    what makes the family closed.
    """
    tree = ast.parse(path.read_text(encoding="utf-8"))
    modules, functions = _pytest_bindings(tree)
    protected = {
        statement.name
        for statement in tree.body
        if (
            isinstance(statement, (ast.FunctionDef, ast.AsyncFunctionDef))
            and _collector_reads(statement.name, names)
        )
        or (isinstance(statement, ast.ClassDef) and _collector_reads(statement.name, classes))
    }
    return [
        f"{type(statement).__name__} at line {statement.lineno}"
        for statement in _unrecognised(
            tree.body, modules, functions, protected, names, classes
        )
    ] + [
        f"{statement.name} defined again at line {statement.lineno}"
        for statement in _defined_more_than_once(tree.body)
    ] + _written_to(tree, protected)


def _is_silenced_by_the_engine(
    path: Path, names: Sequence[str], classes: Sequence[str]
) -> bool:
    """Whether a file collecting nothing here is this engine's doing.

    Both halves, because a row of 0 claims both: that the file has tests, and
    that what stops them here is a property of the engine. Either half alone is
    satisfied by a file no engine runs at all.

    **What this cannot ask is whether the condition is ever false.** A module
    level skip that runs on every engine, and a condition true on every engine,
    both answer True here and both make the row's claim wrong. Deciding that
    needs the other engine rather than the syntax, and the only place it is
    written down is the handful of paths the pipeline's `test:postgres` job
    names by hand.

    **A third condition, and it is what bounds the second.** A module body
    carrying a row of 0 must be built only from statements
    `_statements_that_could_reach_a_test` recognises. Without it the second
    half is an open list of ways to disown a test: four rounds each closed
    the spelling just demonstrated and the next found another, eleven in all,
    measured by collection. The whitelist turns that into a closed list of
    ways to declare one.

    **The two halves read the module at different depths, and that is a seam
    rather than a decision.** The skip half walks every statement under the
    module body, where this half reads the top level and the class bodies
    under it, which is what the collector reads. So a `def test_one` written
    under a module level `if` answers False while a skip written beside it
    answers True, and the pair then refuses a row of 0 on a file that
    deserves one. Censused empty on this tree. **The repair is not to deepen
    this half**, which would start counting tests the collector never sees: it
    is that the collector reads the module after it has run and no parse of
    either depth is that.
    """
    return (
        not _statements_that_could_reach_a_test(path, names, classes)
        and _declares_a_test(path, names, classes)
        and _can_end_its_own_collection(path)
    )


def split(text: str) -> tuple[str, str, str]:
    """The document either side of the generated block.

    A missing fence raises rather than yielding an empty block: a guard whose
    input has gone missing has stopped guarding, and this one would otherwise
    pass by comparing nothing with nothing.
    """
    if BEGIN not in text or END not in text:
        raise AssertionError(
            f"{REGISTER.name} carries no measured block. Expected {BEGIN} and {END}."
        )
    head, rest = text.split(BEGIN, 1)
    block, tail = rest.split(END, 1)
    return head, block, tail


def _files(number: int) -> str:
    return f"{number} file" if number == 1 else f"{number} files"


def _rows(number: int) -> str:
    return f"{number} row" if number == 1 else f"{number} rows"


@dataclass(frozen=True)
class Census:
    """What the running suite collected, by file.

    **Collected tests, not `def test_` lines**, which come to fewer: a
    parametrised case is one line and several tests. Collected is the unit the
    register's rows are stated in, and `test_the_census_counts_cases_rather_than
    _functions` is what says the difference is real.
    """

    counts: dict[str, int]
    #: Every file in the tree whose name the collector reads as a test module,
    #: whether or not this run kept it. The two differ when a run was narrowed
    #: and when a file ends its own collection, which is the distinction
    #: `_excused` is handed the register to make.
    #:
    #: **Its own arming is beside the walk it comes from**, in
    #: `test_house_rules::TestTheTestTreeIsStillTheTestTree`, because a
    #: narrowing written there takes this whole comparison quiet rather than
    #: red: `counts` reads `session.items` and this reads the shared walk, so
    #: the two disagree and a disagreement is handed to `pytest.skip`.
    on_disk: frozenset[str]
    #: The collector's `python_functions` and `python_classes`, carried so
    #: that `_declares_a_test` asks the question this run was collected under
    #: rather than one spelled here. `on_disk` reads `python_files` for the
    #: same reason.
    test_names: tuple[str, ...]
    test_classes: tuple[str, ...]

    @classmethod
    def of(cls, session: pytest.Session) -> Census:
        counts: dict[str, int] = {}
        for item in session.items:
            where = Path(item.path).relative_to(TESTS).as_posix()
            counts[where] = counts.get(where, 0) + 1
        # The naming rule is read from the configuration rather than written
        # here. A project that renamed its test files would otherwise leave this
        # set empty and every completeness check passing on nothing.
        patterns = session.config.getini("python_files")
        return cls(
            counts=counts,
            on_disk=frozenset(
                path.relative_to(TESTS).as_posix()
                for path in _test_sources()
                if any(fnmatch(path.name, pattern) for pattern in patterns)
            ),
            test_names=tuple(session.config.getini("python_functions")),
            test_classes=tuple(session.config.getini("python_classes")),
        )

    def silent(self, excused: frozenset[str]) -> list[str]:
        """Files the walk has that this run did not collect and nothing excuses.

        A narrowed run, or a file collecting no test and carrying no row of 0.
        """
        return sorted((set(self.on_disk) - excused) - set(self.counts))

    def unexpected(self, excused: frozenset[str]) -> list[str]:
        """Files this run collected that the walk did not offer it.

        The walk going wrong, or a row of 0 on a file this engine does run.
        **The two sides are kept apart because they are two different faults**
        and one message used to serve both.
        """
        return sorted(set(self.counts) - (set(self.on_disk) - excused))

    @property
    def total(self) -> int:
        return sum(self.counts.values())

    def unnamed(self, named: list[str]) -> list[str]:
        return sorted(set(self.counts) - set(named))


def render(census: Census, table: list[tuple[str, int]]) -> str:
    """The block the register carries, from one run's own figures.

    Three numbers rather than one, because the register's whole arithmetic is
    the identity between them: the headline, less the tests in the files that
    cannot be named, is what the rows sum to. Rendering all three from one
    census makes that identity hold by construction, where the register used to
    state it and ask the reader to check.

    **A fourth, because the file counts stopped adding up the day a row stated
    0.** The headline counts what the run collected and a file this engine
    cannot run is not in it, so rows plus unnamed files came to one more than
    the headline with nothing in the block saying why. The identity a reader
    can now check is that the rows, less the ones stating 0, plus the unnamed
    files, are the headline's files.
    """
    named = [path for path, _ in table]
    unnamed = census.unnamed(named)
    shortfall = sum(census.counts[path] for path in unnamed)
    # One spelling of "a row of 0", shared with the gate and with the two arms
    # that hold the document to it. The comprehension was written out again
    # here, which is one rule in two places with one of them free to drift.
    recorded = _rows_of_zero(table)
    return (
        f"\n\n**{census.total} tests, in {_files(len(census.counts))}**, counted by the "
        "run that reads this line.\n"
        f"**The {_rows(len(table))} below sum to {census.total - shortfall}.**\n"
        f"The other {shortfall} tests are in {_files(len(unnamed))} this register may "
        "not name.\n"
        f"The table also carries {_files(len(recorded))} this engine does not run, "
        "stated as 0.\n"
    )


#: The word a run prints in front of the write it measured, so that a separate
#: invocation can apply it.
#:
#: **Every figure in that write is this run's own.** A writer that recomputed
#: them would be a second instrument, and a second instrument agrees with this
#: one on almost every tree: the run where the two disagree is the run nobody
#: is watching, and the register would then carry a figure no suite ever took.
#: So what travels is the finished text, and what applies it carries no census
#: at all.
#:
#: **Three files spell this word and none of them can import another.** The
#: frontend half of the register is TypeScript and the applier is a script
#: under a directory this published file may not name as a path. The three are
#: held equal by an arm in the internal guard that reads all three, which is
#: the only place that can.
WRITE_SENTINEL = "COVERAGE-REGISTER-WRITE"

#: This register, named from the repository root the way the write names it.
#: Derived, so a moved register does not leave a literal pointing at nothing.
#:
#: **Derived from this module's location, which is safe here only because
#: nothing spawns a nested run of this suite.** The frontend half of this
#: rule derives the same constant the same way and is not safe: that suite
#: runs whole vitest children over fixture libraries, and a child importing
#: its guard named the real register while carrying the fixture's figures.
#: Its reporter now asks whether the run's own register is the module's
#: before offering a write at all. **The two halves therefore look symmetric
#: and are not**, and this paragraph is here so the next reader does not copy
#: the simpler one into a tree that has grown a fixture runner.
REGISTER_PATH = REGISTER.relative_to(TESTS.parent.parent).as_posix()


@dataclass(frozen=True)
class WriteInstruction:
    """The whole of what a run would change in the register, as text.

    **Lines rather than figures, and that is what keeps the applier honest.**
    Handing it a count would make it find the cell, which is a second spelling
    of this file's row grammar and free to drift from it. Handing it the line
    the document has today and the line this run would write instead makes the
    application a byte replacement with no grammar in it, and a document whose
    line has moved under the write is a refusal by name rather than a wrong
    cell.
    """

    register: str
    #: The text between the fences, or `None` where this run is offering no
    #: block at all, which is every write carrying a refusal.
    block: str | None
    lines: tuple[tuple[str, str], ...]
    #: What this run measured and will not write, with the reason. A register
    #: carrying one of these is left alone entirely: every refusal here is a
    #: cell whose own arm is red for a reason a new number would paper over.
    refused: tuple[str, ...]

    def payload(self) -> str:
        """The one line a run prints, which is the whole write."""
        return WRITE_SENTINEL + " " + json.dumps(
            {
                "register": self.register,
                "block": self.block,
                "lines": [list(pair) for pair in self.lines],
                "refused": list(self.refused),
            },
            sort_keys=True,
        )


def _restated(register: str, match: re.Match[str], counted: int) -> tuple[str, str]:
    """A row's line as the document has it, and as this run would write it.

    **The digits are replaced where they sit and nothing else on the line is
    touched**, so a description a person wrote survives a write that corrects
    the number beside it. The row grammar is read once, here, off the same
    expression every other rule in this file reads.

    **No padding is reproduced, deliberately.** One of the two registers is
    formatted by prettier, which pads this column to a fixed width, so a write
    that changes a count's digit count leaves that file needing the formatter
    the gate already runs last. Reproducing the alignment here would be a
    second implementation of the formatter's rule in two languages, and its
    failure would be silent; forgetting the formatter fails `format:check` by
    name.
    """
    ends = register.find("\n", match.start())
    line = register[match.start() :] if ends < 0 else register[match.start() : ends]
    at = match.start(2) - match.start()
    through = match.end(2) - match.start()
    return line, line[:at] + str(counted) + line[through:]


def write_instruction(census: Census, register: str) -> WriteInstruction | None:
    """What this run would write into the register, or `None` when it is current.

    **Rendered from the census every rule above is checked against**, so the
    write and the check cannot disagree about a figure: there is one
    computation and the applier has none.

    **A row crossing zero is refused rather than written.** A 0 is not a count
    in this document, it is the statement that this engine cannot run the file,
    and the two arms outside the gate read it as one. A run that found a
    counted file stated as 0, or a stated file collecting nothing, has found a
    defect those arms name; replacing the digit would silence them and leave
    the register asserting something no run checked. So such a register is left
    alone in full, block included, because the block's own fourth figure counts
    the rows stating 0 and would be rendered against a table about to change.
    """
    table = rows(register)
    recorded = _rows_of_zero(table)
    lines: list[tuple[str, str]] = []
    refused: list[str] = []
    for match in _ROW.finditer(register):
        path, stated = match.group(1), int(match.group(2))
        counted = census.counts.get(path, 0)
        if counted == stated:
            continue
        if path in recorded or counted == 0:
            refused.append(
                f"{path}: the register says {stated} and this run collected "
                f"{counted}. A 0 in this column records an engine that cannot "
                "run the file rather than a count, so neither figure is a "
                "digit to replace."
            )
            continue
        lines.append(_restated(register, match, counted))
    block = render(census, table)
    _, current, _ = split(register)
    if refused:
        # **The whole register, and this is where that is decided rather than
        # in whatever applies the write.** A rule the applier has to honour is
        # a rule the next applier does not; carrying no block and no line
        # makes the refusal a property of what this run offers.
        return WriteInstruction(
            register=REGISTER_PATH, block=None, lines=(), refused=tuple(refused)
        )
    if current == block and not lines:
        return None
    return WriteInstruction(
        register=REGISTER_PATH, block=block, lines=tuple(lines), refused=()
    )


def _write_line(census: Census, register: str, deselected: Sequence[str]) -> str:
    """The payload to print beside a failure, or nothing when there is none.

    **Appended to the message of every arm that can be red on a stale
    register**, so whichever of them a run reaches carries the same complete
    write. Two arms printing one instruction is the applier's cross check: it
    refuses two payloads for one register that disagree.

    **A run that deselected anything offers no write, and that is the whole
    reason this takes an argument.** The gate above these arms is a file set,
    which cannot see a narrowing inside a file: a `-k` leaving at least one
    test in every file opens it and leaves these two arms red on counts that
    are floors. That was loud and wrong, which is the cheaper direction. It
    stopped being the cheaper direction the moment these arms began printing
    something a tool applies without a question to ask, so the counter the
    gate's own note calls affordable is taken here. `conftest.pytest_deselected`
    is the one cause agnostic hook every narrowing reaches.
    """
    if deselected:
        return (
            f"\nNo write is offered: this run deselected {len(deselected)} of "
            "the items it collected, so every count above is a floor rather "
            "than a count. The file set gate cannot see a narrowing inside a "
            "file, which is why these figures are red and not writable."
        )
    instruction = write_instruction(census, register)
    return "" if instruction is None else "\n" + instruction.payload()


def _planted(counts: dict[str, int], on_disk: set[str]) -> Census:
    """A census this file made up, for driving the rules below against one.

    `test` and `Test` are pytest's own defaults for `python_functions` and
    `python_classes`, and are what this project runs under. `Census.of` reads
    the live values; an arm pinning a rule rather than a tree has no session
    to read them from.
    """
    return Census(
        counts=counts,
        on_disk=frozenset(on_disk),
        test_names=("test",),
        test_classes=("Test",),
    )


def _excused(census: Census, register: str, root: Path = TESTS) -> frozenset[str]:
    """Every file the gate may subtract before comparing its two instruments.

    **The rows of 0, plus the fourth cell of the same partition.** The
    partition is two questions crossed, may the register name this file and
    does this engine run it, which is four cells; three were filled and the
    fourth was stated. A file the publish gate strips cannot carry a row at
    all, so an internal test module that ends its own collection sat in the
    walk, out of the run and out of the document, and the gate skipped on it
    with the three count arms dark and nothing else red anywhere. Driven by a
    review seat: one unconditional module level skip planted in a stripped
    file left the whole suite green while the register went on publishing the
    headline of a run that had not happened.

    **And the remedy that skip prescribes cannot be applied to this cell**,
    because a published register naming a stripped path fails the publish
    gate. A residue whose stated fix reds another gate is worse than one with
    no fix written down, which is why this is closed here rather than stated
    there.

    **Read from the document for the named half and from the file for the
    unnamed half**, which is the asymmetry the two destinations force rather
    than a choice: the stripped half has no document to be read from.

    **So the two halves are held to `_is_silenced_by_the_engine` in two
    places.** The named half is subtracted exactly as the document states it,
    and the two arms outside this gate are what refuse a row of 0 the
    predicate does not support. The unnamed half asks the predicate here,
    because there is nothing to hold it to afterwards; without that an emptied
    internal module would buy the permanent excuse a named one is refused,
    which is `test_an_internal_module_that_merely_collects_nothing_is_not
    _excused`.
    """
    named = not_collected_here(register)
    return named | frozenset(
        path
        for path in set(census.on_disk) - set(census.counts) - named
        if declares_itself_internal(root / path)
        and _is_silenced_by_the_engine(
            root / path, census.test_names, census.test_classes
        )
    )


def _refusal(census: Census, excused: frozenset[str]) -> str | None:
    """Why this run may not answer for the register, or `None` when it may.

    **Two sides and a sentence each, because they are two different faults.**
    One message served both and it was written for the side where the walk has
    a file the run did not collect. On the other side it said the run had
    collected more test files than the tree holds, and offered a row of 0 for
    files that do collect, which
    `test_a_row_of_zero_names_a_file_this_run_did_not_collect` refuses. A
    remedy that reds a sibling arm is worse than no remedy, and the reader who
    follows it has no way to know that from here.
    """
    silent = census.silent(excused)
    unexpected = census.unexpected(excused)
    if not silent and not unexpected:
        return None
    reasons = []
    if silent:
        reasons.append(
            f"The test tree has {_files(len(silent))} this run did not collect "
            f"and the register does not record as collecting nothing here: "
            f"{silent}. On a whole suite run that is a file collecting no test "
            "rather than a narrowed run, and the remedy is a row of 0 for it."
        )
    if unexpected:
        reasons.append(
            f"This run collected {_files(len(unexpected))} the tree walk did "
            f"not return: {unexpected}. That is the walk going wrong rather "
            "than the run being narrowed, so the remedy is in "
            "`test_house_rules::_test_sources` and not in the register. A row "
            "of 0 is refused for a file that collects."
        )
    return (
        f"this run collected {len(census.counts)} test files and the counts in "
        "the register cannot be checked against it. " + " ".join(reasons)
    )


def _rows_of_zero_that_collected(census: Census, register: str) -> list[str]:
    """Rows stating 0 for a file this run did collect, with both figures.

    **A function rather than a comprehension inside the arm**, so that
    neutering the predicate reds an arm of its own: on this tree each of these
    answers about the same single file every run, and an arm whose body is a
    constant would satisfy every rule above it.
    """
    return [
        f"{path}: stated as 0, collected {census.counts[path]}"
        for path in sorted(not_collected_here(register))
        if path in census.counts
    ]


def _rows_of_zero_with_no_engine_reason(
    census: Census, register: str, root: Path = TESTS
) -> list[str]:
    """Rows stating 0 for a file whose silence here is not the engine's doing.

    Asked only of the files the walk has, so a row naming a path the tree lost
    is reported by `test_every_row_names_a_file_the_tree_has` rather than as a
    file this cannot read.
    """
    return sorted(
        path
        for path in not_collected_here(register)
        if path in census.on_disk
        and not _is_silenced_by_the_engine(
            root / path, census.test_names, census.test_classes
        )
    )


#: Set to `off` by the plant harness for every arm it runs: the register is red
#: by construction on a branch that adds a test, so a plant's baseline would
#: refuse exactly there. Only that word turns the document's arms off; the
#: suite runner refuses any other value before a run starts.
SWITCH = "ENDPAPER_COVERAGE_REGISTER"


def _the_document() -> str:
    """The document, or a skip for every arm reading it when the switch is off.

    **Here because this is the file's one read of the document**, so every
    arm comparing it to the tree or the run skips, and the arms testing the
    readers on text of their own still run.

    **In a pipeline the switch fails instead.** The pipeline runs pytest
    directly rather than through the suite runner, so a CI variable carrying
    the switch would otherwise skip the register on every job it reaches,
    green.
    """
    if os.environ.get(SWITCH) == "off":
        if "GITLAB_CI" in os.environ:
            pytest.fail(f"{SWITCH}=off is for a plant copy and this is a pipeline")
        pytest.skip(f"{SWITCH}=off: this run does not check {REGISTER.name}")
    return REGISTER.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def register() -> str:
    return _the_document()


class TestThePlantHarnessSwitch:
    def test_off_skips_the_arms_that_read_the_document(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Cleared, because the pipeline running this arm sets it.
        monkeypatch.delenv("GITLAB_CI", raising=False)
        monkeypatch.setenv(SWITCH, "off")

        with pytest.raises(pytest.skip.Exception, match=SWITCH):
            _the_document()

    def test_off_in_a_pipeline_fails_rather_than_skips(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("GITLAB_CI", "true")
        monkeypatch.setenv(SWITCH, "off")

        # Both caught: a skip escaping this arm would report it skipped, not red.
        with pytest.raises((pytest.fail.Exception, pytest.skip.Exception)) as raised:
            _the_document()

        assert raised.type is pytest.fail.Exception

    def test_unset_reads_the_document(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv(SWITCH, raising=False)

        assert _the_document() == REGISTER.read_text(encoding="utf-8")


@pytest.fixture
def census(request: pytest.FixtureRequest) -> Census:
    """This run, as a count per file.

    `request.session.items` under xdist is the **whole** collection rather than
    this worker's share of it: every worker collects the suite and the
    controller then hands out indices into that list. A share would report a
    fraction of the tree and be refused by `whole_tree` below, so the failure
    mode of being wrong about this is a guard that never runs, which is why the
    gate on it is not optional.
    """
    return Census.of(request.session)


@pytest.fixture
def whole_tree(census: Census, register: str) -> Census:
    """The census, or a skip when this run is not the whole suite.

    **A narrowed run must not be allowed to answer**: run one file and every
    other row reads as missing, which would be reported as a stale register and
    is a guard that cries wolf until somebody deletes it.

    The gate is the file set rather than a flag, because a path, `-k`, a marker
    and a plugin each narrow a run by a different route, and enumerating them is
    the shape this repository keeps paying for.

    **What a file set cannot see is a narrowing INSIDE a file.** A `-k`
    leaving at least one test in every file changes no file's membership, so
    the gate opens and the count arms red on a figure that is correct.
    Measured on a whole run deselecting one test of one file: the block arm
    and the row arm red, nothing here skipped. That is loud and it is wrong,
    which is the cheaper of the two directions.

    **Closing it is affordable, and the decision not to rests on the cost
    alone.** `pytest_deselected` is one cause agnostic hook that `-k`, `-m`,
    `--deselect`, `--lf`, `--ff` and `--sw` all reach, so a conftest counter
    is not the enumeration this gate refuses; what such a counter would not
    see is a plugin dropping items without calling that hook, which pytest's
    own hookspec states as a requirement. So the question is a counter against
    a failure that is already loud, and the cost of answering it wrongly is
    two arms red on a register that is right.

    **A file this engine cannot run is subtracted before the comparison.**
    Until it was, this gate failed open: such a file is in the tree and not in
    the collection, so a **whole** suite run read as narrowed and all three
    arms behind the gate skipped on every run, leaving the register's figures
    checked by nothing. Found by a security critic while it was still latent,
    and live from the day `test_database_tls_on_a_real_server.py` arrived.

    **What `_excused` subtracts and what holds it** is written there. The
    short of it is that the named half is a statement in the document rather
    than a reading of the run, which is what keeps it from being the
    enumeration refused above, and two arms outside this gate hold the
    document to it: a row of 0 on a file this run collected reds
    `test_a_row_of_zero_names_a_file_this_run_did_not_collect`, and a row of 0
    on a file whose silence is not the engine's reds
    `test_a_row_of_zero_names_a_file_this_engine_cannot_run`. Both run on a
    narrowed run, where this gate does not.

    **What still skips, and it is the residue rather than the defect.** A
    published test file that collects nothing and carries no row of 0 is
    indistinguishable here from one a narrowed run did not reach, so it lands
    in this skip. **Its arrival is still loud**, because
    `test_every_file_with_no_row_is_one_the_register_may_not_name` reds on it
    by name; what goes quiet is the three arms behind this gate, until
    somebody gives it the row the message asks for.

    **The two count comparisons and the census diagonal sit behind this**, and
    the rules about the file set do not, because of that residue. They are
    asked of the walk, where such a file is present and has to carry a row or a
    declaration either way.
    """
    refusal = _refusal(census, _excused(census, register))
    if refusal is not None:
        pytest.skip(refusal)
    return census


class TestEveryNumberInTheRegisterIsThisRunsOwn:
    def test_the_measured_block_is_what_this_run_collected(
        self, whole_tree: Census, register: str, deselected_items: list[str]
    ) -> None:
        _, block, _ = split(register)
        table = rows(register)

        assert block == render(whole_tree, table), (
            "COVERAGE.md's measured block is not what this run collected. That "
            "block is generated: replace the text between the fences with what "
            "follows, and read what moved rather than adjusting a figure by the "
            f"delta.\n{render(whole_tree, table)}"
            f"{_write_line(whole_tree, register, deselected_items)}"
        )

    def test_every_row_states_the_count_this_run_collected(
        self, whole_tree: Census, register: str, deselected_items: list[str]
    ) -> None:
        """Every row, including one stating 0.

        **No `path in counts` filter, which used to be here and read as
        harmless.** A row for a file the run did not collect was skipped by it,
        so the one spelling the register has for a file this engine cannot run
        was the one spelling nothing checked. Behind the gate, where the
        collection is the whole tree, a file with no count has collected none.
        """
        wrong = [
            f"{path}: the register says {stated}, the run collected "
            f"{whole_tree.counts.get(path, 0)}"
            for path, stated in rows(register)
            if stated != whole_tree.counts.get(path, 0)
        ]

        assert wrong == [], "\n".join(wrong) + _write_line(
            whole_tree, register, deselected_items
        )

    def test_every_row_names_a_file_the_tree_has(
        self, census: Census, register: str
    ) -> None:
        """The other direction, because the cheapest way to make the rule above
        go green is to delete the row it names.

        The depth table had the same hole and it was measured there: one row
        taken out of the first column left the whole file green with the
        module's own paragraph still beside it.
        """
        gone = sorted({path for path, _ in rows(register)} - census.on_disk)

        assert gone == [], (
            f"these rows name files the test tree does not have: {gone}. A file "
            "that is gone loses its row; one that was renamed keeps its "
            "description."
        )

    def test_no_file_is_given_two_rows(self, register: str) -> None:
        """A path written twice states a row count the table does not have.

        The block renders the number of rows beside what they sum to, and the
        sum is over distinct files, so two rows for one file leave the pair
        describing different tables while every other rule here passes.
        """
        named = [path for path, _ in rows(register)]
        twice = sorted({path for path in named if named.count(path) > 1})

        assert twice == [], f"these files carry more than one row: {twice}"

    def test_every_file_with_no_row_is_one_the_register_may_not_name(
        self, census: Census, register: str
    ) -> None:
        """The shortfall, derived rather than stated.

        **A count in the block would be satisfied by any files at all**, so one
        more added with no row could be absorbed by editing a digit. What makes
        this a partition instead: a collected file either carries a row or
        declares itself internal, and the publish gate holds the other end of
        that, refusing to publish a file carrying the declaration and refusing a
        stripped document that omits it.

        So a new test file has three honest destinations, a row here, the
        strip list, or a row of 0 when this engine does not run it, and one
        that took none of them fails here by name. The fourth cell, a stripped
        file this engine does not run, has no row to take and is read off the
        file by `_excused`.

        **Asked of the walk rather than of the collection**, so that a file
        collecting no test is still required to answer, and so that this rule,
        which is the only thing in the tree requiring a stripped test file to
        carry the declaration, cannot be switched off by narrowing a run.
        """
        named = {path for path, _ in rows(register)}
        undescribed = [
            path
            for path in sorted(census.on_disk - named)
            if not declares_itself_internal(TESTS / path)
        ]

        assert undescribed == [], (
            "these files are in the test tree, carry no row in COVERAGE.md and "
            f"are not stripped from the published tree: {undescribed}. Give each "
            "one a row saying what it covers, which is the half of this register "
            "a run cannot write."
        )

    def test_a_row_of_zero_names_a_file_this_run_did_not_collect(
        self, census: Census, register: str
    ) -> None:
        """A row of 0 is what subtracts a file from `whole_tree`, so it is the
        one cell that can widen what a narrowed run is allowed to look like.

        **Outside that gate deliberately**, because an arm bounding a gate
        cannot be switched off by the gate it bounds.

        **What keeps it green on a narrowed run is a condition, not a rule
        about size.** The docstring here said a narrowed run only ever collects
        less so this could not fire on one by accident, which is false: the row
        of 0 is about the engine and not about the count, and on the other
        engine the narrowed run collects **more** of exactly that file. The
        pipeline's `test:postgres` job runs a few named paths, one of which is
        the file this register's only row of 0 names. What keeps this arm green
        on that leg is that the job does not also name this one, so this arm
        never runs there.
        """
        live = _rows_of_zero_that_collected(census, register)

        assert live == [], (
            "a row of 0 records a file this engine does not run, and these were "
            "collected by the run reading it:\n" + "\n".join(live)
        )

    def test_a_row_of_zero_names_a_file_this_engine_cannot_run(
        self, census: Census, register: str
    ) -> None:
        """The second instrument under that row, so one digit cannot reopen the gate.

        The arm above catches a live file's count changed to 0, because such a
        file collects. **What only this one catches is a file collecting
        nothing for a reason that is a defect**: an empty `test_*.py`, or one
        whose tests were all deleted, given a row of 0 and thereby excused from
        the gate for good. Driven: such a file, planted with a module level
        skip and a row of 0, took the whole suite green at exit 0 before this
        arm asked whether it declares a test.

        **Named for the claim the row makes rather than for one of the two
        predicates under it.** It was named for the skip alone, which is half
        of what a 0 says: `_is_silenced_by_the_engine` holds both halves and
        its docstring says what neither can ask.
        """
        cannot = _rows_of_zero_with_no_engine_reason(census, register)

        assert cannot == [], (
            f"these rows state 0 and this engine is not why they collect "
            f"nothing: {cannot}. A 0 records an engine that cannot run a file "
            "that has tests. A file with no test in it, or one whose module "
            "body cannot end its own collection, collects nothing everywhere "
            "and a 0 excuses it for good."
        )

    def test_this_run_deselected_nothing_and_the_counter_says_so(
        self, deselected_items: list[str]
    ) -> None:
        """The arming check for the thing that withholds a write.

        **Zero is the true value and there is no room under it**, which is
        what makes this an arm rather than a floor: the day a plugin starts
        dropping items on an ordinary run is the day these counts stop being
        counts, and that is exactly when the write must stop being offered.

        It also witnesses that the hook is wired at all. A counter nobody
        calls reads as "nothing was deselected" forever, which is the silent
        direction.
        """
        assert deselected_items == [], (
            "this run dropped items after collecting them, so the counts the "
            "register is checked against are floors. If that is deliberate, "
            "it is the gate that needs widening and not this arm."
        )

    def test_nothing_collected_is_skipped_or_left_expected_to_fail(
        self, request: pytest.FixtureRequest
    ) -> None:
        """What lets the block say "tests" where the gate says "passed".

        Collected and passed differ by the skips plus the open recorded
        defects. The register states the two as one number, and this is the
        condition under which that is a fact about the tree rather than a
        simplification. It reads markers, so a `pytest.skip()` called inside a
        test body is not covered: the run's own summary line is where that one
        shows up.
        """
        marked = sorted(
            f"{Path(item.path).relative_to(TESTS).as_posix()}::{item.name} ({marker})"
            for item in request.session.items
            for marker in ("skip", "skipif", "xfail")
            if item.get_closest_marker(marker) is not None
        )

        assert marked == [], (
            "COVERAGE.md states one number for collected and for passed. These "
            f"tests would make the two differ: {marked}"
        )


class TestTheCensusMeasuresRatherThanAgrees:
    """Two diagonals, because every rule above compares the document with
    `counts` and would compare them just as happily if `counts` were a constant
    or a count of function definitions."""

    def test_the_census_counts_cases_rather_than_functions(
        self, whole_tree: Census
    ) -> None:
        """`test_dialect.py` is the witness because its cases are generated per
        dialect, so its collected count has always stood well above the number
        of functions in it. This file is parametrised nowhere and could not
        serve.
        """
        witness = "test_dialect.py"
        functions = len(
            re.findall(r"^\s*def test_", (TESTS / witness).read_text(), re.MULTILINE)
        )

        assert whole_tree.counts[witness] > functions, (
            f"{witness} collects {whole_tree.counts[witness]} tests from "
            f"{functions} functions; equal means the census has stopped counting "
            "cases and the register would now agree with the wrong instrument"
        )

    def test_the_census_counts_every_item_this_run_collected(
        self, census: Census, request: pytest.FixtureRequest
    ) -> None:
        """The collected side of the comparison, which nothing had ever armed.

        **A comparison has two instruments, and arming one of them repeatedly
        is not arming the comparison.** Three rounds armed the walk, then the
        walk's own filter, each closing the narrowing that had just been
        demonstrated and all three on the same side. `counts` is a loop over
        `session.items` in `Census.of` and had no second derivation anywhere:
        one `continue` planted into that loop, dropping a suffix, took a whole
        suite run green at exit 0 with the three count arms skipping, both
        walk side arms green, **nothing red anywhere**, and the two register
        rows that are legitimately stale on this branch unreported as well,
        so the plant reported a red tree clean.

        **The transform re-derived, not the source.** The items are the same
        list `Census.of` reads, so this says nothing about a run that really
        was narrowed, which is what the gate is for. What it says is that the
        loop between the items and the census drops nothing.

        **What a reader of `Census.of` need not take on trust is that loop
        and the file naming rule**, each re-derived by an arm here. It makes
        three configuration reads and the other two, the function and class
        naming rules, are read once and re-derived nowhere. Both are pytest's
        own defaults in this project, so spelling them here instead would be
        inert today, and a divergence mostly refuses: a stricter rule reads
        fewer names as tests and reds the row of 0 it then cannot support.
        """
        collected = {
            Path(item.path).relative_to(TESTS).as_posix()
            for item in request.session.items
        }

        assert census.total == len(request.session.items), (
            "the census and this run's own item list disagree on how many "
            f"tests ran: {census.total} against {len(request.session.items)}"
        )
        assert set(census.counts) == collected, (
            "the census and this run's own item list disagree on which files "
            f"ran: {sorted(set(census.counts) ^ collected)}"
        )

    def test_the_census_drops_only_what_the_naming_rule_drops(
        self, census: Census, request: pytest.FixtureRequest
    ) -> None:
        """The walk side's second narrowing point, a layer below the walk's
        own arm and silent until this.

        `on_disk` is the shared walk **intersected with a pattern match**, and
        only the walk half had a second derivation. Driven: a narrowing
        written into this comprehension rather than into the walk gave
        `9959 passed, 4 skipped, 0 failed` at exit 0, with the three count
        arms skipping, the walk's own arm green, and **not one arm anywhere
        red**, the skip also hiding the two register rows that are
        legitimately stale on this branch. That is the recorded shape: the
        round before this closed the narrowing that had been demonstrated
        rather than the class.

        **The complement by equality**, so a file the comprehension drops has
        to fail every pattern. It is not the walk's arm restated: a narrowing
        written in `_test_sources` moves both sides of this equality together,
        which is why that half is armed beside the shared reader instead, in
        `test_house_rules::TestTheTestTreeIsStillTheTestTree`.
        """
        patterns = request.session.config.getini("python_files")
        walked = {path.relative_to(TESTS).as_posix() for path in _test_sources()}
        named = {
            path
            for path in walked
            if any(fnmatch(Path(path).name, pattern) for pattern in patterns)
        }

        assert set(census.on_disk) == named, (
            "the census is no longer the test tree walk under the collector's "
            "own naming rule. A file dropped here is one the three count arms "
            "stop seeing, and the gate reports that as a narrowed run rather "
            f"than as a fault: {sorted(set(census.on_disk) ^ named)}"
        )
        # Anti vacuity, and it is the half the equality cannot supply: with
        # every walked file matching, the equality holds over a comprehension
        # that filters nothing and says nothing about one that filters wrongly.
        assert walked - named, (
            "every file the walk returns is read as a test module, so this "
            "equality is comparing the walk with itself"
        )

    def test_the_walk_reads_a_tree_rather_than_the_collection(
        self, tmp_path: Path
    ) -> None:
        """`on_disk` comes from the shared tree walk and `counts` from pytest's
        own collection, and every rule above rests on those being two
        instruments: the completeness gate compares them, and a gate comparing
        one list with itself passes on any tree.

        Driven against a tree this test planted, because the assertion that
        suggests itself here, that the walk covers the collection, is the gate's
        own condition restated and therefore true by construction wherever the
        gate let a test run at all.
        """
        (tmp_path / "tests").mkdir()
        (tmp_path / "tests" / "test_planted.py").write_text("def test_nothing(): ...")
        (tmp_path / "tests" / "helpers.py").write_text("")

        found = {path.name for path in _test_sources(tmp_path)}

        assert found == {"test_planted.py", "helpers.py"}


class TestTheDocumentIsReadRatherThanAssumed:
    """The parser's own failure modes, all of which are silent ones.

    Each has a version where every rule above passes while reading nothing: no
    fences, a table whose shape moved, a padded column. A guard with no input
    cannot fail.
    """

    def test_a_register_with_no_fences_is_refused(self) -> None:
        with pytest.raises(AssertionError, match="no measured block"):
            split("# Backend test coverage\n\nNo block here.\n")

    def test_a_padded_row_is_read(self) -> None:
        assert rows("| `test_a.py`   |   327 | What it covers |\n") == [
            ("test_a.py", 327)
        ]

    def test_a_row_in_a_nested_directory_keeps_its_path(self) -> None:
        assert rows("| `routers/test_books.py` | 143 | Listing |\n") == [
            ("routers/test_books.py", 143)
        ]

    def test_a_number_in_the_third_column_is_not_read_as_the_count(self) -> None:
        """The cell boundary, which is the mistake the roster census made
        first: a number one column along is a claim about a different subject,
        and here it would silently become the row's count."""
        assert rows("| `test_a.py` | 12 | covers 34 cases |\n") == [("test_a.py", 12)]

    def test_a_table_whose_first_cell_is_not_a_path_yields_no_row(self) -> None:
        assert rows("| File | Tests | Covers |\n|---|---:|---|\n") == []

    def test_the_block_renders_every_figure_from_the_census(self) -> None:
        """The renderer driven against a tree this test built, so that the
        equality above compares the document with a measurement rather than
        with a constant."""
        census = Census(
            counts={"test_a.py": 10, "test_b.py": 5, "test_hidden.py": 2},
            on_disk=frozenset(
                {"test_a.py", "test_b.py", "test_hidden.py", "test_quiet.py"}
            ),
            test_names=("test",),
            test_classes=("Test",),
        )

        block = render(
            census, [("test_a.py", 10), ("test_b.py", 5), ("test_quiet.py", 0)]
        )

        assert "**17 tests, in 3 files**" in block
        assert "**The 3 rows below sum to 15.**" in block
        assert "The other 2 tests are in 1 file this register may not name." in block
        assert (
            "The table also carries 1 file this engine does not run, stated as 0."
            in block
        )

    def test_one_file_is_not_written_as_files(self) -> None:
        assert _files(1) == "1 file"
        assert _files(2) == "2 files"

    def test_one_row_is_not_written_as_rows(self) -> None:
        """Unreachable while the table holds more than one row, and written
        because the block is prose: the day a register is down to one row is
        not the day to notice the sentence reads wrong."""
        assert _rows(1) == "1 row"
        assert _rows(2) == "2 rows"


class TestTheWriteCarriesTheChecksOwnFigures:
    """`write_instruction`, which is what a deliberate write applies.

    **The subject of every arm here is that the write and the check are one
    computation.** The register was recounted by hand until this existed, and
    the obvious replacement, a tool that counts the suite a second way, is
    worse than the hand: it would agree with the run on almost every tree, so
    the one tree where it did not is the one nobody would look at. These arms
    hold the write to the same `render` and the same `counts` the rules above
    compare against, which is the only reason a generated figure is worth more
    here than a careful reader.
    """

    @staticmethod
    def _document(census: Census, table: list[tuple[str, int]]) -> str:
        """A register whose block is current for `census` and whose rows are
        whatever the caller asked for, so an arm moves one thing at a time."""
        body = "".join(
            f"| `{path}` | {stated} | What {path} covers |\n" for path, stated in table
        )
        return (
            "# Backend test coverage\n\n"
            f"{BEGIN}{render(census, table)}{END}\n\n"
            "| File | Tests | Covers |\n|---|---:|---|\n" + body
        )

    def test_a_register_that_agrees_with_the_run_has_nothing_to_write(self) -> None:
        census = _planted({"test_a.py": 10}, {"test_a.py"})
        document = self._document(census, [("test_a.py", 10)])

        assert write_instruction(census, document) is None
        assert _write_line(census, document, []) == ""

    def test_a_run_that_deselected_anything_offers_no_write(self) -> None:
        """The narrowing the gate above these arms cannot see.

        A `-k` leaving at least one test in every file changes no file's
        membership, so that gate opens and the counts behind it are floors.
        Before the write existed that was loud and wrong, which the gate's own
        note calls the cheaper direction and rests its decision on. A complete
        write carrying undercounts is not the cheaper direction, because the
        thing that applies it has no question to ask.
        """
        census = _planted({"test_a.py": 12}, {"test_a.py"})
        document = self._document(census, [("test_a.py", 10)])

        said = _write_line(census, document, ["tests/test_a.py::test_one"])

        assert WRITE_SENTINEL not in said
        assert "deselected 1 of the items it collected" in said
        # The diagonal: this register really is stale, so a line that said
        # nothing whatever a run did would pass the assertion above.
        assert write_instruction(census, document) is not None
        assert WRITE_SENTINEL in _write_line(census, document, [])

    def test_a_row_the_run_disagrees_with_is_written_as_two_whole_lines(self) -> None:
        """The line the document has and the line this run would put there.

        **The old line is in the write so that the applier can refuse**: a
        document whose row has moved since the run is a replacement the applier
        cannot find, which is a named refusal rather than a cell written in the
        wrong place.
        """
        census = _planted({"test_a.py": 12}, {"test_a.py"})
        document = self._document(census, [("test_a.py", 10)])

        instruction = write_instruction(census, document)

        assert instruction is not None
        assert instruction.lines == (
            ("| `test_a.py` | 10 | What test_a.py covers |",
             "| `test_a.py` | 12 | What test_a.py covers |"),
        )
        assert instruction.refused == ()

    def test_the_sentence_beside_a_corrected_count_is_carried_through(self) -> None:
        """The descriptions are the half of this register a run cannot write,
        so a write that corrects a figure must not touch them. The third cell
        here holds digits of its own, which is the shape that would be lost by
        a writer rebuilding the row instead of editing the cell."""
        census = _planted({"test_a.py": 4}, {"test_a.py"})
        document = self._document(census, [("test_a.py", 9)]).replace(
            "What test_a.py covers", "**12 shapes**, and the 3 that are not"
        )

        instruction = write_instruction(census, document)

        assert instruction is not None
        assert instruction.lines == (
            ("| `test_a.py` | 9 | **12 shapes**, and the 3 that are not |",
             "| `test_a.py` | 4 | **12 shapes**, and the 3 that are not |"),
        )

    def test_the_block_it_writes_is_the_block_the_arm_compares(self) -> None:
        """One computation, asserted rather than said. The arm above this class
        compares the document against `render`; so does the write."""
        census = _planted({"test_a.py": 10, "test_b.py": 7}, {"test_a.py", "test_b.py"})
        table = [("test_a.py", 10), ("test_b.py", 7)]
        document = self._document(census, table).replace(
            "**17 tests", "**1700 tests"
        )

        instruction = write_instruction(census, document)

        assert instruction is not None
        assert instruction.block == render(census, rows(document))

    def test_a_row_crossing_zero_is_refused_and_the_register_left_whole(self) -> None:
        """A 0 is a statement about the engine, not a count, and two arms
        outside the gate read it as one. A run that disagrees with one has
        found what those arms are for, so nothing is written at all: the
        block's own fourth figure counts the rows stating 0, and rendering it
        against a table about to change is how a write leaves a register
        stale in a second place.
        """
        census = _planted({"test_a.py": 3, "test_zero.py": 6}, {"test_a.py", "test_zero.py"})
        document = self._document(census, [("test_a.py", 5), ("test_zero.py", 0)])

        instruction = write_instruction(census, document)

        assert instruction is not None
        assert instruction.lines == ()
        assert instruction.block is None
        assert len(instruction.refused) == 1
        assert "test_zero.py" in instruction.refused[0]

    def test_a_file_the_run_lost_is_refused_rather_than_written_as_zero(self) -> None:
        """The other direction across the same cell, and the cheapest wrong
        write available: a row whose file is gone collects nothing, and
        writing the 0 would hand it the permanent excuse a row of 0 carries."""
        census = _planted({"test_a.py": 3}, {"test_a.py"})
        document = self._document(census, [("test_a.py", 3), ("test_gone.py", 8)])

        instruction = write_instruction(census, document)

        assert instruction is not None
        assert instruction.lines == ()
        assert instruction.block is None
        assert len(instruction.refused) == 1
        assert "test_gone.py" in instruction.refused[0]

    def test_the_write_travels_as_one_line_and_arrives_unchanged(self) -> None:
        """The payload is printed into a suite artefact and read back out of
        it, so it is one line and it survives the round trip. A block spans
        several lines and a description can hold any character a person
        types."""
        census = _planted({"test_a.py": 12}, {"test_a.py"})
        document = self._document(census, [("test_a.py", 10)])
        instruction = write_instruction(census, document)
        assert instruction is not None

        payload = instruction.payload()

        assert "\n" not in payload
        assert payload.startswith(WRITE_SENTINEL + " ")
        carried = json.loads(payload[len(WRITE_SENTINEL) + 1 :])
        assert carried["register"] == REGISTER_PATH
        assert carried["block"] == instruction.block
        assert carried["lines"] == [list(pair) for pair in instruction.lines]
        assert carried["refused"] == []

    def test_the_register_it_names_is_the_register_this_file_reads(self) -> None:
        """Derived rather than written down, so a moved register does not leave
        the write naming a path the applier cannot find."""
        assert (TESTS.parent.parent / REGISTER_PATH).resolve() == REGISTER.resolve()

    def test_both_arms_that_can_be_red_on_a_stale_register_print_the_write(
        self,
    ) -> None:
        """The seam, which had no witness on this side either.

        **The renderer is positively witnessed as a function and its call
        sites are not.** Both of them are interpolations inside assertion
        messages that exist only when the register is stale, so on a green
        tree deleting either one reds nothing at all and the write simply
        stops being offered by that arm. The frontend half has the same
        shape at its own seam and now has a positive arm; this is that arm
        on this side.

        **Structural rather than a text match**, so reformatting the message
        or moving the call within it changes nothing here, and removing the
        call is what reds.

        **What it cannot witness**: that the message reaches an artefact, or
        that pytest prints it. A suite cannot watch its own reporting from
        inside itself, which is the same residue the frontend's own witness
        states.
        """
        tree = ast.parse(Path(__file__).read_text(encoding="utf-8"))
        calling = {
            node.name
            for node in ast.walk(tree)
            if isinstance(node, ast.FunctionDef)
            and any(
                isinstance(inner, ast.Call)
                and isinstance(inner.func, ast.Name)
                and inner.func.id == "_write_line"
                for inner in ast.walk(node)
            )
        }

        assert {
            "test_the_measured_block_is_what_this_run_collected",
            "test_every_row_states_the_count_this_run_collected",
        } <= calling, (
            "an arm that can be red on a stale register no longer offers the "
            f"write beside its failure. These do: {sorted(calling)}"
        )


class TestWhatEndsAModulesOwnCollection:
    """`_can_end_its_own_collection`, driven against planted files.

    **The subject is what the module body can reach and under what name it
    reaches it.** The predicate read the receiver written at the call and
    refused four spellings that do end a module's collection, so the arms for
    those are here rather than the tuple of pytest function names being
    widened, which could not have reached any of them.
    """

    def test_a_module_level_skip_ends_its_own_collection(self, tmp_path: Path) -> None:
        """Under an `if`, which is where the real one sits: the subject is what
        the module body can reach, not what its first statement is."""
        planted = tmp_path / "test_planted.py"
        planted.write_text(
            "import pytest\n\nif True:\n"
            '    pytest.skip("no engine here", allow_module_level=True)\n'
        )

        assert _can_end_its_own_collection(planted)

    def test_a_module_level_import_or_skip_ends_its_own_collection(
        self, tmp_path: Path
    ) -> None:
        planted = tmp_path / "test_planted.py"
        planted.write_text('import pytest\n\nlxml = pytest.importorskip("lxml")\n')

        assert _can_end_its_own_collection(planted)

    def test_a_skip_written_on_an_alias_of_the_module_ends_its_own_collection(
        self, tmp_path: Path
    ) -> None:
        """`import pytest as pt`, which the receiver test refused."""
        planted = tmp_path / "test_planted.py"
        planted.write_text(
            "import pytest as pt\n\nif True:\n"
            '    pt.skip("no engine here", allow_module_level=True)\n'
        )

        assert _can_end_its_own_collection(planted)

    def test_a_skip_imported_by_name_ends_its_own_collection(
        self, tmp_path: Path
    ) -> None:
        """`from pytest import skip as stop`, which the receiver test refused.

        The alias, rather than the plain `from pytest import skip`, because the
        plain one is the case a reader fixes by widening a name list and the
        alias is the one that says the binding is what is being read.
        """
        planted = tmp_path / "test_planted.py"
        planted.write_text(
            "from pytest import skip as stop\n\nif True:\n"
            '    stop("no engine here", allow_module_level=True)\n'
        )

        assert _can_end_its_own_collection(planted)

    def test_a_skip_that_is_not_allowed_at_module_level_does_not(
        self, tmp_path: Path
    ) -> None:
        """A false accept rather than a miss.

        pytest raises `Failed: Using pytest.skip outside of a test is not
        allowed` for this one, so it reds the run rather than ending the
        module, and a row of 0 for such a file would excuse a broken run.
        """
        planted = tmp_path / "test_planted.py"
        planted.write_text('import pytest\n\nif True:\n    pytest.skip("x")\n')

        assert not _can_end_its_own_collection(planted)

    def test_a_name_this_module_never_bound_to_pytest_does_not(
        self, tmp_path: Path
    ) -> None:
        """The other direction of reading the binding.

        A helper called `skip` that this file defines itself is not pytest's,
        and a predicate matching the name alone would answer True for it.
        """
        planted = tmp_path / "test_planted.py"
        planted.write_text(
            "def skip(reason, allow_module_level=False): ...\n\n"
            'skip("not pytest\'s", allow_module_level=True)\n'
        )

        assert not _can_end_its_own_collection(planted)

    def test_the_same_call_inside_a_test_does_not(self, tmp_path: Path) -> None:
        """The distinction the register's two halves turn on. A test skipping
        itself is collected and not passed, which
        `test_nothing_collected_is_skipped_or_left_expected_to_fail` refuses; a
        module skipping itself is never collected, which is what a row of 0
        records. Reading the two as one would let that refusal be evaded by
        writing the skip one level out.
        """
        planted = tmp_path / "test_planted.py"
        planted.write_text(
            "import pytest\n\n\ndef test_one() -> None:\n"
            '    pytest.skip("not today")\n'
        )

        assert not _can_end_its_own_collection(planted)

    def test_a_file_that_merely_collects_nothing_does_not(self, tmp_path: Path) -> None:
        """An emptied `test_*.py` is the case a row of 0 must not cover."""
        planted = tmp_path / "test_planted.py"
        planted.write_text("import pytest\n")

        assert not _can_end_its_own_collection(planted)


class TestWhatTheCollectorReadsAsATest:
    """`_declares_a_test`, driven against planted files.

    **The name is where the collector starts and these are where it stops.**
    A first version read the name alone, and two review seats drove collection
    against planted files to find six spellings it passed that collect
    nothing; this file's own probe then found a seventh. Every one of them is
    an arm below, because each is a way a row of 0 buys a file a permanent
    excuse with the whole suite green at exit 0.
    """

    def test_a_test_inside_a_class_counts_as_one_the_file_declares(
        self, tmp_path: Path
    ) -> None:
        """Where the collector looks, so the class body is read and a function
        body is not."""
        planted = tmp_path / "test_planted.py"
        planted.write_text(
            "class TestThing:\n    def test_one(self) -> None: ...\n"
        )
        buried = tmp_path / "test_buried.py"
        buried.write_text("def helper() -> None:\n    def test_one() -> None: ...\n")

        assert _declares_a_test(planted, ("test",), ("Test",))
        assert not _declares_a_test(buried, ("test",), ("Test",))
        # The class name rule is the collector's too, so a test hidden in a
        # class it would not read is not one this file declares.
        assert not _declares_a_test(planted, ("test",), ("Suite",))
    def test_a_class_with_a_constructor_declares_no_test(
        self, tmp_path: Path
    ) -> None:
        """`Class.collect` refuses such a class with a warning and no items,
        so a test written inside one runs on no engine at all."""
        for constructor in ("def __init__(self): ...", "def __new__(cls): ..."):
            planted = tmp_path / "test_planted.py"
            planted.write_text(
                f"class TestThing:\n    {constructor}\n\n"
                "    def test_one(self) -> None: ...\n"
            )

            assert not _declares_a_test(planted, ("test",), ("Test",)), constructor

    def test_a_class_that_switches_itself_off_declares_no_test(
        self, tmp_path: Path
    ) -> None:
        planted = tmp_path / "test_planted.py"
        planted.write_text(
            "class TestThing:\n    __test__ = False\n\n"
            "    def test_one(self) -> None: ...\n"
        )

        assert not _declares_a_test(planted, ("test",), ("Test",))

    def test_a_module_that_switches_itself_off_declares_no_test(
        self, tmp_path: Path
    ) -> None:
        """The same attribute one level out, which `PyCollector.collect` asks
        first and which empties the file rather than the class."""
        planted = tmp_path / "test_planted.py"
        planted.write_text("__test__ = False\n\n\ndef test_one() -> None: ...\n")

        assert not _declares_a_test(planted, ("test",), ("Test",))

    def test_a_test_switched_off_by_attribute_is_not_declared(
        self, tmp_path: Path
    ) -> None:
        """The spelling that is not in the `def` at all: the collector reads
        the module's `__dict__` after it has run, so a statement below the
        definition decides."""
        planted = tmp_path / "test_planted.py"
        planted.write_text(
            "def test_one() -> None: ...\n\n\ntest_one.__test__ = False\n"
        )

        assert not _declares_a_test(planted, ("test",), ("Test",))

    def test_a_declared_name_rebound_afterwards_is_not_declared(
        self, tmp_path: Path
    ) -> None:
        """Three places a name can be rebound, and the collector reads the
        module's `__dict__` after it has run, so all three decide.

        The second is the one this file's own probe found after the six a
        review seat drove: the method is a test by name and the collector
        never reaches it, because the name that owns it no longer holds the
        class. **The third was found by collection a round later**, and it is
        why the special case here is the attribute rather than the ownership:
        rebinding the method itself leaves the class in place and collects
        nothing.
        """
        function = tmp_path / "test_function.py"
        function.write_text("def test_one() -> None: ...\n\n\ntest_one = None\n")
        owner = tmp_path / "test_owner.py"
        owner.write_text(
            "class TestThing:\n    def test_one(self) -> None: ...\n\n\n"
            "TestThing = None\n"
        )
        method = tmp_path / "test_method.py"
        method.write_text(
            "class TestThing:\n    def test_one(self) -> None: ...\n\n\n"
            "TestThing.test_one = None\n"
        )

        assert not _declares_a_test(function, ("test",), ("Test",))
        assert not _declares_a_test(owner, ("test",), ("Test",))
        assert not _declares_a_test(method, ("test",), ("Test",))

    def test_a_fixture_the_collector_would_name_is_not_a_test(
        self, tmp_path: Path
    ) -> None:
        """`istestfunction` requires no fixture marker, so a fixture whose
        name the pattern reads is collected as nothing. Three spellings,
        because the marker is resolved through the same bindings the skip
        predicate reads and a name match would see one of them."""
        # **Written as lines and joined**, because a decorator reached by a
        # newline escape inside a string literal reads as an address: the
        # escape's own last character sits where the local part goes, and the
        # published tree refuses an address outside the documentation
        # domains. This file publishes. Found by that guard rather than by
        # reading, and this comment is written around it for the same reason.
        for source in (
            ["import pytest", "", "", "@pytest.fixture", "def test_one(): ..."],
            [
                "import pytest as pt",
                "",
                "",
                "@pt.fixture(scope='module')",
                "def test_one(): ...",
            ],
            ["from pytest import fixture", "", "", "@fixture", "def test_one(): ..."],
        ):
            planted = tmp_path / "test_planted.py"
            planted.write_text("\n".join(source) + "\n")

            assert not _declares_a_test(planted, ("test",), ("Test",)), source

    def test_a_decorated_definition_the_collector_would_read_is_not_a_test(
        self, tmp_path: Path
    ) -> None:
        """A decorator replaces the name it decorates, and the whitelist did
        not look at one.

        Definitions were skipped by kind, so a decorated test class collected
        nothing while every rule here passed, and a planted file holding the
        guarded skip and one such class took the whole arm set green.

        **Three depths refused and one kept, which is the census and not a
        judgement.** A class at any depth and a top level function: every
        decorator on one in this tree is rooted at `pytest`, and no nested
        protected class carries one at all, so the rule is free. A **method**
        is kept, because the same rule there would refuse property based
        generation and a transport mock, 70 decorators in this corpus.
        """
        wrap = "def wrap(thing):\n    return None\n\n\n"
        refused = {
            "a top level class": wrap + "@wrap\nclass TestThing:\n"
            "    def test_one(self) -> None: ...\n",
            "a top level function": wrap + "@wrap\ndef test_one() -> None: ...\n",
            "a nested class": wrap + "class TestOuter:\n    @wrap\n"
            "    class TestInner:\n        def test_one(self) -> None: ...\n",
        }
        # The two marker cases are written as lines and joined, for the
        # reason the fixture arm above gives: a decorator reached by a
        # newline escape inside a string literal reads as an address, and
        # this file publishes.
        marked = ["class TestThing:", "    def test_one(self) -> None: ..."]
        kept = {
            "a marker on a class": "\n".join(
                ["import pytest", "", "", "@pytest.mark.slow", *marked]
            )
            + "\n",
            "a marker on a top level function": "\n".join(
                [
                    "import pytest",
                    "",
                    "",
                    "@pytest.mark.parametrize('n', [1])",
                    "def test_one(n) -> None: ...",
                ]
            )
            + "\n",
            "a marker through an alias": "\n".join(
                ["import pytest as pt", "", "", "@pt.mark.slow", *marked]
            )
            + "\n",
            "a third party decorator on a method": wrap
            + "class TestThing:\n    @wrap\n    def test_one(self) -> None: ...\n",
            "an undecorated nested class": "class TestOuter:\n"
            "    class TestInner:\n        def test_one(self) -> None: ...\n",
            "a decorated helper beside a test": wrap
            + "@wrap\ndef helper() -> None: ...\n\n\n"
            "class TestThing:\n    def test_one(self) -> None: ...\n",
        }

        for what, source in refused.items():
            planted = tmp_path / "test_planted.py"
            planted.write_text(source)

            assert not _declares_a_test(planted, ("test",), ("Test",)), what

        for what, source in kept.items():
            planted = tmp_path / "test_planted.py"
            planted.write_text(source)

            assert _declares_a_test(planted, ("test",), ("Test",)), what

    def test_a_live_sibling_keeps_the_file_declaring_a_test(
        self, tmp_path: Path
    ) -> None:
        """The other direction, so the refusals above are not a predicate
        that answers False on anything interesting.

        An unrelated marker is not a fixture and a truthy declaration is not
        a switch off. **And a rebinding reaches the name it names and no
        other**: an attribute that is not a test leaves its class alone, and
        one test method rebound leaves its sibling counted. Those two are
        where closing the method rebinding would otherwise have bought a
        false refusal.
        """
        planted = tmp_path / "test_planted.py"
        planted.write_text(
            "import pytest\n\n\nclass TestOff:\n    __test__ = False\n\n"
            "    def test_a(self) -> None: ...\n\n\nclass TestOn:\n"
            "    __test__ = True\n\n    @pytest.mark.slow\n"
            "    def test_b(self) -> None: ...\n"
        )
        beside = tmp_path / "test_beside.py"
        beside.write_text(
            "class TestThing:\n    def test_a(self) -> None: ...\n\n"
            "    def test_b(self) -> None: ...\n\n\n"
            "TestThing.test_a = None\nTestThing.helper = None\n"
        )

        assert _declares_a_test(planted, ("test",), ("Test",))
        assert _declares_a_test(beside, ("test",), ("Test",))

    def test_the_end_state_an_evasion_reached_is_not_silenced_by_the_engine(
        self, tmp_path: Path
    ) -> None:
        """The whole file a review seat drove to a green suite at exit 0.

        A module level skip and one `Test` class carrying `__test__ = False`,
        given a row of 0 with the block regenerated to the figures the arm
        itself printed, opened the gate, ran all three count arms and passed
        both document arms. The skip half still answers True, which is why
        this arm asks the pair rather than either half.
        """
        planted = tmp_path / "test_planted.py"
        planted.write_text(
            "import pytest\n\n"
            'pytest.skip("nothing here any more", allow_module_level=True)\n\n\n'
            "class TestQuiet:\n    __test__ = False\n\n"
            "    def test_a(self) -> None: ...\n"
        )

        assert _can_end_its_own_collection(planted)
        assert not _is_silenced_by_the_engine(planted, ("test",), ("Test",))


class TestWhatARowOfZeroClaims:
    """`not_collected_here` reads the document, `_is_silenced_by_the_engine`
    reads the file, and a row of 0 is what the pair holds.

    **Named for the claim rather than for a count of the instruments under
    it**, which was two and is now three.

    **Driven against planted inputs.** On this tree each one answers the same
    way about the same single file every run, so a function returning a
    constant would satisfy every rule above it and the gate would be open
    again with nothing red. Measured by a review seat: with either arm's own
    comprehension replaced by `False`, a targeted run came back green, which
    is why the comprehensions are functions driven here rather than bodies
    inside the arms.
    """

    def test_a_row_of_zero_is_read_and_a_counted_row_is_not(self) -> None:
        assert not_collected_here(
            "| `test_a.py` | 0 | Not on this engine |\n| `test_b.py` | 5 | Here |\n"
        ) == frozenset({"test_a.py"})

    def test_a_file_with_a_test_and_a_module_level_skip_is_silenced_by_the_engine(
        self, tmp_path: Path
    ) -> None:
        planted = tmp_path / "test_planted.py"
        planted.write_text(
            "import pytest\n\nif True:\n"
            '    pytest.skip("no engine here", allow_module_level=True)\n\n\n'
            "def test_one() -> None: ...\n"
        )

        assert _is_silenced_by_the_engine(planted, ("test",), ("Test",))

    def test_an_emptied_file_is_not_silenced_by_the_engine(
        self, tmp_path: Path
    ) -> None:
        """The permanent excuse, which a module level skip alone buys.

        Driven on the branch before this half existed: a planted `test_*.py`
        holding only this skip, given a row of 0, left the gate open, all three
        count arms running and the whole suite green at exit 0.
        """
        planted = tmp_path / "test_planted.py"
        planted.write_text(
            "import pytest\n\n"
            'pytest.skip("nothing here any more", allow_module_level=True)\n'
        )

        assert _can_end_its_own_collection(planted)
        assert not _is_silenced_by_the_engine(planted, ("test",), ("Test",))

    def test_a_module_body_that_only_declares_is_recognised(
        self, tmp_path: Path
    ) -> None:
        """What the whitelist costs, which is the half worth arming.

        A rule that refuses everything refuses every door, so the arm that
        matters is the one saying ordinary module bodies are still allowed to
        carry a row of 0. The shapes below are the ones a reader would expect
        a whitelist to refuse and that it does not. **No count of the corpus
        beside them**, because it moves with the tree; what the rule rests on
        is the property, and the files it does refuse are named by shape in
        `_unrecognised`.
        """
        skip = (
            "import pytest\n\nif 1 != 2:\n"
            "    pytest.skip('no', allow_module_level=True)\n\n\n"
        )
        bodies = {
            "a module level constant": "BACKEND = 1\n",
            "an annotated constant": "ROWS: list[int] = [1, 2]\n",
            "a parametrisation table": "CASES = [(1, 2), (3, 4)]\n",
            "an export list": "__all__ = ['TestThing']\n",
            "a conditional import": (
                "try:\n    import lxml\nexcept ImportError:\n    lxml = None\n"
            ),
        }
        tail = "\n\nclass TestThing:\n    def test_one(self) -> None: ...\n"

        for what, body in bodies.items():
            planted = tmp_path / "test_planted.py"
            planted.write_text(skip + body + tail)

            assert _is_silenced_by_the_engine(planted, ("test",), ("Test",)), what

    def test_a_statement_that_could_reach_a_test_is_refused(
        self, tmp_path: Path
    ) -> None:
        """Eight spellings and one arm, which is the whole of the change.

        **Each is a member of a family with no last member**, and four
        rounds proved it: every one closed the way of putting a test out of
        the collector's reach that had just been demonstrated, and the next
        round found another. Eight more were then measured by collection at
        once. An arm each would have been the fifth round of the same
        mistake, so the rule is a whitelist and this loop is what says the
        whitelist covers them rather than eight arms saying it covers eight.

        The refusal names the statement and its line, because a whitelist
        that only says no is one the next reader widens blindly.
        """
        skip = (
            "import pytest\n\nif 1 != 2:\n"
            "    pytest.skip('no', allow_module_level=True)\n\n\n"
        )
        owned = "class TestThing:\n    def test_one(self) -> None: ...\n\n\n"
        loose = "def test_one() -> None: ...\n\n\n"
        doors = {
            "a tuple target on the owner": owned + "TestThing, _x = None, 1\n",
            "a tuple target on the test": loose + "test_one, _x = None, 1\n",
            "deleting the method": owned + "del TestThing.test_one\n",
            "deleting the class": owned + "del TestThing\n",
            "a dynamic set": owned + "setattr(TestThing, 'test_one', None)\n",
            "an alias then a rebinding": (
                owned + "Alias = TestThing\nAlias.test_one = None\n"
            ),
            "a nested class rebound": (
                "class TestOuter:\n    class TestInner:\n"
                "        def test_one(self) -> None: ...\n\n\n"
                "TestOuter.TestInner = None\n"
            ),
            "a namespace write": loose + "globals()['test_one'] = None\n",
        }

        for what, body in doors.items():
            planted = tmp_path / "test_planted.py"
            planted.write_text(skip + body)

            assert not _is_silenced_by_the_engine(
                planted, ("test",), ("Test",)
            ), what
            assert _statements_that_could_reach_a_test(
                planted, ("test",), ("Test",)
            ), what

    def test_a_class_body_is_read_the_way_the_module_body_is(
        self, tmp_path: Path
    ) -> None:
        """The whitelist skipped a class definition by kind, which is the
        construction that blocked the round before this one.

        A class body holds exactly the statements the rule refuses at module
        level and none of them was read. Measured by collection, each of
        these collects nothing, raises no refusal and answered silenced.
        """
        skip = (
            "import pytest\n\nif 1 != 2:\n"
            "    pytest.skip('no', allow_module_level=True)\n\n\n"
        )
        doors = {
            "the test rebound after its own def": "class TestThing:\n"
            "    def test_one(self) -> None: ...\n\n    test_one = None\n",
            "the test deleted after its def": "class TestThing:\n"
            "    def test_one(self) -> None: ...\n\n    del test_one\n",
            "the test replaced by a number": "class TestThing:\n"
            "    def test_one(self) -> None: ...\n\n    test_one = 1\n",
            "the same inside a nested class": "class TestOuter:\n"
            "    class TestInner:\n"
            "        def test_one(self) -> None: ...\n\n"
            "        test_one = None\n",
        }
        ordinary = (
            "class TestThing:\n    CASES = [(1, 2)]\n\n"
            "    def test_one(self) -> None: ...\n"
        )

        for what, body in doors.items():
            planted = tmp_path / "test_planted.py"
            planted.write_text(skip + body)

            assert not _is_silenced_by_the_engine(
                planted, ("test",), ("Test",)
            ), what
            assert _statements_that_could_reach_a_test(
                planted, ("test",), ("Test",)
            ), what

        # The cost, which is what makes the rule worth having rather than
        # a refusal of every class: an ordinary class level constant stays.
        planted = tmp_path / "test_planted.py"
        planted.write_text(skip + ordinary)

        assert _is_silenced_by_the_engine(planted, ("test",), ("Test",))

    def test_nothing_anywhere_may_bind_a_protected_name(
        self, tmp_path: Path
    ) -> None:
        """The two containers the whitelist does not read, and the binding
        forms that reach past it.

        A non protected class body and a function body both execute at
        import with the whole module namespace in reach, and reading them
        would refuse almost every helper in this tree. So the rule is not
        about containers: it is that nothing anywhere binds or writes a
        protected name. `_written_to` carries the enumeration of binding
        forms it rests on and why that enumeration is the closed one.

        **The `kept` loop below is what keeps the `doors` loop from being
        vacuous, and that is not in either loop's assertion.** Each door row
        asserts only that the file is not silenced, so none of them says
        *which* statement did the refusing. They all share a prefix, and if
        that prefix ever started refusing on its own, every door row would
        pass while this test proved nothing. What stands in the way is the
        `kept` rows, which hold that the same prefix with an innocent body is
        still silenced. Deleting them would leave a loop of thirteen green
        assertions about nothing.
        """
        skip = (
            "import pytest\n\nif 1 != 2:\n"
            "    pytest.skip('no', allow_module_level=True)\n\n\n"
        )
        owned = "class TestThing:\n    def test_one(self) -> None: ...\n\n\n"
        doors = {
            "a helper class body": owned + "class Helper:\n    TestThing.test_one = None\n",
            "a helper function body": owned
            + "def wipe() -> None:\n    TestThing.test_one = None\n\n\n_ = wipe()\n",
            "a helper reached by a decorator": owned
            + "def wipe(thing):\n    TestThing.test_one = None\n    return thing\n\n\n"
            + "@wipe\ndef helper() -> None: ...\n",
            "a helper reached by a default argument": owned
            + "def wipe():\n    TestThing.test_one = None\n    return 1\n\n\n"
            + "def helper(value=wipe()) -> None: ...\n",
            "a nested protected class, from a helper": "class TestOuter:\n"
            "    class TestInner:\n        def test_one(self) -> None: ...\n\n\n"
            "class Helper:\n    TestOuter.TestInner = None\n",
            "a deletion in a helper": owned
            + "def wipe() -> None:\n    del TestThing.test_one\n\n\n_ = wipe()\n",
            "a global declaration in a helper": owned
            + "def wipe() -> None:\n    global TestThing\n"
            "    for TestThing in [None]:\n        pass\n\n\n_ = wipe()\n",
            "a namespace call in a helper": owned
            + "def wipe() -> None:\n    setattr(TestThing, 'test_one', None)\n\n\n"
            "_ = wipe()\n",
            "an import alias": owned + "import os as TestThing\n",
            "a star import": owned + "from os.path import *\n",
            "a star import in a conditional": owned
            + "if True:\n    from os.path import *\n",
            "a star import in a try": owned
            + "try:\n    from os.path import *\nexcept ImportError:\n    pass\n",
            "an except handler": owned + "try:\n    import os\n"
            "except ImportError as TestThing:\n    pass\n",
        }
        kept = {
            "a helper with a local named like a test": owned
            + "def helper() -> int:\n    test_one = 1\n    return test_one\n",
            "a helper class with an ordinary attribute": owned
            + "class Helper:\n    CASES = [1]\n",
            "a helper reading a protected name": owned
            + "def helper():\n    return TestThing\n",
            "a namespace call on something else": owned
            + "class Helper:\n    NAMES = frozenset(n for n in vars(dict) if n)\n",
            "an ordinary import and an ordinary handler": owned
            + "try:\n    import os\nexcept ImportError as exc:\n    os = exc\n",
        }

        for what, body in doors.items():
            planted = tmp_path / "test_planted.py"
            planted.write_text(skip + body)

            assert not _is_silenced_by_the_engine(
                planted, ("test",), ("Test",)
            ), what

        for what, body in kept.items():
            planted = tmp_path / "test_planted.py"
            planted.write_text(skip + body)

            assert _is_silenced_by_the_engine(planted, ("test",), ("Test",)), what

        # **The star import clause is conditioned on a protected name
        # existing, and only the reporting function witnesses that.** A file
        # declaring no test cannot carry a row of 0 at all, so the silencing
        # predicate is False there for a different reason and would have
        # read as this condition working.
        planted = tmp_path / "test_planted.py"
        planted.write_text("def helper() -> None: ...\n\n\nfrom os.path import *\n")

        assert _statements_that_could_reach_a_test(planted, ("test",), ("Test",)) == []

    def test_a_walrus_binding_a_protected_name_is_refused(
        self, tmp_path: Path
    ) -> None:
        """The row of the table that was discharged by a sentence.

        The sentence said the value rule catches one, which holds only where
        the walrus sits inside a statement that rule scans. A definition is
        accepted by kind and nothing scans its default arguments, its
        decorator arguments or its bases, and all three evaluate at import in
        module scope. Censused free: 29 walrus expressions in this corpus and
        none binds a protected name.
        """
        skip = (
            "import pytest\n\nif 1 != 2:\n"
            "    pytest.skip('no', allow_module_level=True)\n\n\n"
        )
        owned = "class TestThing:\n    def test_one(self) -> None: ...\n\n\n"
        doors = {
            "in a default argument": owned
            + "def helper(value=(TestThing := None)) -> None: ...\n",
            "in a decorator argument": owned
            + "def deco(thing):\n    return lambda given: given\n\n\n"
            + "@deco((TestThing := None))\ndef helper() -> None: ...\n",
            "in a class base": owned
            + "class Helper((TestThing := object)):\n    pass\n",
            "inside a module level statement": owned + "_ = [(TestThing := None)]\n",
        }

        for what, body in doors.items():
            planted = tmp_path / "test_planted.py"
            planted.write_text(skip + body)

            assert not _is_silenced_by_the_engine(
                planted, ("test",), ("Test",)
            ), what

    def test_a_container_that_can_rebind_is_refused_by_kind(
        self, tmp_path: Path
    ) -> None:
        """A witness for a row discharged rather than refused.

        The table discharges a loop or context manager target at module level
        to the container being refused by kind, and there is no rule over the
        binding itself. **A row discharged by prose is what the walrus was**,
        so this drives it: the refusal arrives, it names the container, and
        the second half shows why the container refusal is load bearing, by
        executing the module and reading the namespace the collector reads.

        **What it holds is that the message names the container, not that
        the container is what refused.** Those come apart in general. Here
        the attribution is sound for a reason worth writing rather than
        assuming: the write rule has no branch for either statement kind, so
        the whitelist falling through is the only thing that can report one,
        and a future branch over them would make this arm prove less than it
        reads.
        """
        skip = (
            "import pytest\n\nif 1 != 2:\n"
            "    pytest.skip('no', allow_module_level=True)\n\n\n"
        )
        bodies = {
            "a loop target": "class TestThing:\n"
            "    def test_one(self) -> None: ...\n\n\n"
            "for TestThing in [None]:\n    pass\n",
            "a context manager target": "import contextlib\n\n\n"
            "class TestThing:\n    def test_one(self) -> None: ...\n\n\n"
            "with contextlib.nullcontext(None) as TestThing:\n    pass\n",
        }
        kinds = {
            "a loop target": "For at line",
            "a context manager target": "With at line",
        }

        for what, body in bodies.items():
            planted = tmp_path / "test_planted.py"
            planted.write_text(skip + body)
            reported = _statements_that_could_reach_a_test(
                planted, ("test",), ("Test",)
            )

            assert not _is_silenced_by_the_engine(
                planted, ("test",), ("Test",)
            ), what
            assert any(kinds[what] in one for one in reported), (what, reported)

            # The container refusal is the only thing holding this, so the
            # binding it would otherwise allow is shown rather than asserted.
            namespace: dict[str, object] = {}
            exec(compile(body, "<planted>", "exec"), namespace)

            assert namespace["TestThing"] is None, what

    def test_a_binding_the_collector_never_reads_leaves_the_test(
        self, tmp_path: Path
    ) -> None:
        """The other row discharged rather than refused, with its witness,
        and the witness split the row.

        A parameter and a comprehension target bind where the collector never
        reads and are accepted. **An accept is not that property**: the
        property is that the test is still there afterwards, so the second
        half executes the module and reads the namespace
        `PyCollector.collect` reads, an instrument outside this file rather
        than its own parse of the same text.

        **It executes into a bare dictionary, which is nearly an import and
        is not one**: no module object, no `__name__`, no entry in the module
        table. Immaterial for a parameter and a comprehension target, which
        touch none of those. It would matter to anybody reusing this harness
        for a case that reaches the module through that table, and that is
        one of the conceded doors rather than a row here.

        **A local was in the same row and is not in the same case.** A local
        assignment is an assignment, so the walk refuses it where it shadows
        a protected name, and so is an attribute of an unprotected class.
        Both are false refusals, both censused free, and both are loud. The
        third part below is what says so.
        """
        skip = (
            "import pytest\n\nif 1 != 2:\n"
            "    pytest.skip('no', allow_module_level=True)\n\n\n"
        )
        head = (
            "def test_alone() -> None: ...\n\n\n"
            "class TestThing:\n    def test_one(self) -> None: ...\n\n\n"
        )
        body = head + (
            "def helper(test_alone: int = 1) -> list[int]:\n"
            "    return [test_alone for test_alone in range(2)]\n"
        )
        planted = tmp_path / "test_planted.py"
        planted.write_text(skip + body)

        assert _is_silenced_by_the_engine(planted, ("test",), ("Test",))
        assert _statements_that_could_reach_a_test(planted, ("test",), ("Test",)) == []

        namespace: dict[str, object] = {}
        exec(compile(body, "<planted>", "exec"), namespace)
        collected = namespace["TestThing"]

        assert callable(namespace["test_alone"])
        assert isinstance(collected, type)
        assert callable(getattr(collected, "test_one", None))

        # The half of that row this walk refuses rather than discharges,
        # which the witness above found by being written.
        for what, shadow in {
            "a local": "def helper() -> int:\n    TestThing = 1\n    return TestThing\n",
            "an unprotected class attribute": "class Helper:\n    TestThing = 1\n",
        }.items():
            planted.write_text(skip + head + shadow)

            assert not _is_silenced_by_the_engine(
                planted, ("test",), ("Test",)
            ), what

    def test_a_top_level_name_defined_twice_is_refused(
        self, tmp_path: Path
    ) -> None:
        """The second definition wins and the first is gone, so a class
        redefined under a name the collector reads can lose its tests to a
        later definition carrying a falsy declaration.

        Censused free: no file in this corpus defines a top level name twice.
        """
        skip = (
            "import pytest\n\nif 1 != 2:\n"
            "    pytest.skip('no', allow_module_level=True)\n\n\n"
        )
        again = {
            "a class": "class TestThing:\n"
            "    def test_one(self) -> None: ...\n\n\n"
            "class TestThing:\n    __test__ = False\n",
            "a function": "def test_one() -> None: ...\n\n\n"
            "def test_one() -> None: ...\n",
        }

        for what, body in again.items():
            planted = tmp_path / "test_planted.py"
            planted.write_text(skip + body)

            assert not _is_silenced_by_the_engine(
                planted, ("test",), ("Test",)
            ), what
            assert any(
                "defined again" in reason
                for reason in _statements_that_could_reach_a_test(
                    planted, ("test",), ("Test",)
                )
            ), what

    def test_a_row_of_zero_on_a_collected_file_is_reported(self) -> None:
        """The arm's own comprehension, driven.

        On this tree it answers about the same single file every run, so
        replacing its condition with `False` left the whole suite green.
        Driven here against a planted register and a planted census, which is
        what makes the arm above an arm.
        """
        census = _planted({"test_a.py": 10}, {"test_a.py"})
        register = "| `test_a.py` | 0 | Not on this engine |\n"

        assert _rows_of_zero_that_collected(census, register) == [
            "test_a.py: stated as 0, collected 10"
        ]
        assert _rows_of_zero_that_collected(_planted({}, {"test_a.py"}), register) == []

    def test_a_row_of_zero_on_a_file_with_nothing_in_it_is_reported(
        self, tmp_path: Path
    ) -> None:
        """The sibling comprehension, driven the same way and for the same
        reason: replacing its membership test with `False` was also green."""
        (tmp_path / "test_quiet.py").write_text(
            'import pytest\n\npytest.skip("gone", allow_module_level=True)\n'
        )
        (tmp_path / "test_engine.py").write_text(
            "import pytest\n\nif True:\n"
            '    pytest.skip("not here", allow_module_level=True)\n\n\n'
            "def test_one() -> None: ...\n"
        )
        census = _planted({}, {"test_quiet.py", "test_engine.py"})
        register = "| `test_quiet.py` | 0 | Gone |\n| `test_engine.py` | 0 | Elsewhere |\n"

        assert _rows_of_zero_with_no_engine_reason(census, register, tmp_path) == [
            "test_quiet.py"
        ]


class TestTheGateComparesTwoInstruments:
    """`_refusal` and `_excused`, which are the skip itself.

    **The skip and not a set difference.** Four arms here were named for the
    gate and held a method on `Census`, so the message the gate prints was
    driven by nothing and could be written for one side of the comparison and
    misdirect on the other with no arm to say so.
    """

    def test_the_gate_opens_when_the_excused_file_is_the_only_difference(
        self,
    ) -> None:
        """`_refusal` and not `Census.silent`, because what used to be driven
        here was the set difference and not the gate.

        Four arms named for the gate held a method, and the skip itself, which
        is the thing the branch exists to open and shut, was driven by nothing.
        That is why the message below could be written for one side of the
        comparison and misdirect on the other with no arm to say so.
        """
        census = _planted({"test_a.py": 10}, {"test_a.py", "test_quiet.py"})

        assert _refusal(census, frozenset({"test_quiet.py"})) is None

    def test_the_gate_names_a_file_that_collected_nothing_and_is_not_excused(
        self,
    ) -> None:
        """The fail open this slot exists to close, as it was."""
        census = _planted({"test_a.py": 10}, {"test_a.py", "test_quiet.py"})

        refusal = _refusal(census, frozenset())

        assert refusal is not None
        assert "test_quiet.py" in refusal

    def test_the_gate_names_an_excused_file_that_collected(self) -> None:
        """Symmetric, so the subtraction cannot turn a live file into a hole."""
        census = _planted(
            {"test_a.py": 10, "test_quiet.py": 6}, {"test_a.py", "test_quiet.py"}
        )

        refusal = _refusal(census, frozenset({"test_quiet.py"}))

        assert refusal is not None
        assert "test_quiet.py" in refusal

    def test_the_gate_still_names_a_narrowed_run(self) -> None:
        census = _planted(
            {"test_a.py": 10}, {"test_a.py", "test_b.py", "test_quiet.py"}
        )

        refusal = _refusal(census, frozenset({"test_quiet.py"}))

        assert refusal is not None
        assert "test_b.py" in refusal

    def test_the_gate_offers_a_row_of_zero_only_for_the_side_that_takes_one(
        self,
    ) -> None:
        """The two sides of the comparison get two sentences.

        One message served both and it said, on a narrowed walk, that the run
        had collected more test files than the tree holds, offering a row of 0
        for files that do collect. Applying that remedy reds
        `test_a_row_of_zero_names_a_file_this_run_did_not_collect`, so the one
        place a reader looks prescribed a fix that breaks a sibling arm.
        """
        walk_short = _planted({"test_a.py": 10, "test_b.py": 5}, {"test_a.py"})
        run_short = _planted({"test_a.py": 10}, {"test_a.py", "test_b.py"})

        from_the_walk = _refusal(walk_short, frozenset())
        from_the_run = _refusal(run_short, frozenset())

        assert from_the_walk is not None
        assert from_the_run is not None
        assert "the remedy is a row of 0 for it" not in from_the_walk
        assert "the walk going wrong" in from_the_walk
        assert "the remedy is a row of 0 for it" in from_the_run
        assert "the walk going wrong" not in from_the_run

    def test_an_internal_module_this_engine_cannot_run_is_excused(
        self, tmp_path: Path
    ) -> None:
        """The fourth cell, which has no row to be excused by.

        A file the publish gate strips cannot be named in a published
        register, so the subtraction for it is read off the file. Driven on
        the branch before it existed: an unconditional module level skip
        planted in a stripped file left the whole suite green with the
        register publishing the figures of a different run and nothing
        saying so.
        """
        (tmp_path / "test_stripped.py").write_text(
            '"""Notes.\n\n**This file is internal.**\n"""\n\nimport pytest\n\n'
            "if True:\n"
            '    pytest.skip("not this engine", allow_module_level=True)\n\n\n'
            "def test_one() -> None: ...\n"
        )
        census = _planted({"test_a.py": 1}, {"test_a.py", "test_stripped.py"})

        assert _excused(census, "", tmp_path) == frozenset({"test_stripped.py"})
        assert _refusal(census, _excused(census, "", tmp_path)) is None

    def test_an_internal_module_that_merely_collects_nothing_is_not_excused(
        self, tmp_path: Path
    ) -> None:
        """The same half of the rule the row of 0 has.

        Without it the fourth cell's fix would hand an emptied stripped file
        the permanent excuse the row of 0 is refused.
        """
        (tmp_path / "test_stripped.py").write_text(
            '"""Notes.\n\n**This file is internal.**\n"""\n\nimport pytest\n\n'
            'pytest.skip("nothing here any more", allow_module_level=True)\n'
        )
        census = _planted({"test_a.py": 1}, {"test_a.py", "test_stripped.py"})

        assert _excused(census, "", tmp_path) == frozenset()

    def test_a_published_module_that_collects_nothing_is_not_excused(
        self, tmp_path: Path
    ) -> None:
        """The cell that stays in the skip, and deliberately.

        Such a file can carry a row of 0 and is required to, so the gate asks
        the document for it rather than the file. Its arrival is loud either
        way, because `test_every_file_with_no_row_is_one_the_register_may_not
        _name` reds on a published file with no row.
        """
        (tmp_path / "test_loud.py").write_text(
            "import pytest\n\nif True:\n"
            '    pytest.skip("not this engine", allow_module_level=True)\n\n\n'
            "def test_one() -> None: ...\n"
        )
        census = _planted({"test_a.py": 1}, {"test_a.py", "test_loud.py"})

        assert _excused(census, "", tmp_path) == frozenset()
        assert _refusal(census, frozenset()) is not None
