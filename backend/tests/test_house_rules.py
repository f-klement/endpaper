"""House rules that are cheaper to enforce than to review for.

Each class here exists because the same defect was found by a person, twice or
in two places, and the finding was mechanical enough that nobody should have to
find it a third time. Adding one is the right answer to "a reviewer caught this
again".
"""

import ast
import copy
import dataclasses
import importlib
import inspect
import os
import re
import warnings
from enum import StrEnum
from fnmatch import fnmatch
from pathlib import Path
from typing import Final, get_args

import httpx
import pytest
import respx
from pydantic import BaseModel
from sqlalchemy import CheckConstraint

import metadata
import models as orm  # noqa: F401  (registers the tables on Base.metadata)
import sources
import targets
from database import Base
from enums import CatalogueSource
from tests.helpers import silence_catalogues

BACKEND = Path(__file__).resolve().parent.parent


#: Directories under `backend/` that hold Python this project did not write.
#:
#: **A name per tool is what this used to be, and it failed the moment a new tool
#: appeared.** The list read `.venv` and `__pycache__`, which is every cache anybody had
#: seen locally; CI sets `UV_CACHE_DIR` inside the build directory, so `.uv-cache/`
#: appeared under `backend/` with `pydantic` and `cyclonedx` inside it, and the address
#: rule below reported `cyclonedx/model/contact.py` for reading a member's address. The
#: suite was green locally and red on every push, because the difference was the
#: environment rather than the tree.
#:
#: So the rule is structural: **a leading dot means a tool owns it**, which covers
#: `.venv`, `.uv-cache`, `.mypy_cache`, `.ruff_cache`, `.pytest_cache` and whatever is
#: next without an edit here. `__pycache__`, `node_modules`, `site-packages` and
#: `dist-packages` are the four that carry no dot and so still have to be named.
#:
#: **The last two are an environment rather than a tool, and the dot does not cover
#: one.** A virtualenv is `.venv` by convention and by nothing else: `test_marc.py`
#: records CI putting one inside `backend/` under another name, after which its walk
#: read `pydantic`, `packaging`, `urllib3` and the standard library's own `xml` and
#: reported them for breaking a rule about this application. What is closed about an
#: environment is not its directory's name but that everything installed into it sits
#: under `site-packages`, or `dist-packages` where Debian put it. Two modules reached
#: that conclusion independently, `test_covers.py` and `test_marc.py`, which is the same
#: signal this list already rests on for `__pycache__` and `node_modules`.
#:
#: **The stronger structural marker is deliberately not here.** An environment always
#: carries a `pyvenv.cfg` at its root, whatever it is called, and `test_marc.py` tests
#: for it when choosing which directories to descend. That is a filesystem question and
#: this is a path predicate: the diagonal below drives it against constructed trees and
#: `test_roster_counts.py` drives it against paths that need not exist. Naming the two
#: directories keeps this answerable from the path alone.
#:
#: **`root` exists because the same lesson was learned twice.** This rule was written
#: here, and `test_roster_counts.py` was written later with a name list of its own that
#: did not include `.uv-cache`. It went red on ten of twenty pushes to `main` and never
#: locally, on third party prose inside the cache: a Pygments lexer and a charset detector
#: each carry a small number beside a word the census reads as a roster noun, and it had no
#: verdict for either. Same environment difference, same enumeration, a different file.
#: **The first draft of this comment quoted both phrases and the census then reported the
#: comment**, which is the same recursion the dash table at the root records: a note about
#: a count contains the count. It takes a root so one rule can serve a walk from
#: `backend/` and a walk from the repository, rather than being stated twice and drifting
#: twice.
def _is_vendored(path: Path, root: Path = BACKEND) -> bool:
    return any(
        part.startswith(".")
        or part in {"__pycache__", "node_modules", "site-packages", "dist-packages"}
        for part in path.relative_to(root).parts
    )


def _python_sources(root: Path = BACKEND) -> list[Path]:
    """Every backend module, excluding the tests and the generated migrations.

    **`root` for the reason `_is_vendored` takes one**, one rung up: it is what
    lets `test_every_walk_refuses_a_vendored_path_of_this_kind` drive this walk
    against a tree it built. A walk asserted against this checkout is vacuous
    wherever the vendored directory is absent, which is every machine but the
    pipeline's, and that is the environment difference the comment above
    records.

    **The two names are matched against the path relative to that root**, not
    against the whole of it. Asked absolutely, a checkout under a directory
    called `tests` matched every file it held and the walk returned nothing.
    """
    return [
        path
        for path in root.rglob("*.py")
        if not {"tests", "migrations"} & set(path.relative_to(root).parts)
        and not _is_vendored(path, root)
    ]


def _test_sources(root: Path = BACKEND) -> list[Path]:
    """Every file in the test tree. `_python_sources` deliberately excludes it."""
    return [path for path in (root / "tests").rglob("*.py") if not _is_vendored(path, root)]


def _every_python_file(root: Path = BACKEND) -> list[Path]:
    """Every Python file under `backend/`, wider than both walks above.

    The two above drop the tests, and `_python_sources` drops the migrations
    too, because the rules that walk them are about application semantics and a
    fixture or a generated revision has no share in those. The compile rule at
    the foot of this file is the one exception, and the reason is that its
    failure is at import: a file that will not compile takes whatever imports
    it, so a migration stops `upgrade_to_head()` and a test module takes every
    guard in it. Which walk returned the file changes nothing about that.

    One walk and one exclusion, rather than `_python_sources() +
    _test_sources() + something for the migrations`, which is a list of three
    directory names whose fourth member nobody would remember to add.

    **The boundary is `backend/` rather than the repository.** Eleven tracked
    `.py` files live outside it, one under `frontend/scripts/` and ten under
    tooling directories this suite does not own. All eleven compile clean,
    measured 2026-09-02 on CPython 3.14.0, so the gap is worth knowing about
    rather than urgent. It is deliberately not closed from here: `BACKEND`
    anchors every walk in this file, and a rule reaching out of its own tree
    would report against code this suite has no claim on, in a checkout that may
    not even contain it.

    **`rglob`, so this is the working tree and not what git tracks.** An
    untracked file under `backend/` is compiled and reported, which is wanted:
    the suite runner ships the working tree, so a defect is seen before it is
    committed, where `git archive HEAD` cannot see it at all. The publishing
    tooling uses "ships" for that opposite sense, which is why the name here says
    `backend/` and the word is left to it.
    """
    return [path for path in root.rglob("*.py") if not _is_vendored(path, root)]


def _source_modules(root: Path = BACKEND) -> dict[str, str]:
    """`_python_sources()` read, keyed by path relative to `backend/`.

    **Here rather than in `tests/test_shelf.py`, which is where it used to
    live**, because the exclusion it rests on is `_is_vendored` and that is
    defined above. The shelf rules import this one; the reverse would be a cycle
    under `--import-mode=importlib`, since that module is imported for
    `_is_vendored` before it defines anything of its own.

    **The rules in other test modules that need this corpus import it**, and
    three of them used to keep a copy, each spelling the exclusion as
    `parts[0] not in {"tests", "migrations", ".venv"}`. That is the enumeration
    `_is_vendored` exists to replace, and it held the name of the directory a
    developer has rather than the one the pipeline creates.
    `test_no_other_test_module_defines_one_of_these_walks` is what stops the
    next copy of one of these being free to write, and its docstring says what
    that does not cover.
    """
    return {
        str(path.relative_to(root)): path.read_text() for path in _python_sources(root)
    }


def _every_file_a_tool_does_not_own(root: Path = BACKEND) -> list[Path]:
    """Every file under `backend/` that no tool owns, of whatever suffix.

    **A second instrument for the walk above, and the only reason it exists.**
    `_every_python_file` states its corpus as an exclusion (not vendored, not
    bytecode) and a rule stating an exclusion needs the complement to be
    checkable: this is what lets
    `test_the_walk_reaches_every_group_and_leaves_no_remainder` say that
    everything left out is a tool's or is not a `.py` file, rather than
    restating the filter it is testing.

    `os.walk` and a pruned `dirnames`, where the walk above is an `rglob` and a
    per path predicate. Same exclusion, different traversal, so a filter added
    to that function shows up here as a difference. Pruning is also what keeps
    this affordable: a `.venv` holds tens of thousands of files and neither walk
    should descend one.
    """
    found: list[Path] = []
    for directory, dirnames, filenames in os.walk(root):
        here = Path(directory)
        dirnames[:] = [name for name in dirnames if not _is_vendored(here / name, root)]
        found += [here / name for name in filenames]
    return found


#: One vendored path of each kind the walks above have to refuse.
#:
#: **Planted in two places, and that is what makes the fixture cover every walk.** A
#: walk that descends `tests/` alone never sees a directory beside it, so a fixture
#: planting each kind at the root only hands that walk a clean verdict without ever
#: putting a file in front of it. Measured on the first draft of this fixture: deleting
#: the exclusion from `_test_sources` was reported by nothing.
#:
#: **A `.py` and a second suffix per kind.** The `.py` is all four `rglob` walks can
#: see at all. The second is not what creates the detection, since the walk that prunes
#: reaches `mod.py` too: it is there so that walk is put in front of a file its own
#: suffix rule cannot excuse.
#:
#: A virtualenv and the pipeline's cache are both here because the enumeration this
#: replaced held the first and not the second, and the tree where that mattered is the
#: pipeline's rather than anybody's checkout. The last is the one no list of names can
#: hold, and it is what makes the rule structural rather than a longer list.
VENDORED_KINDS: Final = {
    "a virtualenv": ".venv/lib/python3.14/site-packages/pydantic",
    # The same packages one level out of reach of the dot. CI has already built
    # an environment under `backend/` whose directory carried no dot, and the
    # walk that went into it reported the standard library's own `xml` for
    # breaking a rule about this application. `.venv` above is caught by its
    # dot and would be caught with `site-packages` removed from the predicate,
    # so it is this row that drives that half and not that one.
    "an environment whose directory is not hidden": "env/lib/python3.14/site-packages/pydantic",
    "the cache the pipeline creates under backend": ".uv-cache/cyclonedx/model",
    "bytecode beside a module of ours": "routers/__pycache__",
    "a dependency tree": "node_modules/marked/lib",
    "a tool nobody has written yet": ".some-tool/wheel",
}

#: What the walks must still reach with all of that planted around them.
#:
#: One file per group the walks divide this tree into, so a walk that answered by
#: returning nothing fails here rather than passing the refusal above.
FIRST_PARTY: Final = (
    "shelf.py",
    "routers/loans.py",
    "tests/test_shelf.py",
    "migrations/versions/a1.py",
    "README.md",
)

#: What each walk must reach out of that, keyed by the name it is called here.
#:
#: **Compared as a whole against the walks this file holds**, so a walk added later
#: fails this until somebody says what it is for. Listing the walks was the shape the
#: refusal test was written to avoid, and a vacuity check that quietly skipped the new
#: walk would leave the refusal above as the only thing driving it, which is the half
#: that a walk returning nothing passes.
WHAT_EACH_WALK_REACHES: Final = {
    "_python_sources": {"shelf.py", "routers/loans.py"},
    "_source_modules": {"shelf.py", "routers/loans.py"},
    "_test_sources": {"tests/test_shelf.py"},
    "_every_python_file": {
        "shelf.py",
        "routers/loans.py",
        "tests/test_shelf.py",
        "migrations/versions/a1.py",
    },
    "_every_file_a_tool_does_not_own": set(FIRST_PARTY),
}


#: Both ways a module defines a function, because a rule reading one of them reads a
#: subset of its own corpus and says nothing about it.
#:
#: Not hypothetical here: this test tree already holds module level `async def`, so a walk
#: or a copy spelled that way is a shape the corpus contains rather than one nobody would
#: write, and this file already pairs the two elsewhere. **Both facts, neither counted.**
#: A count of either moves whenever somebody writes one more, this is a published file,
#: and nothing here recomputes it. Which sites they are is in the history.
_A_FUNCTION: Final = (ast.FunctionDef, ast.AsyncFunctionDef)


def _a_backend_with_vendored_code_in_it(root: Path, vendored: str) -> None:
    """Write a tree shaped like `backend/`, with one kind of vendored code in it.

    **In the test tree as well as beside it.** Which of the two a walk can reach
    is the walk's own business and not this function's, and a caller choosing
    per walk would be the fixture deciding what it is about to test.
    """
    for relative in FIRST_PARTY:
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("x = 1\n")
    for directory in (root / vendored, root / "tests" / vendored):
        for name in ("mod.py", "notes.md"):
            path = directory / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("x = 1\n")


def _walk_names() -> tuple[set[str], set[str]]:
    """The names in this module that decide what a walk reaches, as `(walks, all)`.

    **Read off this file rather than listed**, which is the same rule the walks
    themselves now follow: a list here would be a sixth name somebody has to
    remember, and the diagonal would report five clean while the new one went
    unexercised.

    A **walk** is the subset taking nothing but a `root`, which is what makes it
    drivable against a constructed tree. `_is_vendored` itself takes a path as
    well and is driven by the two tests above.

    **Every other name has to be a walk, and that is asserted rather than left
    as the reason for a subtraction.** A function that reaches the predicate and
    takes a second parameter, or spells its first `base`, would otherwise drop
    out of both guards while their floors still passed: the matcher would see
    one spelling and the tests would report on what it saw.

    **Deciding what vendored means and consuming what one of these returns are
    two different things, and only the first belongs here.** So a name joins on
    a **call that passes an argument**, which is what forwarding a root looks
    like, and not on a bare mention. A helper reading `_source_modules()` for
    the corpus decides nothing, and under the looser rule it failed the
    assertion above under a message describing a defect it did not have.

    **Taking the tree puts a function in regardless**, which is the half the
    call rule alone gets wrong: one that takes a root and then calls a walk
    with no argument ignores it, and dropping it out would leave the diagonal
    never driving it. In it, that walk reads this checkout instead of the
    constructed tree and every kind is reported against it.

    **Taking the tree is a parameter called `root` or a default of `BACKEND`,
    and the second is there because the first is one spelling.** The parameter
    name is the caller's choice and open, so a helper spelling it `base` and
    calling a walk with no argument satisfied neither arm and dropped out
    silently, which is the failure this clause exists to stop, one name over.
    `BACKEND` is this module's only name for the tree under test: measured on
    this file, it is the only path constant at module level and exactly the
    functions here that decide vendored code carry it as a default.

    The cost is stated rather than discovered: a helper taking the tree and only
    reading a corpus fires too. That is the same side as the rest of this rule,
    and being told about it is cheaper than the walk nothing drives.
    """
    reaches: set[str] = {"_is_vendored"}
    growing = True
    while growing:
        growing = False
        for node in ast.parse(Path(__file__).read_text()).body:
            if not isinstance(node, _A_FUNCTION) or node.name in reaches:
                continue
            parameters = [
                *node.args.posonlyargs,
                *node.args.args,
                *node.args.kwonlyargs,
            ]
            takes_the_tree = any(
                argument.arg == "root" for argument in parameters
            ) or any(
                isinstance(default, ast.Name) and default.id == "BACKEND"
                for default in [
                    *node.args.defaults,
                    *(one for one in node.args.kw_defaults if one is not None),
                ]
            )
            if any(
                (
                    isinstance(inner, ast.Call)
                    and isinstance(inner.func, ast.Name)
                    and inner.func.id in reaches
                    and inner.args
                )
                or (
                    takes_the_tree
                    and isinstance(inner, ast.Name)
                    and inner.id in reaches
                )
                for inner in ast.walk(node)
            ):
                reaches.add(node.name)
                growing = True
    walks = {
        node.name
        for node in ast.parse(Path(__file__).read_text()).body
        if isinstance(node, _A_FUNCTION)
        and node.name in reaches
        and [argument.arg for argument in node.args.args] == ["root"]
    }
    assert walks | {"_is_vendored"} == reaches, (
        "these reach the vendored rule and cannot be driven against a tree, so "
        f"nothing below covers them: {sorted(reaches - walks - {'_is_vendored'})}"
    )
    return walks, reaches


def _is_a_walk(node: ast.AST, defines_walk: bool = False) -> bool:
    """Whether this call reads a tree of Python files rather than one directory.

    **Read off the pattern and off the name `walk`, never off the receiver.** The
    version this replaced asked for `rglob` or an attribute of `os`, so
    `glob("**/*.py")`, `Path.walk()` and a bare `walk` imported from `os` all
    walked past it. Measured against four planted modules: one reported, three
    clean.

    `walk` under any spelling, because `os.walk`, `pathlib.Path.walk` and a bare
    import are one operation with three addresses, and which one a module reaches
    for says nothing about what it reads.

    **Whether the pattern could yield a `.py` file, never whether it ends in
    one.** A second version asked `pattern.endswith(".py")`, which reads the file
    kind off the tail exactly as the first read recursion off the method name:
    `rglob("*")` and `glob("**/*")` filtered in Python afterwards walked past it,
    and so did `rglob(pattern="*.py")`, whose `args` are empty. `fnmatch` answers
    the real question, so `*.ts*` and `*.md` stay out because no Python file can
    match them, and `*` and `**/*` come in because one can. A pattern this cannot
    read at all counts as a walk: assuming otherwise would make naming it the
    next evasion.

    **Two things share that word and neither is a filesystem walk**, so both are
    excluded by what the call is rather than by a list of the modules that have
    one. `ast.walk` takes a parse tree, and every module that walks a directory
    here also walks an `ast`, so a rule matching the bare word reports all of
    them and is deleted within the week. And a **locally defined** `walk` is a
    recursion helper over routes, JSON schemas or AST nodes: three modules in
    this tree have one, none of them touches the filesystem, and all three were
    reported by the first draft of this predicate.

    So `walk` counts when it is somebody else's: an attribute on anything but
    `ast`, or a bare call in a module that does not define `walk` itself, which
    is what `from os import walk` looks like. `defines_walk` is that second half
    and the caller supplies it, because it is a fact about the module rather than
    about the call.
    """
    if not isinstance(node, ast.Call):
        return False
    if (
        isinstance(node.func, ast.Attribute)
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id == "ast"
    ):
        return False
    name = (
        node.func.attr
        if isinstance(node.func, ast.Attribute)
        else node.func.id
        if isinstance(node.func, ast.Name)
        else ""
    )
    if name == "walk":
        return isinstance(node.func, ast.Attribute) or not defines_walk
    if name not in {"glob", "rglob"}:
        return False
    given = node.args or [
        keyword.value for keyword in node.keywords if keyword.arg == "pattern"
    ]
    if not given:
        return True
    pattern = given[0]
    if not isinstance(pattern, ast.Constant) or not isinstance(pattern.value, str):
        # A pattern this cannot read is reported rather than assumed shallow.
        return True
    could_be_python = fnmatch("one.py", pattern.value) or fnmatch(
        "under/a/directory/one.py", pattern.value
    )
    return could_be_python and (name == "rglob" or "**" in pattern.value)


def _reached(name: str, root: Path) -> set[str]:
    """One walk's answer over `root`, as paths relative to it.

    `_source_modules` hands back its corpus keyed by that same relative path and
    the rest hand back paths, so the two shapes are levelled here rather than in
    the caller, where levelling them would mean naming which walk is which.
    """
    found = globals()[name](root)
    if isinstance(found, dict):
        return set(found)
    return {str(path.relative_to(root)) for path in found}


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


class TestTheSourceWalkSeesOnlyThisProject:
    """Every rule in this file walks one of the source lists, so their reach is a rule too.

    Written after `.uv-cache/` cost two red pipelines against a green local suite. Every
    guard here reports a module by path, so a walk that reaches vendored code reports
    somebody else's module for breaking a rule it has never heard of, and it does so only
    in the environment where that directory exists.
    """

    def test_no_module_outside_this_project_is_walked(self) -> None:
        # The failure this reproduces: `pydantic/networks.py` and
        # `cyclonedx/model/contact.py` were reported for reading a member's address.
        outside = [
            str(path.relative_to(BACKEND))
            for path in _python_sources() + _test_sources() + _every_python_file()
            if path.suffix == ".py"
            and any(
                part.startswith(".") or part in {"__pycache__", "node_modules"}
                for part in path.relative_to(BACKEND).parts
            )
        ]
        assert not outside, f"the walk reached code this project did not write: {outside}"

    def test_the_walk_still_finds_this_project(self) -> None:
        # The other half. An exclusion that matched everything would satisfy the test
        # above and silently retire every rule in this file, which is the failure mode
        # a vacuity check exists for.
        found = {path.name for path in _python_sources()}
        assert "shelf.py" in found
        assert "models.py" in found
        assert len(found) > 30, f"only {len(found)} modules walked"

    def test_a_tool_directory_is_excluded_by_shape_and_not_by_name(self, tmp_path: Path) -> None:
        # The regression that matters: a cache nobody has seen yet is still excluded.
        # A name per tool passes this only for the tools somebody thought of.
        assert _is_vendored(BACKEND / ".some-tool-nobody-has-written-yet" / "mod.py")
        assert _is_vendored(BACKEND / "__pycache__" / "mod.py")
        assert not _is_vendored(BACKEND / "shelf.py")
        assert not _is_vendored(BACKEND / "routers" / "loans.py")

    def test_the_rule_holds_from_a_different_root(self) -> None:
        """`root` is what lets the census reuse this instead of restating it.

        The census walks from the repository, so it sees `backend/.uv-cache/...`
        with the dotted part one level deeper than this file's own walk does.
        Passing the wrong root is not a silent miss, it raises `ValueError`, so
        the failure of a future caller is loud rather than vacuous.
        """
        repo = BACKEND.parent

        assert _is_vendored(BACKEND / ".uv-cache" / "pygments" / "lexers.py", repo)
        assert not _is_vendored(BACKEND / "shelf.py", repo)
        assert not _is_vendored(repo / "frontend" / "src" / "main.tsx", repo)
        with pytest.raises(ValueError):
            _is_vendored(repo / "frontend" / "src" / "main.tsx")

    @pytest.mark.parametrize("kind", sorted(VENDORED_KINDS))
    def test_every_walk_refuses_a_vendored_path_of_this_kind(
        self, kind: str, tmp_path: Path
    ) -> None:
        """Each kind against every walk, rather than each walk against its own kind.

        The defect this is for was four walks passing four tests: three test
        modules each carried a copy of this corpus and each named the vendored
        directories it had heard of, so every one of them was green on the tree
        its author ran it against. The kinds are the rows and the walks are the
        columns, and a walk that refuses `.venv` and reads `.uv-cache` is a
        cell rather than a file nobody thought to open.

        **Against a tree this builds, not against this checkout.** The
        directories in question are absent from a developer's `backend/` and
        present in the pipeline's, so an assertion over the real tree is vacuous
        in the place it is usually run.
        """
        root = tmp_path / "tests" / "backend"
        _a_backend_with_vendored_code_in_it(root, VENDORED_KINDS[kind])
        walks, _ = _walk_names()
        assert len(walks) >= 5, f"the walks went missing from this file: {walks}"

        # Stated as "anything that is not one of ours", so a walk reaching a
        # second file in that directory, or a directory above it, is reported
        # too. Matching the planted names would only ever find what was planted.
        read = sorted(
            f"{name} read {relative}"
            for name in walks
            for relative in _reached(name, root)
            if relative not in FIRST_PARTY
        )
        assert not read, f"{kind} was walked: {read}"

    def test_the_walks_still_reach_this_project_with_that_planted_around_them(
        self, tmp_path: Path
    ) -> None:
        """The other half, without which refusing everything scores five of five.

        Per group rather than in total: the walks divide a backend into the
        modules, the tests and the migrations, and a total is satisfied by a
        walk that lost one of them.

        **The whole table at once**, so a walk added to this file has to be
        given a row here. Named one at a time, the new walk would be driven by
        the refusal above and by nothing that notices it answering with nothing.
        """
        # **Under a directory called `tests`**, which is what says the two names
        # are matched relative to the root. Asked of the whole path, the filter
        # matches this ancestor and `_python_sources` returns nothing at all.
        root = tmp_path / "tests" / "backend"
        for vendored in VENDORED_KINDS.values():
            _a_backend_with_vendored_code_in_it(root, vendored)
        walks, _ = _walk_names()

        assert walks == set(WHAT_EACH_WALK_REACHES), (
            "a walk was added or renamed and nothing here says what it is for: "
            f"{sorted(walks ^ set(WHAT_EACH_WALK_REACHES))}"
        )
        assert {name: _reached(name, root) for name in walks} == WHAT_EACH_WALK_REACHES

    def test_no_other_test_module_defines_one_of_these_walks(self) -> None:
        """The next copy of this walk is what the diagonal cannot be run against.

        Three test modules each defined their own `_source_modules`, and each
        spelled the exclusion as a list of directory names holding `.venv` and
        not the cache the pipeline creates. They import this one now, and this
        is what says they still do: the names are read off the functions here
        that reach `_is_vendored`, so one added later is covered with no edit.

        **It matches by name, and what that leaves out is covered by the rule
        below rather than by the tracker.** Other test modules walked
        `backend/` for `*.py` under names of their own and filtered with a
        directory list of their own, none of which held the cache the pipeline
        creates; this reaches none of them, because it was written for the shape
        that produced the defect, where the offending function in all three
        cases carried the name it was copied from. It makes that paste expensive
        rather than free, and
        `test_no_other_test_module_walks_the_backend_without_the_shared_rule`
        catches the class it cannot see.
        """
        _, names = _walk_names()
        assert len(names) >= 6, f"the walks went missing from this file: {names}"
        mine = Path(__file__).resolve()

        copies = sorted(
            f"{path.relative_to(BACKEND)}::{node.name}"
            for path in _test_sources()
            if path.resolve() != mine
            for node in ast.parse(path.read_text()).body
            if isinstance(node, _A_FUNCTION) and node.name in names
        )
        assert not copies, (
            "these keep their own copy of a walk this file owns, so what counts "
            f"as vendored is decided twice: {copies}"
        )

    def test_no_other_test_module_walks_the_backend_without_the_shared_rule(
        self,
    ) -> None:
        """The rule the test above cannot state, which is about the shape rather
        than the name.

        Nine test modules recursed `backend/` for `*.py` under names of their
        own, each excluding a list of directory names it had heard of and **none
        of them naming the cache the pipeline creates**. Two are security guards:
        the rule that no module reads a catalogue's address off the roster table,
        and the rule that keeps the password reset off HTTP. So a dependency
        unpacked under `backend/` in the pipeline and nowhere else decided
        whether either fired, which is green where it is written and red where it
        is trusted.

        **Recursion is read off the pattern, never off the method name**, and
        that distinction is the whole rule. A first version matched `rglob` and
        `os.walk` by name and said `glob` was safe because "a non recursive glob
        reads one directory": `glob("**/*.py")` recurses and was passed unseen,
        and so were `Path.walk()`, which 3.14 has, and a `walk` imported bare
        from `os`. Measured on four planted modules, one control reported and
        three evasions clean. So a call is a walk when its pattern carries `**`,
        or when it is `rglob`, or when anything at all is called `walk`. What is
        genuinely out is a `glob` whose pattern has no `**`, which reads one
        directory and cannot enter a vendored tree at all; five sites here are
        that shape.

        **Asked of the module rather than of the function**, and the cost is
        stated rather than discovered: a module that walks in one place and asks
        the predicate in an unrelated one passes. The tighter rule reports three
        modules that are correct, `test_classifications.py` among them, where the
        walk calls a helper that calls the predicate. Reporting a module for a
        split it was right to make is worse than the residue, and the diagonal
        above is what covers the predicate itself.
        """
        mine = Path(__file__).resolve()
        offenders: list[str] = []
        checked: set[str] = set()

        for path in _test_sources():
            if path.resolve() == mine:
                continue
            tree = ast.parse(path.read_text())
            defines_walk = any(
                isinstance(node, _A_FUNCTION) and node.name == "walk"
                for node in ast.walk(tree)
            )
            walks = [
                node.lineno
                for node in ast.walk(tree)
                if isinstance(node, ast.Call) and _is_a_walk(node, defines_walk)
            ]
            if not walks:
                continue
            checked.add(str(path.relative_to(BACKEND)))
            # **Any of the shared walks, not the predicate by name.** A module
            # that imports `_source_modules` or `_markdown_sources` has asked the
            # shared rule as surely as one that calls `_is_vendored`, and asking
            # for the one spelling reported three modules that were already
            # right. The set is read off this file rather than listed, so a walk
            # added here is accepted with no edit.
            _, shared = _walk_names()
            if any(
                isinstance(node, ast.Name) and node.id in shared
                for node in ast.walk(tree)
            ):
                continue
            offenders += [f"{path.relative_to(BACKEND)}:{line}" for line in walks]

        # A floor, because a matcher that stopped matching would report no
        # offender and no walk. It counts the modules this examined, which is
        # the population rather than the verdict.
        assert len(checked) >= 8, f"the walks went missing from the tests: {checked}"
        assert not offenders, (
            "these recurse `backend/` and decide what vendored means for "
            f"themselves, so the pipeline's cache is read as ours: {offenders}"
        )

    @pytest.mark.parametrize(
        ("call", "defines_walk", "recurses"),
        [
            ('BACKEND.rglob("*.py")', False, True),
            ('BACKEND.glob("**/*.py")', False, True),
            ("BACKEND.walk()", False, True),
            ("walk(BACKEND)", False, True),
            ("os.walk(BACKEND)", False, True),
            ('BACKEND.glob("*.py")', False, False),
            ("ast.walk(tree)", False, False),
            ("walk(node)", True, False),
            ("BACKEND.rglob(pattern)", False, True),
            # Recursion with the file kind decided in Python afterwards, and the
            # pattern handed over by keyword. These three are why this predicate
            # asks `fnmatch` rather than reading the pattern's tail, and every
            # one of them passed the version that read the tail.
            ('BACKEND.rglob("*")', False, True),
            ('BACKEND.glob("**/*")', False, True),
            ('BACKEND.rglob(pattern="*.py")', False, True),
            # **The row that actually drives the keyword arm.** The one above
            # does not: with the arm removed the pattern is unreadable, and an
            # unreadable pattern counts as a walk too, so both answers are
            # `True` and deleting the arm stays green. Measured. Here the two
            # answers differ, because a pattern that is read is judged.
            ('DOCS.rglob(pattern="*.md")', False, False),
            # Out of this rule's subject rather than evading it: no Python file
            # can match either, so neither can reach vendored source.
            ('FRONTEND.rglob("*.ts*")', False, False),
            ('DOCS.rglob("*.md")', False, False),
        ],
    )
    def test_what_counts_as_recursing_the_tree(
        self, call: str, defines_walk: bool, recurses: bool
    ) -> None:
        """The predicate above, one spelling per row.

        **Every row but the first is a spelling the tree does not hold**, which
        is why this is here: the rule above is driven by ten real modules and
        every one of them uses the first, so a matcher that had stopped reading
        any of the rest would still pass it. Rows two, three and four are the
        three evasions a critic measured against the version that matched
        `rglob` and an attribute of `os` by name, and the three after the
        unreadable pattern are the three it measured against the version that
        asked whether the pattern ended in `.py`.

        **Both sets came from the critic rather than from me**, and that is the
        arrangement rather than an accident: the first draft of this table held
        only the cases the rewrite had been designed against, so it scored clean
        while `rglob("*")` sat outside it. A guard's author is the worst person
        to choose its evasion.

        **And for one round this docstring described five rows the table did not
        have**, because the edit adding them died on a later assertion and wrote
        nothing, and only the failing half was re-applied. Both halves of the fix
        those rows exist for could then be reverted for `22 passed`. A comment
        claiming a case is not the case: count the rows.

        An unreadable pattern counts as a walk: a rule that assumed otherwise
        would be evaded by naming the pattern. The last two rows are the other
        side, and they are refusals of scope rather than misses: this rule is
        about reaching vendored **Python**, and no Python file matches either.
        """
        statement = ast.parse(call).body[0]
        assert isinstance(statement, ast.Expr)

        assert _is_a_walk(statement.value, defines_walk) is recurses


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

    Measured on the tree as it stands: **117** models under `schemas/`, **43** of
    them reachable from a request.

    **What those two numbers count, because a bare number is what rots.** The
    first is `_schema_models`: every class under `schemas/` that reaches
    `BaseModel` through any chain of bases, resolved to a fixed point, so a
    subclass of a model counts and a plain helper class does not. The second is
    `_body_models`: those of the first that a route handler annotates a
    parameter with, plus every model reachable from an in-scope model's own
    field annotations. Neither counts a response model that no handler accepts.

    **To recount them**, change nothing and run
    `test_the_stated_model_counts_are_the_measured_ones`: it recomputes both and
    the failure message prints the measured pair. Adding a request body model
    moves both numbers; adding a response only model moves the first.

    They are read back out of this paragraph by that test, because the previous
    pair (54 and 22) was stale by the time anybody noticed: it had drifted
    silently through at least two features before a reviewer recomputed it. It
    then drifted again during the author authority feature, three times: 69 and
    28 to 73 and 29 when four models arrived, to 74 when a fifth did, and to 75
    on 2026-08-28 when `ConfirmedIdentifierOut` did. It drifted a fourth time on the
    same day, to **77**, when the overdue reminder work added `SenderHealth` and
    `MyOverdueOut`. It drifted a fifth time, to **81** and **30**, when
    `users.email` added `MemberEmailOut` and `EmailUpdate` and the public
    catalogue added two more, and twice more inside the same evening as two
    other seats landed a model each: to 82, then to **83**. **Three trios in
    one wave is the condition this paragraph cannot survive on its own**, so
    the last word before a commit belongs to the command below rather than to
    this history. It drifted an eighth time on 2026-08-30, to **86**, when the
    classification facets added `HeadingFacetOut`, `DivisionFacetOut` and
    `ClassificationFacets`. **The second number has now
    stood still through six of those eight**, because every model that
    did not move it is served on a response and accepted by no handler, which
    is exactly the distinction the two counts exist to keep visible. Every drift
    was caught by this test rather than by a reader, and a history that stops one
    drift short is the defect this paragraph exists to prevent. A number in prose that
    nothing checks is a number that is eventually wrong, and this file exists
    precisely to stop a defect being found a third time by a person.

    It drifted a ninth time on 2026-08-30, to **90**, when MARC import added
    `MarcPreviewOut` and `MarcPreviewRow`. **The second number stood still for
    the seventh of the nine**: both are served on the preview response and no
    handler accepts either as a body, so neither can carry a row id in from
    outside. That is the distinction the two counts exist to keep visible, said
    once more because it is the reason a drift in the first number is not
    automatically a hole in the rule.

    **And the history stopped one drift short anyway, which is the thing it
    warns about happening to itself.** The eighth entry above ends at 86 with
    the three classification facet models; the tree measured **88** at
    `2c00658`, before this trio wrote a line. Two models landed without an
    entry. That is not reconstructed here, because guessing which ones would put
    a made up fact in a paragraph whose whole purpose is that its facts are
    recomputed: what the entry above should have said is whatever the command
    below reported at the time. **The last word before a commit belongs to that
    command**, and this is the second wave in which the prose lost to it.

    Both numbers moved together when `BookIdentifierIn` and `BookIdentifierOut`
    arrived, which is the case the pair exists to make visible: one of the two
    is accepted on `POST /api/books` and the other is served, so a drift of one
    and not the other would have been the tell that something was misclassified.
    The figures above are whatever the command below reports; this entry names
    the models and deliberately not a count.
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
    `test_shelf.py::_entity_aliases` resolves a guarded model, which is the
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


#: Enum columns deliberately without a `CheckConstraint`, and why.
#:
#: SQLite cannot ALTER a CHECK, so a constraint costs a batch table rebuild in a
#: migration every time the enum grows. That is a fair price for an enum that is
#: closed and a recurring tax on one that is not.
#:
#: **Each of these is meant to degrade at the read end instead**, in the shape
#: `custom_fields._kind_of` uses: an unrecognised value becomes a safe default
#: and is logged. That is quieter than a 500 on every read of the row, and it is
#: still data loss nobody can see, which is why the degrade logs rather than
#: passing silently.
#:
#: **Meant to, and three of these six do not**, which is stated here rather than
#: left as a promise the list makes and the code does not keep. Measured
#: 2026-09-06: a restored `classifications.scheme` of `udc`, which
#: `test_backup.py` restores and asserts a 200 on, makes `PublicBookOut` raise,
#: so it 500s the unauthenticated public catalogue. Nothing here degrades that.
GROWING_ENUM_COLUMNS: dict[str, str] = {
    "user_books.status": (
        "ReadStatus has already grown once: WANT_TO_READ was added later and "
        "kept distinct from UNREAD because a Goodreads export carries the "
        "distinction."
    ),
    "classifications.scheme": (
        "ClassificationScheme grows whenever a catalogue source is added, which "
        "is an open issue rather than a hypothetical."
    ),
    "tags.category": (
        "TagCategory is the seeded vocabulary's shape, and the bilingual tag "
        "work touches it."
    ),
}

#: Enum columns nobody has decided about, as opposed to the ones above.
#:
#: **A separate constant because it holds a different thing.** An entry above is
#: a decision with a reason: this enum grows, so it pays at the read end
#: instead. An entry here is the absence of one. Both keep the rule green, and
#: merging them would let the second be mistaken for the first, which is exactly
#: what a list named "with a reason" invites.
#:
#: These three became visible on 2026-09-06, when the walk above was fixed to
#: descend into `Mapped[Enum | None]` and went from seeing 7 enum columns to
#: seeing 11. Neither half of the bargain above holds for any of them: none
#: carries a CHECK, and none degrades at the read end, so a restored value
#: outside the enum raises inside `BookOut` and 500s the listing. The same is
#: true of `classifications.scheme` above, where it is measured: a restored
#: `udc`, which `test_backup.py` restores and asserts a 200 on, makes
#: `PublicBookOut` raise.
#:
#: **Membership is pinned below**, so a fourth column cannot be parked here by a
#: later wave without editing a test and saying why.
#:
#: **Names only, where `GROWING_ENUM_COLUMNS` above maps to reasons.** The first
#: version mapped each to its enum's name, which `_enum_columns` already
#: derives, and that redundancy made the pin untestable: a mutation replacing
#: the walk's answer with this constant's own values could not be caught,
#: because the two agree on any tree where the constant is right. A pin holding
#: no derived data has nothing to quote itself from.
UNDECIDED_ENUM_COLUMNS: frozenset[str] = frozenset(
    {"books.format", "books.condition", "books.lending"}
)


def _enum_types(annotation: object) -> list[type[StrEnum]]:
    """Every `StrEnum` anywhere inside an annotation, at any depth.

    Recursive rather than one level, so `Mapped[X]`, `Mapped[X | None]` and
    anything a later column is written as are all one rule. Reading at a fixed
    depth is what let every nullable column through.
    """
    if isinstance(annotation, type) and issubclass(annotation, StrEnum):
        return [annotation]
    return [
        found for arg in get_args(annotation) for found in _enum_types(arg)
    ]


def _enum_columns() -> dict[str, str]:
    """Every mapped column whose Python type is a `StrEnum`, as `table.column`.

    Read off the mapper rather than the source text, because an annotation can
    be written several ways and a rule that reads one spelling of it enforces
    nothing. That is the defect this repository has found in a guard eleven
    times.
    """
    from sqlalchemy import Table

    from database import Base

    found: dict[str, str] = {}
    for mapper in Base.registry.mappers:
        table = mapper.local_table
        if not isinstance(table, Table):
            continue
        for name, attr in mapper.column_attrs.items():
            annotation = mapper.class_.__annotations__.get(name)
            if annotation is None:
                continue
            # `get_args`, not a substring of `str(annotation)`. The annotation
            # renders as `Mapped[enums.OwnershipStatus]`, so matching
            # `[OwnershipStatus]` finds nothing while looking correct. This rule
            # was written that way first, and the tripwire below is what caught
            # it, which is the rule's own warning applied to itself.
            #
            # **Descended rather than read at one depth, and that is the same
            # defect a second time.** A nullable column is
            # `Mapped[HeadingKind | None]`, whose single argument is the union,
            # so `isinstance(arg, type)` was False and the walk saw **none** of
            # them: measured 2026-09-06, 7 columns found against 11 that exist,
            # and the 4 it missed were every nullable one. The tripwire below
            # did not catch it because all three columns it names are
            # non-nullable, which is a fixture agreeing with the case it covers.
            for arg in _enum_types(annotation):
                found[f"{table.name}.{attr.columns[0].name}"] = arg.__name__
    return found


def _bounds_column(sqltext: str, column_name: str) -> bool:
    """Whether a CHECK's text restricts this column to a list of values.

    **Bounds it, rather than mentions it, and the difference is live in this
    tree.** `author_identifiers.provenance` appears in two constraints:
    `ck_author_identifiers_provenance`, which is `provenance IN (...)`, and
    `ck_author_identifiers_asserter`, which is
    `provenance <> 'catalogue' OR created_by_user_id IS NULL` and restricts the
    column to nothing at all. A rule asking only whether some CHECK names the
    column reports it constrained on the strength of the second, so deleting the
    first leaves this green. Measured 2026-09-06: 5 enum columns are mentioned
    by a CHECK, 5 are bounded by one, and `provenance` is the column where those
    two sets are reached by different constraints.

    **At a word boundary**, because a bare `in` test reports a column
    constrained off another column whose name contains it: over all 143 mapped
    columns, `loans.id` reads as constrained off `loaned_to_user_id` and
    `author_identifiers.id` off three constraints naming `identifier` and
    `created_by_user_id`. No enum column collides today, which is what made it
    safe to be wrong.

    Still a text match on SQL rather than a parse, so it has a known blind spot
    with no live instance: a column name inside a quoted literal in a CHECK on
    the same table. Parsing SQL to close that is not a cheap fix and is recorded
    rather than done.
    """
    return bool(
        re.search(
            rf"(?<![A-Za-z0-9_]){re.escape(column_name)}\s+IN\s*\(",
            sqltext,
            re.IGNORECASE,
        )
    )


def _has_check(qualified: str) -> bool:
    """Whether a CHECK on this column's table bounds this column's values."""
    from sqlalchemy import Table

    from database import Base

    table_name, column_name = qualified.split(".")
    for mapper in Base.registry.mappers:
        table = mapper.local_table
        if not isinstance(table, Table) or table.name != table_name:
            continue
        for constraint in table.constraints:
            if isinstance(constraint, CheckConstraint) and _bounds_column(
                str(constraint.sqltext), column_name
            ):
                return True
    return False


class TestEveryEnumColumnIsConstrainedOrExemptWithAReason:
    """A value outside the enum 500s every read of the row that holds it.

    `backup.restore` inserts through Core, where neither a Pydantic model nor a
    `@validates` hook fires, so an archive decides the value. `custom_fields.kind`
    shipped with its constraint **in the migration only**, so `create_all` built
    the table without it and `--autogenerate` would have proposed dropping it.
    Four migrations would have fixed that day and prevented nothing; this is what
    prevents the next one.
    """

    def test_every_enum_column_is_constrained_or_named(self):
        unaccounted = {
            column: enum
            for column, enum in _enum_columns().items()
            if not _has_check(column)
            and column not in GROWING_ENUM_COLUMNS
            and column not in UNDECIDED_ENUM_COLUMNS
        }
        assert not unaccounted, (
            "These map a StrEnum and carry no CheckConstraint, so a restored row "
            "outside the enum raises at read time. Add the constraint, or add the "
            "column to GROWING_ENUM_COLUMNS with the reason it cannot have one: "
            f"{sorted(unaccounted)}"
        )

    def test_the_exemption_list_names_only_real_columns(self):
        """An exemption for a column that no longer exists is an exemption
        nobody notices is doing nothing."""
        exempted = set(GROWING_ENUM_COLUMNS) | set(UNDECIDED_ENUM_COLUMNS)
        stale = exempted - set(_enum_columns())
        assert not stale, f"exempted columns that do not exist: {sorted(stale)}"

    def test_a_column_is_not_bounded_by_another_columns_name(self):
        """`id` is not constrained by a clause about `loaned_to_user_id`.

        A substring match reports it constrained because the longer name
        contains it, which would exempt a future enum column from the rule above
        with nothing going red. Measured over all 143 mapped columns on
        2026-09-06: two answer differently under the two spellings, `loans.id`
        and `author_identifiers.id`, and no enum column does, which is why the
        rule above was right today and was not safe.

        Both halves, so the boundary cannot be satisfied by refusing
        everything.
        """
        assert not _bounds_column("loaned_to_user_id IN ('a', 'b')", "id")
        assert _bounds_column("id IN ('a', 'b')", "id")
        assert not _has_check("loans.id")

    def test_a_check_that_only_mentions_a_column_does_not_count(self):
        """The two live constraints on `author_identifiers.provenance`.

        One restricts the column and the other merely names it. A rule that
        accepted the second would let the first be deleted with nothing red,
        which is the evasion this pair pins rather than describes.
        """
        assert _bounds_column("provenance IN ('catalogue', 'member')", "provenance")
        assert not _bounds_column(
            "provenance <> 'catalogue' OR created_by_user_id IS NULL", "provenance"
        )
        assert _has_check("author_identifiers.provenance")

    def test_the_growing_list_does_not_grow_without_somebody_saying_so(self):
        """The other half of the exemption, pinned the same way.

        **Splitting the list moved the escape hatch rather than closing it.**
        Pinning only the undecided half left this one open, and nothing tests
        that a reason string is true: measured 2026-09-06, moving `books.format`
        here with the invented reason "looks like it grows to me" leaves the
        whole suite green. A future wave wanting green reaches for the list with
        no pin, so both lists have one and every exemption is a two place edit.
        """
        assert set(GROWING_ENUM_COLUMNS) == {
            "user_books.status",
            "classifications.scheme",
            "tags.category",
        }

    def test_the_undecided_list_does_not_grow_without_somebody_saying_so(self):
        """The exemption above catches a stale entry and never a new one.

        Without this, a later wave adds a fourth column with no reason and the
        rule stays green for good, which is how a list of three exceptions
        becomes the rule. Pinned to the exact set, so growing it is a test edit
        with a name on it. Shrinking it is the same edit, and that is the
        direction somebody should want.

        **A set of names and nothing derived**, which is what makes this
        testable. Two earlier versions carried each column's enum name beside
        it, once behind a helper that read it back through `_enum_columns` so
        the pin could not quote itself. Both were mutated to quote the constant
        instead, and **neither mutation was caught**, because a duplicated fact
        and the thing it duplicates agree on every tree where the duplicate is
        correct. The redundancy was the defect; the indirection only hid it.

        That the three columns still exist is `test_the_exemption_list_names_
        only_real_columns` above, which walks the same union.
        """
        assert set(UNDECIDED_ENUM_COLUMNS) == {
            "books.format",
            "books.condition",
            "books.lending",
        }

    def test_the_reader_finds_the_columns_it_is_meant_to(self):
        """A tripwire. An empty or half built mapping makes both tests above
        pass while enforcing nothing, which is the shape of every guard defect
        found in this repository.

        **Every name here is nullable or not on purpose.** The three this
        started with were all `Mapped[Enum]`, so the walk could miss every
        `Mapped[Enum | None]` column in the tree and still pass: it did, for
        four of them. A tripwire whose fixtures all sit on one side of a
        distinction cannot see that side being dropped.
        """
        # No `len(found) >= 5` here, and its absence is the point: 11 enum
        # columns existed when this was written on 2026-09-06 and the walk this
        # tripwire was extended for found 7, so the inequality passed through the
        # exact regression it read as bounding. The named columns below are the
        # bound, and unlike a count they do not go stale on the twelfth column.
        found = _enum_columns()
        assert found.get("custom_fields.kind") == "CustomFieldKind"
        assert found.get("books.ownership") == "OwnershipStatus"
        assert found.get("user_books.status") == "ReadStatus"
        # Nullable, which is the half the walk used to drop entirely.
        assert found.get("classifications.kind") == "HeadingKind"
        assert found.get("books.format") == "BookFormat"


#: The one bot id a fixture may use. Real Telegram bot ids are eight to ten
#: digits, so this satisfies `notifications._TELEGRAM_TOKEN` while being
#: unmistakable to a reader and to a scanner.
FAKE_BOT_ID = "0:"


class TestNoFixtureLooksLikeACredential:
    """A value that only **looks** like a secret costs the same to triage as one
    that is, and on the public mirror somebody else does that triage.

    GitHub's secret scanner flagged `test_notifications.py` for a Telegram bot
    token: realistic bot id, realistic secret half, and shaped that way on
    purpose because `_TELEGRAM_TOKEN` insists on the shape before the value goes
    into a URL path. The fixture was never a live credential and that did not
    matter, because nobody triaging an alert can tell from the outside.

    Everything published is published, so this is a rule about what ships rather
    than about what is true.

    **These arms walk every Python file under `backend/`.** They walked
    `backend/tests/` alone until 2026-09-02, and the sentence here justified that
    by saying `_test_sources()` was what they had. `_every_python_file()` landed
    with the compile rule at the foot of this file and made that false, so the
    scope moved rather than the excuse: the application modules and the
    migrations ship to the mirror exactly as the fixtures do, and `models.py` is
    as public as a fixture is. The widening was free, **99 further files and 0
    offenders on both arms, measured 2026-09-02** with a planted token and a
    planted address confirming the scan still sees one. That is the guard's own
    argument three paragraphs down, applied to itself.

    The class is still named for the shape it forbids rather than the tree it
    walks, which is why the name did not move with the scope. The frontend half
    is
    `frontend/tests/houseRules.test.ts`, "no fixture or string carries an
    address outside reserved space", and it walks `src/` as well as `tests/`
    because `src/i18n/en.ts` ships a placeholder address in published source. A
    docstring here claimed both trees for one round while checking one, which is
    the reason that sentence is now this specific.

    **The second arm is an address, and it is here because `users.email` is the
    first column in this schema holding somebody's personal data.** A fixture
    address is not a credential, but it ships to the same public mirror and
    reads to a stranger as a real person's mailbox. The reserved domains exist
    for exactly this: RFC 2606 sets aside `example.com`, `example.net`,
    `example.org` and the `.test`, `.example`, `.invalid` and `.localhost` TLDs,
    and nothing outside them can be told apart from somebody's actual address.

    It was added while the diff that introduced the column was **already
    green**: 25 distinct addresses across both trees and every one already
    inside reserved space. That is the moment a guard costs nothing, and the
    moment after it is the one where somebody has to go and change fixtures.
    """

    #: Files allowed to contain the patterns, with the reason.
    #:
    #: Only this file, which has to write them down in order to forbid them.
    ALLOWED = {"tests/test_house_rules.py"}

    #: The reserved names a fixture address may sit under. RFC 2606 and RFC 6761.
    #:
    #: **Written without leading dots and compared by `_is_reserved`, not by
    #: `str.endswith` against this tuple.** It held both spellings, `.example.com`
    #: and `example.com`, so that a bare `example.com` would match; the
    #: undotted entries then made `endswith` accept **`notexample.com`**,
    #: **`myexample.org`** and **`fakeexample.net`**, all three registrable and
    #: all three measured. That is `grep -F ci` matching "de**ci**sion", which
    #: this file has now made in three different guards, so the comparison is a
    #: named method with its own fixtures rather than a call site anybody can
    #: get subtly right.
    RESERVED = (
        "example.com",
        "example.net",
        "example.org",
        "test",
        "example",
        "invalid",
        "localhost",
    )

    def _is_reserved(self, domain: str) -> bool:
        """Is this domain the reserved name itself, or a label under it?

        A boundary comparison, so `mail.example.org` passes and
        `notexample.com` does not. The dot is what makes it a label boundary,
        and the equality is what still admits the bare name.
        """
        return any(
            domain == base or domain.endswith("." + base) for base in self.RESERVED
        )

    def test_no_published_file_contains_a_realistic_bot_token(self):
        pattern = re.compile(r"[0-9]{6,}:[A-Za-z0-9_-]{25,}")
        offenders: list[str] = []
        paths = _every_python_file()
        # **The scope is asserted on the list this loop iterates**, not on a
        # fresh call, which would pin the helper's reach rather than this arm's
        # use of it. Both walks report zero today, so reverting this line to
        # `_test_sources()` changes no verdict and silently drops the
        # application modules and the migrations. That is the same guard, and
        # the same reasoning, as `test_every_python_file_under_backend_compiles_clean`.
        assert any("migrations" in path.parts for path in paths)
        assert any(path.name == "models.py" for path in paths)
        for path in paths:
            relative = str(path.relative_to(BACKEND))
            if relative in self.ALLOWED:
                continue
            # **Decoded explicitly, not through the locale.** `_offences` reads
            # bytes for this reason and this arm walks the same corpus:
            # `read_text()` uses `locale.getencoding()` and raises
            # `UnicodeDecodeError` on a latin-1 cookied file that compiles
            # perfectly well, which is the scan failing rather than the file.
            # `errors="replace"` because this is looking for a shape, so a
            # replacement character in an undecodable byte costs nothing and a
            # traceback costs the whole run.
            text = path.read_text(encoding="utf-8", errors="replace")
            for number, line in enumerate(text.splitlines(), 1):
                if pattern.search(line):
                    offenders.append(f"{relative}:{number}")

        assert not offenders, (
            "These carry a string shaped like a live Telegram bot token, and this "
            f"tree is published. Use {FAKE_BOT_ID!r} as the bot id: it "
            "satisfies the validator and cannot be mistaken for a credential. "
            f"{sorted(offenders)}"
        )

    def _addresses(self, text: str) -> list[str]:
        """Every address-shaped string in a file.

        Deliberately looser than `mailer._ADDRESS`: this is looking for what a
        **reader** would take for an address, and a stranger triaging the public
        mirror does not run our validator over it first.
        """
        return re.findall(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}", text)

    def test_no_published_file_carries_an_address_outside_reserved_space(self):
        offenders: list[str] = []
        paths = _every_python_file()
        # Pinned the same way and for the same reason as the arm above.
        assert any("migrations" in path.parts for path in paths)
        assert any(path.name == "models.py" for path in paths)
        for path in paths:
            relative = str(path.relative_to(BACKEND))
            if relative in self.ALLOWED:
                continue
            # Decoded the same way and for the same reason as the arm above.
            text = path.read_text(encoding="utf-8", errors="replace")
            for number, line in enumerate(text.splitlines(), 1):
                for address in self._addresses(line):
                    domain = address.rsplit("@", 1)[1].lower()
                    if not self._is_reserved(domain):
                        offenders.append(f"{relative}:{number} ({address})")

        assert not offenders, (
            "These carry an address outside the domains reserved for documentation, "
            "and this tree is published, so a stranger cannot tell them from "
            "somebody's real mailbox. Use example.org, example.com, example.net or "
            f"a .test / .invalid name: {sorted(offenders)}"
        )

    def test_the_rules_report_the_shapes_they_exist_for(self):
        """A rule nothing can fail is a rule nobody notices deleting."""
        pattern = re.compile(r"[0-9]{6,}:[A-Za-z0-9_-]{25,}")
        assert pattern.search("123456789:AAHrealisticlookingsecrethalfhere")
        assert not pattern.search("0:TEST-TOKEN-NOT-A-REAL-CREDENTIAL")

        # The address arm, both ways. A reserved domain passes and a plausible
        # personal one does not, which is the only distinction it draws.
        found = self._addresses("write to kim.jones@gmail.com or sam@example.org")
        assert found == ["kim.jones@gmail.com", "sam@example.org"]
        assert not self._is_reserved(found[0].rsplit("@", 1)[1])
        assert self._is_reserved(found[1].rsplit("@", 1)[1])

    @pytest.mark.parametrize(
        ("domain", "reserved"),
        [
            ("example.org", True),
            ("example.com", True),
            ("example.net", True),
            # A label under a reserved name, which is what makes this a rule
            # rather than a list nobody can finish.
            ("mail.example.org", True),
            ("sub.deep.example.test", True),
            ("anything.invalid", True),
            ("localhost", True),
            ("test", True),
            # The three that `str.endswith` against a tuple of bare names
            # accepted. All registrable, all measured.
            ("notexample.com", False),
            ("myexample.org", False),
            ("fakeexample.net", False),
            # The same mistake one label along, and at the TLD.
            ("example.org.evil.test.co", False),
            ("faketest", False),
            ("notlocalhost", False),
            ("gmail.com", False),
        ],
    )
    def test_the_reserved_check_compares_at_a_label_boundary(self, domain, reserved):
        assert self._is_reserved(domain) is reserved


def _label(path: Path) -> str:
    """A path to report, whether or not it is inside the backend tree.

    The self-tests below hand these scanners a `tmp_path` file, and
    `relative_to` raises on one. Reported as a bare name there.
    """
    try:
        return str(path.relative_to(BACKEND))
    except ValueError:
        return path.name


def _dataclasses_modules(tree: ast.Module) -> set[str]:
    """Every name in this module that is the `dataclasses` module itself.

    `import dataclasses as dc` is not an evasion, it is an accident: a module
    that already aliases the import for its own reasons and then writes
    `dc.replace(record, headings=...)`.
    """
    found = {"dataclasses"}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found |= {
                alias.asname or alias.name
                for alias in node.names
                if alias.name == "dataclasses"
            }
    return found


def _replace_aliases(tree: ast.Module) -> set[str]:
    """Every bare name in this module that is `dataclasses.replace`."""
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module == "dataclasses":
            found |= {
                alias.asname or alias.name
                for alias in node.names
                if alias.name == "replace"
            }
    return found


def _holds_a_record(tree: ast.Module) -> bool:
    """Whether this module could have a `catalogue.Record` in hand.

    An approximation, and the one this rule is scoped by: a module that never
    names `catalogue` cannot construct a `Record`, so forbidding `replace`
    there would be a rule with a wider reach than its reason.
    """
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module == "catalogue":
            return True
        if isinstance(node, ast.Import) and any(
            alias.name == "catalogue" for alias in node.names
        ):
            return True
    return False


class TestOnlyTheCatalogueBuildsAnUnfoldedRecord:
    """`Record._folded` is a rule stated in a comment, and comments do not hold.

    `catalogue.py` says it outright: **a `replace` that changes `subjects` or
    `headings` passes `_folded=False`**, and `merged_with` is the only one that
    does. Break it from a distance and nothing raises. Pass `_folded=True` into
    a constructor and `__post_init__` returns before deduplicating anything, so
    the record keeps every repeat a catalogue sent: duplicate headings spend a
    Book's eight classification slots, and the fold nobody skipped now runs on
    every `replace` again, which is a 31 second event loop stall inside
    `async def search`. Measured, both directions, in `Record._folded`.

    Both critic seats arrived at this independently and neither found a live
    offender, which is the point: the tree conforms today, `with_cover()` exists
    **only** so that it can, and nothing was keeping it that way.

    **Two rules, because there are two ways in**, and one allowlist entry
    between them:

    1. Nothing outside `catalogue.py` names `_folded`, in either tree. Four node
       shapes, not one, and the list is the result of somebody attacking the
       first draft rather than of reasoning about it: the keyword
       (`Record(_folded=True)`), the attribute (`record._folded`), a **string
       constant in a call** (`object.__setattr__(record, "_folded", True)`) and
       a **dict key** (`Record(**{"_folded": True})`). The third is the one that
       matters most and the one the first draft missed: it is the only way to
       set the flag on a frozen instance, and it is verbatim the line
       `__post_init__` uses three times, so it is the line somebody copies.
    2. A module that could hold a `Record` does not call `dataclasses.replace`.
       `Record.with_cover()` is what such a caller reaches for instead, and
       adding a second method is cheaper than auditing a `replace` that looks
       fine.

    **Rule 1 is constrained to call arguments and dict keys rather than to every
    string constant**, which was tried first and is wrong: a bare `ast.Constant`
    test trips on this class's own message strings and on
    `tests/test_catalogue.py`, which names the field in order to exclude it from
    `_FILLED`.

    **Blind spots, listed rather than left to be found.** Rule 2 is scoped by
    whether a module imports `catalogue` at all, so a module handed a `Record`
    by a caller without importing it escapes: that is a real gap and it is the
    price of not forbidding `replace` on every unrelated frozen dataclass in the
    backend. A name bound indirectly (`fn = dataclasses.replace`) escapes both.
    Neither is the failure this exists for, which is somebody copying the
    `replace` already in `catalogue.py` to a new site.

    Both spellings of the alias **are** covered, and only because a seat tried
    them: `from dataclasses import replace as swap` by `_replace_aliases`, and
    `import dataclasses as dc` by `_dataclasses_modules`. The second was missing
    from the first draft and is not an evasion but an accident, which is the
    kind this rule is for.
    """

    #: Allowed to break both rules, because it owns them. A path rather than a
    #: basename, matching the sibling guard above: compared as `path.name`, any
    #: file called `catalogue.py` at any depth would have been exempt.
    ALLOWED = "catalogue.py"

    def _offenders_naming_the_flag(self, paths: list[Path]) -> list[str]:
        offenders: list[str] = []
        for path in paths:
            if _label(path) == self.ALLOWED:
                continue
            tree = ast.parse(path.read_text())
            for node in ast.walk(tree):
                # Two nodes rather than one test, because a `keyword` carries
                # `arg` and an `Attribute` carries `attr`, and mypy needs each
                # narrowed before it will believe in `lineno`.
                if isinstance(node, ast.keyword) and node.arg == "_folded":
                    offenders.append(f"{_label(path)}:{node.value.lineno}")
                elif isinstance(node, ast.Attribute) and node.attr == "_folded":
                    offenders.append(f"{_label(path)}:{node.lineno}")
                elif isinstance(node, ast.Call):
                    # `object.__setattr__(record, "_folded", True)` is the only
                    # way to set it on a frozen instance, and it is the line
                    # `__post_init__` uses three times, so it is the one most
                    # likely to be copied. It is a string, not a keyword.
                    offenders += [
                        f"{_label(path)}:{argument.lineno}"
                        for argument in node.args
                        if isinstance(argument, ast.Constant)
                        and argument.value == "_folded"
                    ]
                elif isinstance(node, ast.Dict):
                    # `Record(**{"_folded": True})` is a Dict key, not a keyword.
                    offenders += [
                        f"{_label(path)}:{key.lineno}"
                        for key in node.keys
                        if isinstance(key, ast.Constant) and key.value == "_folded"
                    ]
        return offenders

    def test_no_module_outside_the_catalogue_names_the_fold_flag(self) -> None:
        offenders = self._offenders_naming_the_flag(
            _python_sources() + _test_sources()
        )
        assert not offenders, (
            "`Record._folded` decides whether `__post_init__` deduplicates. "
            "Setting it from outside `catalogue.py` ships a record holding "
            "every repeat its catalogue sent, with no error anywhere. "
            f"{sorted(offenders)}"
        )

    def test_no_module_holding_a_record_replaces_a_field_on_one(self) -> None:
        offenders: list[str] = []
        for path in _python_sources():
            if _label(path) == self.ALLOWED:
                continue
            tree = ast.parse(path.read_text())
            if not _holds_a_record(tree):
                continue
            aliases = _replace_aliases(tree)
            modules = _dataclasses_modules(tree)
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call):
                    continue
                function = node.func
                hit = (
                    isinstance(function, ast.Attribute)
                    and function.attr == "replace"
                    and isinstance(function.value, ast.Name)
                    and function.value.id in modules
                ) or (isinstance(function, ast.Name) and function.id in aliases)
                if hit:
                    offenders.append(f"{_label(path)}:{node.lineno}")

        assert not offenders, (
            "A `replace` on a `Record` outside `catalogue.py` keeps `_folded` "
            "set, so a new `subjects` or `headings` tuple is never folded. Add "
            "a method on `Record` the way `with_cover()` was added. "
            f"{sorted(offenders)}"
        )

    def test_the_rules_report_the_shapes_they_exist_for(self, tmp_path) -> None:
        """A rule nothing can fail is a rule nobody notices deleting."""
        offending = tmp_path / "offender.py"
        offending.write_text(
            "import dataclasses\n"
            "from catalogue import Record\n"
            "def f(record: Record) -> Record:\n"
            "    return dataclasses.replace(record, subjects=())\n"
            "def g() -> Record:\n"
            "    return Record(_folded=True)\n"
            "def h(record: Record) -> None:\n"
            "    object.__setattr__(record, \"_folded\", True)\n"
            "def i() -> Record:\n"
            "    return Record(**{\"_folded\": True})\n"
            "def j(record: Record) -> bool:\n"
            "    return record._folded\n"
        )
        tree = ast.parse(offending.read_text())
        assert _holds_a_record(tree)
        # Four, one per node shape rule 1 covers: the keyword, the string in a
        # call, the dict key and the attribute read. A count, because "something
        # was caught" is what let the first draft pass while missing three of
        # them. The `dataclasses.replace` in the same file is rule 2's and is
        # deliberately not among them.
        assert len(self._offenders_naming_the_flag([offending])) == 4

        aliased = tmp_path / "aliased.py"
        aliased.write_text("from dataclasses import replace as swap\n")
        assert _replace_aliases(ast.parse(aliased.read_text())) == {"swap"}

        aliased_module = tmp_path / "aliased_module.py"
        aliased_module.write_text("import dataclasses as dc\n")
        assert _dataclasses_modules(ast.parse(aliased_module.read_text())) == {
            "dataclasses",
            "dc",
        }

        innocent = tmp_path / "innocent.py"
        innocent.write_text("import dataclasses\ndataclasses.replace(thing, a=1)\n")
        assert not _holds_a_record(ast.parse(innocent.read_text()))
        assert not self._offenders_naming_the_flag([innocent])

class TestAnAddressIsServedOnlyWhereItIsNamed:
    """A member's address reaches the three schemas that exist for it, and no other.

    The rule is issue #80's, settled by the owner: an admin may read and write
    any address, a member may read and write their own, and **it is used and
    shown nowhere else**. #103 added one moment to that and no new disclosure:
    an address may be **set** while an account is being created, by the person
    creating it. `UserCreate` is a request body, so it takes an address in and
    serves none back, and the route answers with `UserOut`, which this rule
    still keeps clear of one. The last one is load bearing, and an intention is not
    a mechanism: `UserOut` is served inside every book payload and by the member
    list, so one field added there discloses an address to every member who can
    see a book, with a 200 and nothing in any log. That is the shape the
    appearance columns were kept off `UserOut` to avoid, and it was kept off by
    a comment.

    Two passes, in the two places the field could arrive.

    **The schema pass asks pydantic what each model puts on the wire**, rather
    than reading Python field names, and it asks **once**. A model carries an
    address when the string `email` names a property anywhere in its JSON schema
    document, in either mode. Nothing else.

    **It took three versions to get to one mechanism, and the second is the
    instructive one.** The first tested `"email" in model_fields`, the Python
    name, and a reviewer walked past it twice in a sitting: with
    `mailbox: str = Field(serialization_alias="email")` on `UserOut`, which
    `from_attributes` fills from `User.email` and FastAPI serialises
    `by_alias=True`; and with `class Anything(BaseModel): member: MemberEmailOut`,
    which carries the whole address model and has no address field of its own.

    The second version fixed both, and fixed them with **two** mechanisms: the
    wire names from `model_json_schema`, plus a fixed point over Python
    annotations for the nesting. A reviewer then walked through the seam between
    them. A `@computed_field` returning `MemberEmailOut` is in the serialization
    schema and **absent from `model_fields`**, which was all the annotation walk
    read, so `model_dump()` returned `{'id': 0, 'person': {..., 'email': ...}}`
    while the guard saw a model whose only field was `id`.

    Two mechanisms meeting in the middle is where a hole lives. The third
    version deletes the second one: `model_json_schema` already inlines every
    referenced model into one flattened top level `$defs`, measured to reach a
    model nested two deep, so walking the document covers naming, every alias
    spelling, an `alias_generator`, nesting at any depth, list and dict
    positions, and computed fields with no arm for any of them. It is a net
    deletion, which is what the fix to an enumerating guard looks like when it
    is the right one.

    Models are reached through `BaseModel.__subclasses__()` after `main` has
    imported every router, rather than by listing modules: a hard coded module
    list is the guard defect this file has already made once. A model is this
    app's if its own source file is under `backend/` and outside `.venv`, which
    keeps `fastapi.openapi.models.Contact` (which has an `email`) out of the
    answer. A model whose schema cannot be built is **reported**, not skipped:
    a skipped model is a hole.

    **The reader pass** is the `TestProvenanceColumnsAreNeverRead` shape: no
    module outside the two named may read `.email` off anything. That is what
    catches an address put into a plain `dict` a route returns, which no schema
    pass can see. `getattr(x, "email")` is the other spelling of an attribute
    read and is matched too; `getattr(row, column.name)` is not, which is
    exactly the generic door `backup.py` reads every column through and the
    reason a restore keeps carrying this one.

    **Blind spots, stated rather than discovered**, and this list has itself
    been wrong once: it claimed the pass covered everything except an address
    under a different name, which did not describe the computed field above at
    all. That one served the address **under the name `email`**, inside a nested
    object. So what follows is what the mechanism cannot see rather than a
    restatement of what it does.

      * An address served under a different property name (`contact`, `mailbox`
        with no alias). This pins the name the app uses, in the place a caller
        sees it, and a rule that guessed at synonyms would be an enumeration.
      * A route with `response_model=None` returning a hand built dict, unless
        the value reached it through an attribute read, which the reader pass
        catches.
      * A model this app builds but never reaches from `BaseModel`'s subclass
        tree, which today is none: the tripwire counts them.
    """

    #: The models allowed to carry an address, and what each is for.
    #:
    #: `EmailUpdate` is a request body rather than a response and is named here
    #: anyway: the pass walks every model, and an exemption list that quietly
    #: skipped request bodies would be a hole shaped exactly like the next
    #: schema somebody adds.
    ADDRESS_MODELS = {
        "MemberEmailOut": "the four routes in routers/users.py",
        "EmailUpdate": "the body those two writes take",
        "UserCreate": "the body the two routes that create an account take, #103",
    }

    #: The modules allowed to read `.email`, and why each must.
    #:
    #: `models.py` is absent on purpose: declaring the column is an annotated
    #: assignment rather than an attribute read, so it is invisible to this pass
    #: and adding it here would exempt a module that has nothing to exempt.
    ADDRESS_READERS = {
        "auth_backends.py": "the directory writes it, and compares before writing",
        "routers/users.py": "the routes that serve it",
        # **The one widening of issue #80's rule, and it is deliberate.** That
        # issue kept the mailer off `users.email` because a reminder goes to the
        # household mailbox, and that is unchanged: `notifications` still takes
        # its recipients from `overdue_mail_to`. A confirmation code goes to the
        # one person being confirmed, and there is no other address it could go
        # to, so this module reads one and hands it to `mailer.checked_config`
        # as an explicit recipient. It serves none back: `accounts` has no
        # schema, and the code it produces travels to the mailbox rather than to
        # the caller.
        "accounts.py": "the confirmation code is sent to the member's own address",
    }

    #: Modules where **one receiver** may be read, rather than the whole module.
    #:
    #: **`routers/auth.py` is exempt for a request body and nothing else**, and
    #: the distinction is not pedantry: that module builds `Token`, which nests
    #: `UserOut`, which is the disclosure this whole rule exists to prevent. A
    #: module wide exemption there would forgive a future `user.email` on the
    #: response as readily as the `payload.email` #103 needs. The security seat
    #: found the wider version in review.
    #:
    #: The receiver is matched by name, so this says "reads off the thing called
    #: `payload`" rather than "reads off the request body", which is as far as an
    #: `ast` pass can see and is stated here rather than implied.
    ADDRESS_READERS_BY_RECEIVER = {
        "routers/auth.py": ({"payload"}, "registration sets one on the account it creates, #103"),
    }

    #: The name an address goes by on the wire.
    ADDRESS_FIELD = "email"

    def _our_models(self) -> dict[str, type[BaseModel]]:
        """Every Pydantic model defined in this app, by name."""
        import inspect as inspect_module

        import main  # noqa: F401  (imports every router, so every model is built)

        found: dict[str, type[BaseModel]] = {}
        seen: set[type[BaseModel]] = set()

        def walk(model: type[BaseModel]) -> None:
            for subclass in model.__subclasses__():
                if subclass in seen:
                    continue
                seen.add(subclass)
                try:
                    source = Path(inspect_module.getfile(subclass))
                except (TypeError, OSError):
                    source = None
                if (
                    source is not None
                    and BACKEND in source.parents
                    # The rule this file owns, rather than the one name it used
                    # to spell. The class comes from `__subclasses__` and not
                    # from a walk, so what reaches it is whatever a dependency
                    # declared at import: a cache under `backend/` is as much a
                    # source of those as a virtualenv is.
                    and not _is_vendored(source)
                ):
                    found[subclass.__name__] = subclass
                walk(subclass)

        walk(BaseModel)
        return found

    def _serves_an_address(self, schema: object) -> bool:
        """Does this JSON schema document describe an address anywhere in it?

        **One walk over the whole document, rather than `properties` plus a
        second rule for nesting.** The previous version asked pydantic for the
        top level property names and then read Python **annotations** to follow
        nesting, and a reviewer walked straight through the seam between the
        two: a `@computed_field` returning `MemberEmailOut` is in the
        serialization schema and absent from `model_fields`, which is all the
        annotation walk could see. Measured leak: `model_dump()` returning
        `{'id': 0, 'person': {..., 'email': ..., }}` while `model_fields` was
        `['id']`.

        Two mechanisms meeting in the middle is where a hole lives, so there is
        one now. `model_json_schema` already inlines every referenced model into
        a single top level `$defs`, **flattened**: measured, a model nesting a
        model that nests the address model carries both in its own `$defs`. So
        an object node anywhere in the document whose `properties` names the
        address is the whole rule, and it covers the plain field, every alias
        spelling, an `alias_generator`, nesting at any depth, list and dict
        positions, and a computed field, without an arm for any of them.

        The one false positive it can produce is a field literally called
        `properties` holding a mapping with an `email` key. That fails loudly
        and is the safe direction; the alternative walks a schema by knowing
        which keywords nest, which is the enumeration this replaced.
        """
        if isinstance(schema, dict):
            properties = schema.get("properties")
            if isinstance(properties, dict) and self.ADDRESS_FIELD in properties:
                return True
            return any(self._serves_an_address(value) for value in schema.values())
        if isinstance(schema, list):
            return any(self._serves_an_address(item) for item in schema)
        return False

    def _carriers(self, models: dict[str, type[BaseModel]]) -> tuple[set[str], list[str]]:
        """The models that put an address in front of a caller, and any failures.

        Both modes, because the two differ and an address disclosed by either is
        disclosed: `validation_alias` names what a request body may send,
        `serialization_alias` what a response carries, and a computed field is
        in the serialization schema **only**.
        """
        unreadable: list[str] = []
        carriers: set[str] = set()
        for name, model in models.items():
            try:
                schemas = [
                    model.model_json_schema(mode=mode)
                    for mode in ("validation", "serialization")
                ]
            except Exception as error:  # noqa: BLE001  (reported, never skipped)
                unreadable.append(f"{name}: {type(error).__name__}: {error}")
                continue
            if any(self._serves_an_address(schema) for schema in schemas):
                carriers.add(name)
        return carriers, unreadable

    def test_no_other_schema_carries_an_address(self) -> None:
        models = self._our_models()
        carriers, unreadable = self._carriers(models)

        assert not unreadable, (
            "These models could not be asked what they put on the wire, so this "
            "rule said nothing about them. A model it cannot read is a hole, not "
            "an exemption:\n  " + "\n  ".join(sorted(unreadable))
        )

        offenders = sorted(carriers - set(self.ADDRESS_MODELS))
        assert not offenders, (
            "These put a member's address in front of a caller, by naming one on "
            "the wire or by carrying a model that does, and are not one of the "
            f"schemas that may: {offenders}. UserOut is served inside every book "
            "payload and the member list, so an address there is disclosed to "
            "every member who can see a book. Serve it from "
            + "; ".join(f"{name} ({why})" for name, why in self.ADDRESS_MODELS.items())
            + " instead, or change the rule on issue #80 first."
        )

    def test_no_module_outside_the_two_reads_an_address(self) -> None:
        offenders: list[str] = []

        for path in _python_sources():
            where = str(path.relative_to(BACKEND))
            if where in self.ADDRESS_READERS:
                continue
            allowed, _ = self.ADDRESS_READERS_BY_RECEIVER.get(where, (frozenset(), ""))
            tree = ast.parse(path.read_text())
            for node in ast.walk(tree):
                if isinstance(node, ast.Attribute) and node.attr == self.ADDRESS_FIELD:
                    # A read off a named receiver this module may read, and only
                    # that. `payload.email` passes; `user.email` in the same
                    # module is reported.
                    if (
                        isinstance(node.value, ast.Name)
                        and node.value.id in allowed
                    ):
                        continue
                    offenders.append(f"{where}:{node.lineno}")
                elif (
                    isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Name)
                    and node.func.id == "getattr"
                    and len(node.args) >= 2
                    and isinstance(node.args[1], ast.Constant)
                    and node.args[1].value == self.ADDRESS_FIELD
                ):
                    offenders.append(f"{where}:{node.lineno} (getattr)")

        assert not offenders, (
            "These read a member's address, and only "
            + "; ".join(f"{where} ({why})" for where, why in self.ADDRESS_READERS.items())
            + ", plus "
            + "; ".join(
                f"{where} off {sorted(names)} ({why})"
                for where, (names, why) in self.ADDRESS_READERS_BY_RECEIVER.items()
            )
            + " may:\n  "
            + "\n  ".join(sorted(offenders))
        )

    def test_the_two_passes_still_have_something_to_find(self) -> None:
        """Both rules above pass just as well with the field deleted, which is
        how a guard in this repository has twice gone quiet without failing."""
        from models import User

        models_found = self._our_models()
        assert len(models_found) >= 40, (
            f"the model walk found too little to be checking anything: "
            f"{len(models_found)} models"
        )
        assert "UserOut" in models_found, "the walk missed the model this rule exists for"

        carriers, unreadable = self._carriers(models_found)
        assert not unreadable, f"models this rule cannot read: {sorted(unreadable)}"
        for name in self.ADDRESS_MODELS:
            assert name in models_found, f"{name} is gone, so the exemption guards nothing"
            assert name in carriers, (
                f"{name} no longer puts an address on the wire, so it is exempted "
                "for nothing and the pass has stopped having a subject"
            )

        assert self.ADDRESS_FIELD in User.__table__.columns, (
            "users.email is gone, so both passes above are vacuous"
        )

        readers = {
            str(path.relative_to(BACKEND))
            for path in _python_sources()
            if any(
                isinstance(node, ast.Attribute) and node.attr == self.ADDRESS_FIELD
                for node in ast.walk(ast.parse(path.read_text()))
            )
        }
        exempted = set(self.ADDRESS_READERS) | set(self.ADDRESS_READERS_BY_RECEIVER)
        assert readers == exempted, (
            "the reader pass is exempting modules that do not read an address, "
            f"or missing one that does: reads it {sorted(readers)}, "
            f"exempted {sorted(exempted)}"
        )
        # **The narrow exemption has to still be narrow**, or it has quietly
        # become the wide one this pair was split to avoid: the module must read
        # the address off the receiver it names and off nothing else.
        for where, (allowed, _) in self.ADDRESS_READERS_BY_RECEIVER.items():
            tree = ast.parse((BACKEND / where).read_text())
            receivers = {
                node.value.id
                for node in ast.walk(tree)
                if isinstance(node, ast.Attribute)
                and node.attr == self.ADDRESS_FIELD
                and isinstance(node.value, ast.Name)
            }
            assert receivers, f"{where} no longer reads an address, so it is exempted for nothing"
            assert receivers <= allowed, (
                f"{where} reads an address off {sorted(receivers - allowed)}, which "
                f"the narrow exemption does not cover"
            )



class TestEveryTargetResolvesToADoorAndAReader:
    """One roster, and every row in it names something this application implements.

    **The successor to `TestTheProviderRosterIsOneList`, and the shape of the
    question changed with it.** That test compared `metadata`'s two dispatch
    tables, keyed on `CatalogueSource`, against the sets in `sources`. Both
    tables are keyed on `decoders.Reader` now and one reader serves several sources,
    so the comparison cannot be restated: which sources answer what is a field on
    a row, and `sources.LOOKUP_SOURCES` and `SEARCH_SOURCES` are derived from
    those fields rather than written beside them, so there is nothing left for
    two lists to disagree about.

    What is left to check is what the old test was really asking underneath:
    **is there code that can serve what this row claims.** `metadata.resolve` is
    that question and it is a function rather than only a test, because
    `main.seed_catalogue_targets` calls it on every row before writing it, so a
    reader nothing implements fails the boot rather than a member's scan.

    Compared at **runtime** rather than by reading the source with `ast`, which
    is the lesson the old test carried and this one keeps: the guard in
    `test_fetch.py` that counted the search fan out read a list literal out of
    `metadata.search` and stopped being able to when the fan out became a
    comprehension. A table a test can import cannot go stale that way.
    """

    def test_every_seeded_row_resolves(self):
        for target in targets.SEEDED.values():
            metadata.resolve(target)

    def test_a_capability_with_no_reader_behind_it_is_refused(self):
        """The diagonal: `resolve` must report, not merely not raise.

        Both arms, because a version that checked only the lookup passed with
        the search arm deleted. The row is otherwise valid, so what fails is the
        pairing of a capability with a reader, which is the only thing this
        function knows.
        """
        readable = targets.SEEDED[CatalogueSource.LOC]
        with pytest.raises(ValueError):
            metadata.resolve(
                dataclasses.replace(readable, reader=targets.Reader.OPEN_LIBRARY)
            )
        bespoke = targets.SEEDED[CatalogueSource.OPEN_LIBRARY]
        with pytest.raises(ValueError):
            metadata.resolve(
                dataclasses.replace(bespoke, reader=targets.Reader.MARC_GND)
            )

    def test_the_derived_sets_are_the_rows(self):
        """Not a restatement of the derivation: it names the roster's answer.

        A derivation compared against itself is vacuous, so this writes out what
        the eleven rows actually say. A row whose capability changes has to change
        this line too, which is the argument the old test made for writing
        `SEARCH_SOURCES` out rather than deriving it, kept in the one place where
        it still costs nothing.
        """
        assert {source.value for source in sources.LOOKUP_SOURCES} == {
            "dnb", "k10plus", "oenb", "nlg", "nkp", "bne", "open_library",
            "google_books", "bna",
        }
        assert {source.value for source in sources.SEARCH_SOURCES} == {
            "dnb", "k10plus", "oenb", "nlg", "open_library", "google_books",
            "bnf", "loc",
        }
        assert {source.value for source in sources.METERED} == {"google_books"}

    def test_no_reader_is_in_both_search_tables(self):
        """Or a key-needing source would be asked through the keyless path."""
        assert not set(metadata._FREE_SEARCHES) & set(metadata._METERED_SEARCHES)

    def test_every_source_in_the_roster_can_answer_something(self):
        """A member of the enum nothing can ask is a row the screen cannot explain."""
        assert set(sources.DEFAULT_ORDER) == (
            sources.LOOKUP_SOURCES | sources.SEARCH_SOURCES
        )

    def test_the_default_order_names_the_whole_roster_exactly_once(self):
        assert sorted(sources.DEFAULT_ORDER) == sorted(CatalogueSource)

    def test_a_metered_source_is_one_that_needs_a_credential(self):
        """The containment that holds, and the equality that stopped.

        They were one set until a source arrived that is free and credentialled:
        the Biblioteca Nacional Argentina publishes its own login and charges
        nothing. The containment is the half `Plan.lookup_together` rests on,
        since that tier bars a metered source and not a credentialled one, and
        both it and `describe` were re-read when the two came apart.

        **The second line names a row, and that is the weaker half.** There is
        no capability saying "the credential is published", so the exception is
        registered here rather than derived; giving it one is open work, and
        until then a second such catalogue changes this line.
        """
        assert sources.METERED <= sources.NEEDS_A_KEY
        free_but_credentialled = sources.NEEDS_A_KEY - sources.METERED
        assert free_but_credentialled == {CatalogueSource.BNA}


class TestBeliefIsStatedOnceRatherThanTwice:
    """`_SECONDARY_SOURCES` and the tail of `_MATCH_PRECEDENCE` are one fact.

    **Found by a critic, and it predates the provider list.** The sources ranked
    last for belief and the sources docked a point for relevance are the same
    three, written out separately in two constants twelve lines apart. Nothing
    made them agree, and the provider list makes it matter more: they are the
    two rules a household's order deliberately does **not** reach, so a reader
    working out why promoting a source changed nothing has to read both and
    trust that they say the same thing.

    Pinned rather than merged. Deriving one from the other would hide that they
    are two decisions that happen to coincide, and the day a regional catalogue
    is believed late without being docked, this fails and says so.
    """

    def test_the_sources_believed_last_are_the_ones_docked_a_point(self):
        cut = len(metadata._MATCH_PRECEDENCE) - len(metadata._SECONDARY_SOURCES)
        assert frozenset(metadata._MATCH_PRECEDENCE[cut:]) == metadata._SECONDARY_SOURCES

    def test_precedence_names_every_source_and_nothing_else(self):
        """A source missing here sorts last by default, silently."""
        assert sorted(metadata._MATCH_PRECEDENCE) == sorted(
            source.value for source in CatalogueSource
        )


def test_every_seeded_source_is_covered_by_a_silencer():
    """`silence_catalogues` answers for every row, whatever its transport.

    **The hole this closes is silent and it has opened twice.** respx fails a
    test that makes an unmocked request, so a source no silencer covers does not
    fail here: it fails in whichever unrelated test happens to reach it, with a
    message about a URL. Adding the ÖNB broke 21 such tests, and adding the
    Spanish National Library broke 32 more plus four in `tests/routers/`.

    **A request per row rather than a reading of the helper**, because what
    matters is whether a route resolves, and respx resolves in registration
    order with the first match winning. Reading the loop cannot see that.

    `silence_sru_catalogues` deliberately covers less, and its docstring says
    which and why. This is the one that has to cover everything.
    """
    with respx.mock(assert_all_called=False) as mock:
        silence_catalogues(mock)
        unanswered = []
        for target in targets.SEEDED.values():
            # **Z39.50 is excluded and the exclusion is the point.** `fetch.py`
            # never opens that socket, so a row carrying that transport is not
            # reached over HTTP and an HTTP silencer for it would be a route
            # nothing requests. Without this line the day the Z39.50 transport
            # lands, #129, this fails and the cheap way to green it is exactly
            # that useless route.
            if target.transport is targets.Transport.Z3950:
                continue
            try:
                httpx.get(target.base_url, params={"probe": "1"})
            except Exception as error:  # respx raises its own assertion type
                unanswered.append(f"{target.source.value}: {error!r}"[:120])
    assert not unanswered, (
        "these seeded sources are not answered by `silence_catalogues`, so a "
        "test that reaches one fails on an unmocked request instead:\n  "
        + "\n  ".join(unanswered)
    )


class TestNoModuleHardCodesASourceOrder:
    """The ranking is data now, and the guard is that nobody kept a copy.

    The ticket that made it data names this rule: "a settings backed order with
    a constant still consulted somewhere is the failure mode". So the shape
    looked for is any **ordered** literal of two or more catalogue sources.

    **Both spellings, and the second is the one that matters.** The first
    version collected `ast.Constant` strings only, which caught `("dnb",
    "k10plus")` and was blind to `(CatalogueSource.DNB, CatalogueSource.K10PLUS)`.
    That is backwards: `CatalogueSource` exists so new code stops writing the
    strings, `sources.py` already writes every roster as members, and the next
    hard coded order will therefore be in the spelling the guard could not see.
    Measured by a critic against eight real orders of real sources: it reported
    one.

    **Ordered, so `ast.Tuple`, `ast.List` and a dict's keys.** A set has no
    order and cannot be one, which is why `_SECONDARY_SOURCES` needs no
    exemption: it is a `frozenset` and says which sources are docked a point,
    not in what order.

    Five exemptions over six names, each a deliberate table that something
    else pins. The counts differ because one bullet covers the two dispatch
    tables together:

    * `sources.DEFAULT_ORDER`, the seeded order itself.
    * `metadata._MATCH_PRECEDENCE`, which source is believed about a shared
      field, deliberately not reachable from the settings list, and
      `metadata._BESPOKE_LOOKUPS` beside it. This is the bullet the count below
      means by covering two names, and naming the second is what stops the
      sentence explaining an arithmetic nobody can check against it.
    * `targets.SEEDED`, the eleven catalogue rows. **A mapping consulted by key**,
      the narrower claim `SERVES_GROUPS` makes: `metadata` reaches it with
      `SEEDED[name]`, and the four derivations in `sources.py` build
      `frozenset`s, which have no order to read. The order a household gets is
      still `DEFAULT_ORDER`'s, and the copy of it that lives on the rows is
      `Target.rank`, a field on the value rather than the key order, pinned
      against `DEFAULT_ORDER` by
      `test_targets.py::TestTheSeededRosterSaysWhatTheRulesSay::test_rank_is_the_default_order`.
      So the literal's key order is decoration and the guard cannot see that, which
      is what an exemption is for.

      **Two exemptions left when this one arrived**, and their disappearance is
      the thing to notice rather than this one's arrival: `metadata._lookup_one` and
      `metadata._FREE_SEARCHES` were dispatch tables keyed on a source, and there
      is no such table any more. Both are keyed on `targets.Reader` now, one
      reader serves several sources, and a dict of readers is not an order of
      sources in any spelling, so the guard no longer reports them and an
      exemption for them would have no subject.
    * `sources.TAIL_MARGINAL`, how many books the leading tier missed that each
      source asked in turn answers. `MEASURED`'s case exactly: a table of
      measurements keyed on a source, whose completeness is pinned by
      `test_the_marginal_table_covers_the_whole_measured_tail` and whose values
      are recomputed from the committed sample. It is what orders the tail, so
      it is data the order is derived **from** rather than a copy of the order.
      **`sources.SERVES_GROUPS` left the same way and for the same reason**, so
      it is recorded here rather than only in the history: it was a dict literal
      keyed on sources and is a comprehension over `targets.SEEDED` now, the
      remit having moved onto the row. A comprehension is not a literal, the
      guard cannot report it, and an exemption for it would have no subject.
      `test_dropping_an_exemption_surfaces_only_its_own_literal` is what said so,
      by surfacing nothing when its entry was dropped. What still checks that
      table is unchanged and is in `test_sources.py`: its membership,
      its spellings, and its values against the committed sample.
    * `sources.MEASURED`, what each lookup source needing no credential was
      measured to do.
      **Justified by what is checkable rather than by what is obvious.** Nothing
      outside `backend/tests/` reads it, `TIER_UNION` or `SLOT_MUST_EARN` at all,
      every reference to them under `backend/` being a comment, so none can be
      the "constant still consulted somewhere" this guard exists to catch. Its
      completeness is pinned by `TestTheOrderFollowsTheMeasurement` and its
      values by `TestTheConstantsAreRederivableFromTheCommittedSample`. The
      exemption is by identity of that constant's own value, so a plain tuple of
      sources added to `sources.py` tomorrow is still reported. That was checked
      by planting one and watching this test fail, rather than reasoned about.

    **A sequence of objects each carrying a source is invisible here**, and it is
    newly reachable rather than theoretical: `sources.Measured` did not exist
    before the round that added this exemption, and a tuple of records is the
    obvious way to restructure a table out of the dict arm below.
    `_source_named` returns `None` for a `Call`, so a tuple of
    `Measured(source=CatalogueSource.DNB, ...)` is not reported, measured through
    this guard's own `paths` hook against a fixture holding nothing else. **That
    is the argument against restructuring `MEASURED` to satisfy this guard
    rather than exempting it**: the restructure would not satisfy the guard, it
    would blind it, and the exemption keeps more checked than the tidier looking
    alternative.

    **`_METERED_SEARCHES` is deliberately not exempted**, and it was for a round.
    It holds one entry, so it is never two or more sources and is never reported;
    an exemption for it guards nothing, which
    `test_dropping_an_exemption_surfaces_only_its_own_literal` said in as many
    words the moment it was added. The day a second metered source arrives it
    starts being reported and somebody has to decide, which is the right moment
    to be asked rather than a rule that quietly already forgave it.

    **What it still cannot see, said rather than left to be found.** An order
    built by a call rather than written as a literal: `sorted(...)`,
    `"dnb,k10plus".split(",")`, a comprehension over something else. Those are
    reachable only by following values, which is the machinery the shelf guard
    was rewritten to get rid of. The literal forms are what a person writes when
    they mean to fix an order, and that is what this catches.
    """

    #: Where an ordered literal of sources is still allowed, by module and name.
    ALLOWED = {
        "sources.py": {"DEFAULT_ORDER", "MEASURED", "TAIL_MARGINAL"},
        "metadata.py": {"_MATCH_PRECEDENCE", "_BESPOKE_LOOKUPS"},
        # The literal is inline in the `MappingProxyType` call, so the exempt
        # name and the literal are the same assignment again. Naming the view
        # when it wrapped a separate private dict exempted nothing, because a
        # `Call` has no literal behind it; the private name is gone now, and
        # `test_every_exemption_still_exists_to_be_exempted` is what said so.
        "targets.py": {"SEEDED"},
    }

    def _offenders(self, paths: list[Path] | None = None) -> dict[str, set[str]]:
        """Every ordered literal of source names, wherever it sits.

        **Every literal in the module, not only the ones on the right of an
        assignment.** Scoping this to `ast.Assign` was the first version and it
        is the "enumerates something open" trap: an order handed straight to a
        call, used as a default argument, or held in a class body would have
        gone unseen, and each is ordinary Python rather than an evasion somebody
        had to think of.

        `paths` exists so the mutation test can run **this** function over a
        fixture rather than re-implementing it. Its first version walked a
        synthetic tree inline and asserted on its own copy, so it would have
        passed with this function returning `{}`: the tell was a `tmp_path`
        argument it never used.
        """
        names = {source.value for source in CatalogueSource}
        members = {source.name for source in CatalogueSource}
        found: dict[str, set[str]] = {}
        for path in paths if paths is not None else _python_sources():
            module = path.name if paths is not None else str(path.relative_to(BACKEND))
            allowed = self.ALLOWED.get(module, set())
            tree = ast.parse(path.read_text())

            # The literals belonging to an exempt constant, by identity, so the
            # exemption covers exactly that constant's value and nothing that
            # happens to sit near it.
            exempt: set[int] = set()
            for node in ast.walk(tree):
                # **The target is read structurally, not by statement kind.**
                # Listing `ast.Assign` alone exempted neither constant, because
                # both are `_NAME: Final = ...`, an `AnnAssign` with a single
                # `target` rather than a list of `targets`. The guard then
                # reported the literals it exists to permit, which is how this
                # was found.
                bound = getattr(node, "targets", None) or getattr(node, "target", None)
                value = getattr(node, "value", None)
                if bound is None or not isinstance(value, ast.AST):
                    continue
                written = bound if isinstance(bound, list) else [bound]
                if allowed & {
                    target.id for target in written if isinstance(target, ast.Name)
                }:
                    exempt.update(id(inner) for inner in ast.walk(value))

            for node in ast.walk(tree):
                if isinstance(node, (ast.Tuple, ast.List)):
                    candidates: list[list[ast.expr]] = [list(node.elts)]
                elif isinstance(node, ast.Dict):
                    # **Keys and values both.** `{source: index}` is how
                    # `_merge_matches` spells an order and `{index: source}` is
                    # the more natural way to write "position 0 is the DNB";
                    # reading only one side would catch one of the two.
                    candidates = [
                        [key for key in node.keys if key is not None],
                        list(node.values),
                    ]
                else:
                    continue
                if id(node) in exempt:
                    continue
                for elements in candidates:
                    spelled = [
                        named
                        for element in elements
                        if (named := _source_named(element, names, members)) is not None
                    ]
                    if len(spelled) >= 2 and len(spelled) == len(elements):
                        found.setdefault(module, set()).add(", ".join(sorted(spelled)))
                        break
        return found

    def test_no_module_keeps_its_own_list_of_source_names(self):
        assert self._offenders() == {}, (
            "a hard coded source order is back: "
            f"{ {name: sorted(where) for name, where in self._offenders().items()} }"
        )

    @pytest.mark.parametrize(
        ("shape", "source"),
        [
            ("strings", '_ORDER = ("dnb", "k10plus")'),
            ("enum members", "_ORDER = (CatalogueSource.DNB, CatalogueSource.K10PLUS)"),
            ("a list", '_ORDER = ["dnb", "loc"]'),
            ("the value attribute", "_ORDER = (CatalogueSource.BNF.value, CatalogueSource.LOC.value)"),
            ("a call argument", 'def f():\n    return g(["dnb", "loc"])'),
            ("a default argument", 'def f(order=("bnf", "oenb")):\n    return order'),
            ("a class body", 'class C:\n    ORDER = ["loc", "bnf"]'),
            ("a dict keyed on sources", "_M = {CatalogueSource.DNB: 0, CatalogueSource.OENB: 1}"),
            ("a rank written as a float", "_M = {CatalogueSource.DNB: 0.9, CatalogueSource.OENB: 0.8}"),
            (
                "an order nested inside a table keyed on a source",
                "_M = {CatalogueSource.DNB: (CatalogueSource.LOC, CatalogueSource.BNF)}",
            ),
            ("nested in a dict value", '_M = {"a": ("dnb", "oenb")}'),
            ("a dict keyed on position", '_M = {0: "dnb", 1: "loc"}'),
            (
                "an aliased import",
                "from enums import CatalogueSource as CS\n_O = (CS.DNB, CS.K10PLUS)",
            ),
            (
                "a dotted receiver",
                "import enums\n_O = (enums.CatalogueSource.DNB, enums.CatalogueSource.LOC)",
            ),
            ("the subscript spelling", '_O = (CatalogueSource["DNB"], CatalogueSource["LOC"])'),
            ("an order carrying a weight", '_O = (("dnb", 1.0), ("k10plus", 0.9))'),
            ("a mixed spelling", '_O = ("dnb", CatalogueSource.LOC)'),
        ],
    )
    def test_the_guard_reports_every_shape_an_order_is_written_in(
        self, tmp_path: Path, shape: str, source: str
    ) -> None:
        """A mutation per shape, run through `_offenders` itself.

        **Real sources, never invented names**, or the fixture would pass
        whatever the rule did. One shape per case rather than one case listing
        them, so a shape that stops being reported names itself.
        """
        fixture = tmp_path / "offender.py"
        fixture.write_text(source + "\n")
        assert self._offenders([fixture]) != {}, f"{shape} is invisible to the guard"

    @pytest.mark.parametrize(
        ("shape", "source"),
        [
            ("a single source", '_ONE = ("dnb",)'),
            ("strings that are not sources", '_X = ("alpha", "beta")'),
            ("a set, which has no order", "_S = {CatalogueSource.BNF, CatalogueSource.LOC}"),
            ("a mixed tuple", '_X = ("dnb", "not a source")'),
        ],
    )
    def test_the_guard_leaves_alone_what_is_not_an_order(
        self, tmp_path: Path, shape: str, source: str
    ) -> None:
        """The other half of the diagonal: it must not report everything."""
        fixture = tmp_path / "innocent.py"
        fixture.write_text(source + "\n")
        assert self._offenders([fixture]) == {}, f"{shape} is reported and should not be"

    def test_every_exemption_still_exists_to_be_exempted(self):
        """An allowlist entry for a deleted constant guards nothing."""
        owners = {"sources.py": sources, "metadata.py": metadata, "targets.py": targets}
        for module, allowed in self.ALLOWED.items():
            for name in allowed:
                assert hasattr(owners[module], name), (
                    f"{module}:{name} is gone, so its exemption has no subject"
                )

    def test_dropping_an_exemption_surfaces_only_its_own_literal(self):
        """Each exemption is pinned by something, and only by itself.

        One mutation dropping two names at once cannot show that either was
        pinning anything, so this drops them one at a time.

        **It compares which literal came back, not merely that one did.** The
        first version asserted `module in offenders`, so the name promised more
        than it checked: four exemptions could all have surfaced the same
        literal and it would have passed. Now each drop must produce exactly one
        literal for its module, and they must be distinct, which is what "only
        its own" says.

        **Distinct as a module and a literal together, not as a literal**, and
        that correction was bought by an exemption arriving in a third module.
        `sources.DEFAULT_ORDER` and `targets.SEEDED` both name the whole roster,
        so they surface the identical joined string while sitting in different
        files and pinning different constants. Comparing the strings alone read
        that as neither being pinned. The offenders map is keyed by module, so
        the identity of a surfaced literal is the pair; the old spelling was a
        unit that had never had two modules producing one literal to be wrong
        about.
        """
        surfaced: dict[str, frozenset[str]] = {}
        for module, allowed in self.ALLOWED.items():
            for name in sorted(allowed):
                guard = TestNoModuleHardCodesASourceOrder()
                guard.ALLOWED = {
                    where: (names - {name} if where == module else names)
                    for where, names in self.ALLOWED.items()
                }
                reported = guard._offenders().get(module, set())
                assert len(reported) == 1, (
                    f"{module}:{name} surfaced {sorted(reported)}; dropping one "
                    "exemption should surface exactly that constant's literal"
                )
                surfaced[f"{module}:{name}"] = frozenset(
                    f"{module}:{literal}" for literal in reported
                )

        assert len(set(surfaced.values())) == len(surfaced), (
            "two exemptions surface the same literal, so neither is pinned by "
            f"itself: {surfaced}"
        )


def _source_named(
    element: ast.expr, names: set[str], members: set[str]
) -> str | None:
    """The source this element names, in any spelling, or None.

    **The receiver is deliberately not checked.** Requiring
    `Name(id="CatalogueSource")` hard coded one spelling of the *receiver* in
    place of one spelling of the *name*, which is the same mistake one level
    along: `from enums import CatalogueSource as CS` and
    `import enums` then `enums.CatalogueSource.DNB` are both plain literals and
    both were invisible. The first is the aliased-import shape this repository
    has already been caught by once.

    **The cost is a false positive, and it stopped being latent.** Any attribute
    whose name is a member counts, so an unrelated enum with a colliding member
    is reported. This paragraph used to say no enum collided and that the cost
    was therefore hypothetical; `targets.Reader` collides on `OPEN_LIBRARY` and
    `GOOGLE_BOOKS`, because a reader is named after the one catalogue it reads,
    and `metadata._BESPOKE_LOOKUPS` is reported for it. That is the exemption in
    `ALLOWED` and it is a false positive rather than an order.

    It is still the right trade, because the alternative is resolving aliases by
    following imports, and because a false positive fails loudly and is cleared
    in a minute where a miss is silent and permanent. What it costs is stated
    rather than glossed: the guard cannot see a real source order written inside
    that one table, and nothing else can either.

    **It recurses one level into a tuple or list**, because an order carrying a
    weight per source, `(("dnb", 1.0), ("k10plus", 0.9))`, is exactly how a
    reintroduced ranking gets written and is an ordered literal of two sources
    by any reading.

    **What it still does not read: an order built from a name or a
    comprehension**, never merely one wrapped in a call. Every literal in the
    module is walked wherever it sits, so `sorted(("dnb", "loc"))` and
    `tuple(["dnb", "loc"])` **are** reported, both measured. What survives is
    `"dnb,loc".split(",")`, `sorted(KNOWN, key=rank)` and
    `[s for s in KNOWN if s in ENABLED]`, where the order comes from something
    that is not a literal. Following values is the machinery the shelf guard was
    rewritten to be rid of.

    This paragraph said "a call" for a round, which understated the guard in the
    direction a reader could act on: somebody could have concluded that wrapping
    a literal in `sorted` evades it, and written exactly that.
    """
    if isinstance(element, ast.Constant) and element.value in names:
        return str(element.value)
    # `CatalogueSource["DNB"]`, the subscript spelling of a member.
    if (
        isinstance(element, ast.Subscript)
        and isinstance(element.slice, ast.Constant)
        and element.slice.value in members
    ):
        return str(element.slice.value)
    if isinstance(element, ast.Attribute):
        # `CatalogueSource.DNB.value`: unwrap one attribute and try again.
        if element.attr == "value":
            return _source_named(element.value, names, members)
        if element.attr in members:
            return element.attr
    # A pair or a row: the source it is about, whatever else it carries.
    if isinstance(element, (ast.Tuple, ast.List)):
        for inner in element.elts:
            found = _source_named(inner, names, members)
            if found is not None:
                return found
    return None


class TestEveryOutboundEntryPointTakesTheProviderList:
    """"Off means not asked" holds by signature, not by discipline.

    **A required parameter rather than a rule somebody remembers.** Every public
    coroutine in `metadata.py` reaches a catalogue, and each takes `plan`
    keyword only with no default, so mypy refuses a call site that forgets to
    apply the library's provider list. A default would have made forgetting
    silent, and the thing it would silently do is ask a source the library
    switched off.

    This is the second leg. The first is that the plan is honoured *inside*
    those functions, which `tests/test_sources.py` owns. What this catches is a
    new door: a public entry point added later that reaches outward with no plan
    at all, which no type checker can notice because there is nothing to check
    it against.

    **Public, deliberately.** The private helpers each source is fetched with
    (the DNB title search, `_open_library`) take no plan and must not: they are called
    only from the two functions that have already filtered, and requiring one of
    them too would put the same decision in two places.
    """

    #: The entry points as they stand. Named so that a **removed** door fails
    #: this too: a rule that only checks what it finds passes happily on a file
    #: whose subject has been deleted, which has happened twice in this suite.
    DOORS = {"lookup", "search", "title_search", "editions", "candidates"}

    def _public_coroutines(self) -> dict[str, set[str]]:
        tree = ast.parse((BACKEND / "metadata.py").read_text())
        return {
            node.name: {
                argument.arg
                for argument in [*node.args.args, *node.args.kwonlyargs]
            }
            for node in tree.body
            if isinstance(node, ast.AsyncFunctionDef)
            and not node.name.startswith("_")
        }

    def test_every_public_entry_point_takes_a_plan(self):
        missing = {
            name
            for name, arguments in self._public_coroutines().items()
            if "plan" not in arguments
        }
        assert missing == set(), (
            f"these reach a catalogue with no provider list: {sorted(missing)}"
        )

    def test_the_doors_are_the_ones_this_rule_was_written_against(self):
        """A door removed or renamed is a finding, not a quieter pass."""
        assert set(self._public_coroutines()) == self.DOORS

    def test_the_plan_cannot_be_defaulted_away(self):
        """Keyword only with no default, or forgetting it stops being an error.

        Checked on the signature rather than trusted to review: a default is one
        character of diff and turns a compile error into a source being asked
        that somebody switched off.
        """
        for name in self.DOORS:
            signature = inspect.signature(getattr(metadata, name))
            parameter = signature.parameters["plan"]
            assert parameter.kind is inspect.Parameter.KEYWORD_ONLY, name
            assert parameter.default is inspect.Parameter.empty, name


#: The `str` predicates that answer an alphanumeric question over the whole of
#: Unicode, where the caller means `0` to `9`, or `0` to `9` and `A` to `Z`.
#:
#: **The name used to say "digit" and the family was always wider than that.**
#: `isalnum` belongs to the same defect and was missing: `isbn.normalise` filters
#: on `character.isascii() and character.isalnum()`, and the narrowing half is
#: what makes it agree with `frontend/src/lib/isbn.ts`, whose `[^0-9A-Za-z]` is
#: not Unicode. Dropping that `isascii()` was reportable by nothing, because the
#: rule below walked three names and this is the fourth.
#:
#: The other eight predicates have their verdict in `_PREDICATES_LEFT_ALONE`, and
#: `test_every_str_character_class_predicate_has_a_verdict` pins the union of the
#: two against `dir(str)`. A predicate CPython adds fails that test rather than
#: falling through the gap this one fell through, and a name deleted from here
#: fails it too.
_ALPHANUMERIC_PREDICATES: Final = frozenset(
    {"isalnum", "isdecimal", "isdigit", "isnumeric"}
)

#: Every other `str` predicate whose name begins `is`, mapped to the reason this
#: rule is not about it.
#:
#: **A mapping rather than a set, so a name cannot arrive without a reason.** A
#: comment above a run of names says nothing about which of them it covers, and
#: the cheapest way to green the verdict test when CPython adds a predicate is one
#: word in a set. That is how `isalnum` was lost from the rule for as long as it
#: was: the name went in somewhere plausible and nobody was asked why.
#:
#: The call site counts below are measured 2026-09-06 over the modules
#: `_python_sources` returns, by walking the `ast` for a call of that name.
#: **The corpus is named and not counted**: how many modules it held on the day
#: is not the measurement, and a size written beside a count is the figure that
#: goes stale first. Read with the `ast` rather than with `grep`, which counts
#: lines where the claim is calls: `isprintable` reads 5 that way and is 3, the
#: other two being prose about it.
_PREDICATES_LEFT_ALONE: Final = {
    "isascii": "the narrowing call this rule demands, so it is the remedy",
    "isalpha": (
        "the near miss, out deliberately: 0 call sites, and an alphabetic test "
        "over Unicode is the ordinary correct thing where a digit test over "
        "Unicode is almost never what the caller meant"
    ),
    "isidentifier": "asks about Python's own grammar, which is Unicode on purpose",
    "islower": "asks about case, not about which alphabet",
    "isprintable": (
        "a different question, and 3 call sites none of which is narrowed, so "
        "adding it would be a cleanup of live code rather than a guard widening"
    ),
    "isspace": (
        "a different question, and 4 call sites none of which is narrowed, so "
        "adding it would be a cleanup of live code rather than a guard widening"
    ),
    "istitle": "asks about case, not about which alphabet",
    "isupper": "asks about case, not about which alphabet",
}


def _receiver_key(node: ast.expr) -> str:
    """A receiver's identity, with a walrus unwrapped to the name it binds.

    **`(x := f()).isascii() and x.isdigit()` is the ordinary way to write this**
    and the two receivers are the same object, so comparing raw `ast.dump` would
    report the correct shape and push whoever hit it into writing something
    worse. That is the guard flagging the door it exists to promote, and it
    happened on the first run of this rule against `dependencies.row_ids`.
    """
    if isinstance(node, ast.NamedExpr):
        node = node.target
    # **Every `ctx` flattened to `Load`, or the walrus case still misses.** The
    # target of `(x := ...)` is a `Name` with `ctx=Store()` and the later `x` is
    # the same `Name` with `ctx=Load()`, so their raw dumps differ and the
    # unwrapping above buys nothing on its own. Found by the fixture below
    # rather than by reading this function.
    node = copy.deepcopy(node)
    for inner in ast.walk(node):
        if hasattr(inner, "ctx"):
            inner.ctx = ast.Load()
    return ast.dump(node)


def _isascii_receivers(node: ast.AST) -> set[str]:
    """Every receiver `x` for which this subtree calls `x.isascii()`."""
    return {
        _receiver_key(inner.func.value)
        for inner in ast.walk(node)
        if isinstance(inner, ast.Call)
        and isinstance(inner.func, ast.Attribute)
        and inner.func.attr == "isascii"
    }


class TestAnAlphanumericPredicateIsAlwaysNarrowedToAscii:
    r"""`str.isdigit()` is not a guard for `int()`, and this is the rule that says so.

    **The family is alphanumeric, not digits.** `str.isalnum()` is the same
    defect one alphabet wider: `isbn.normalise` keeps a character when it is
    alphanumeric, and without an `isascii()` beside it that keeps characters
    `frontend/src/lib/isbn.ts` strips, so the two implementations answer
    different ISBNs for one input. A rule named for digits and walking three
    names is a rule that cannot see an instance of its own defect class, which is
    what `_PREDICATES_LEFT_ALONE` and the verdict test below exist to stop.

    **Two live defects bought this test, and they failed in opposite
    directions.** `isbn.is_valid_isbn13` gated on `isdigit()` alone. A superscript
    two, `U+00B2`, is `isdigit()` and `int()` **raises** on it, so
    `GET /api/books/lookup?isbn=978` and ten of them left the router as an
    unhandled `ValueError`. An Arabic-Indic zero, `U+0660`, is `isdigit()` and
    `int()` **accepts** it, so a checksum over it can pass and `POST /api/books`
    stored a non ASCII string that `uq_books_isbn_single_copy` could not see as
    the same book. `dependencies.row_ids` had the first shape on a query string.

    **A helper was the obvious fix and is the weaker one.** A
    `is_ascii_digits()` that four modules import is bypassed by anybody writing
    `.isdigit()` directly, which is exactly what five call sites had already
    done. Requiring the two calls together at every site is enforceable here and
    cannot be bypassed by writing the ordinary thing.

    **Receiver matched, not merely present.** `if a.isascii() and b.isdigit()`
    would satisfy a rule that only asked whether an `isascii` call was nearby,
    and that is the likeliest way to get this wrong rather than an evasion
    somebody has to think of.

    **Scoped to backend modules and not the test tree**, which is where such a
    predicate over committed fixture data is ordinary and carries no external
    input. `_python_sources` already draws that line for four rules above.

    **What it does not reach, said because the first version of this docstring
    claimed it did.** It said "every digit predicate in every backend module"
    while enumerating three `str` methods, and there is a fifth beyond the four
    now in `_ALPHANUMERIC_PREDICATES`: **`re`'s `\d`**, which is `isdecimal()`
    rather than `isdigit()`. Measured:
    `re.fullmatch(r"\d{3}", "٣٣٠")` matches and `"²²²"` does not, so it admits
    the quiet half of this defect and refuses the crashing half. There are
    **16** string literals containing `\d` across **five** backend modules,
    counted 2026-08-31 by walking the AST of everything `_python_sources`
    returns and excluding docstrings; `ddc._NOTATION` is the one whose match is
    **stored** rather than handed to `int()`.

    **That count was 17 across six for as long as it took to check it.** The
    first version was read off a `grep`, which counts lines rather than literals
    and cannot tell a trailing comment from a pattern. Recount by walking the
    tree, in a paragraph whose whole subject is a claim wider than its evidence.

    **The instrument that would have caught this rule's own defect now exists.**
    The paragraph above shipped with a bare `\d` in a non raw docstring, which
    CPython warns about and nothing in this tree read.
    `TestEveryPythonFileCompilesWithoutAWarning` at the foot of this file
    compiles every non vendored Python file under `backend/` with warnings
    recorded, which is why that paragraph is raw today.

    **Not enforced here, deliberately.** `\d` is a different rule with a
    different fix (`re.ASCII`, or `[0-9]`), a different blast radius, and its own
    argument about which of those 16 want it. What belongs to this rule is that
    its stated reach is its real one. That is the same defect class as
    `targets.Target.isbn_query`'s rationale, corrected in the same round: code that is
    defensible while the reason written beside it is not.
    """

    def _offenders(self, paths: list[Path] | None = None) -> list[str]:
        found: list[str] = []
        for path in paths if paths is not None else _python_sources():
            tree = ast.parse(path.read_text())
            parents: dict[ast.AST, ast.AST] = {}
            for node in ast.walk(tree):
                for child in ast.iter_child_nodes(node):
                    parents[child] = node
            for node in ast.walk(tree):
                if not (
                    isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Attribute)
                    and node.func.attr in _ALPHANUMERIC_PREDICATES
                ):
                    continue
                receiver = _receiver_key(node.func.value)
                # Climb to every enclosing `and`, and ask whether any operand
                # other than this call's own subtree narrows the same receiver.
                narrowed = False
                current: ast.AST | None = node
                while current is not None and not narrowed:
                    parent = parents.get(current)
                    if isinstance(parent, ast.BoolOp) and isinstance(
                        parent.op, ast.And
                    ):
                        narrowed = any(
                            operand is not current
                            and receiver in _isascii_receivers(operand)
                            for operand in parent.values
                        )
                    current = parent
                if not narrowed:
                    # `path.name` rather than a path relative to `BACKEND`: the
                    # fixture files the mutation tests below hand to `paths` sit
                    # under pytest's `tmp_path` and `relative_to` raises for
                    # them, which turned every one of those tests red for a
                    # reason that had nothing to do with the rule.
                    found.append(f"{path.name}:{node.lineno} .{node.func.attr}()")
        return found

    def test_no_backend_module_trusts_an_alphanumeric_predicate_on_its_own(self):
        assert self._offenders() == []

    def test_every_str_character_class_predicate_has_a_verdict(self):
        """The two sets are read back against the runtime rather than against a
        memory of what `str` carries. A predicate CPython adds is a gap in this
        rule until somebody judges it, and a name deleted from
        `_ALPHANUMERIC_PREDICATES` is the way this rule went quiet about
        `isalnum` for as long as it did: both fail here rather than passing
        smaller. The other set is a mapping, so the name that closes this test
        cannot be added without the reason beside it."""
        assert {name for name in dir(str) if name.startswith("is")} == (
            _ALPHANUMERIC_PREDICATES | _PREDICATES_LEFT_ALONE.keys()
        )

    @pytest.mark.parametrize(
        ("shape", "source"),
        [
            ("a bare call", "def f(s):\n    return s.isdigit()"),
            ("negated, no conjunction", "def f(s):\n    if not s.isdigit():\n        return 0"),
            ("isnumeric", "def f(s):\n    return s.isnumeric()"),
            ("isdecimal", "def f(s):\n    return s.isdecimal()"),
            ("isalnum", "def f(s):\n    return s.isalnum()"),
            (
                "isascii on a different receiver",
                "def f(a, b):\n    return a.isascii() and b.isdigit()",
            ),
            (
                "isascii joined by or rather than and",
                "def f(s):\n    return s.isascii() or s.isdigit()",
            ),
            (
                "a subscript receiver narrowed on a different slice",
                "def f(s):\n    return s[:4].isascii() and s[:5].isdigit()",
            ),
            (
                "a walrus narrowed on a different name",
                "def f(a, b):\n    return (x := a).isascii() and (y := b).isdigit()",
            ),
        ],
    )
    def test_the_rule_sees_every_way_of_getting_it_wrong(
        self, tmp_path: Path, shape: str, source: str
    ):
        """One shape per case, so a shape that stops being reported names itself."""
        fixture = tmp_path / "offender.py"
        fixture.write_text(source + "\n")
        assert self._offenders([fixture]) != [], f"{shape} is invisible to the rule"

    @pytest.mark.parametrize(
        ("shape", "source"),
        [
            ("the shape this rule wants", "def f(s):\n    return s.isascii() and s.isdigit()"),
            (
                "narrowed once, negated as a whole",
                "def f(s):\n    if not (s.isascii() and s.isdigit()):\n        return 0",
            ),
            (
                "the digit test nested inside the narrowed conjunction",
                'def f(s):\n    return s.isascii() and (s.isdigit() or s == "X")',
            ),
            (
                "a matching subscript receiver",
                "def f(s):\n    return s[:4].isascii() and s[:4].isdigit()",
            ),
            (
                "isalnum narrowed on the same receiver",
                "def f(s):\n    return s.isascii() and s.isalnum()",
            ),
            ("no alphanumeric predicate at all", "def f(s):\n    return s.isascii()"),
            (
                "a walrus narrowed and then reused by name",
                "def f(t):\n    return (x := t.strip()).isascii() and x.isdigit()",
            ),
        ],
    )
    def test_the_rule_leaves_the_correct_shape_alone(
        self, tmp_path: Path, shape: str, source: str
    ):
        """The other half of the diagonal: it must not report everything."""
        fixture = tmp_path / "innocent.py"
        fixture.write_text(source + "\n")
        assert self._offenders([fixture]) == [], f"{shape} is reported and should not be"
class TestOneReaderPerAmbiguousSubfield:
    """`$2` means a vocabulary on a subject field and a Dewey edition on `082`.

    So the same two characters are a subject vocabulary in one field and the
    edition of a schedule in another, and the second is what this repository's
    own fixtures carry: `23sdnb` on the DNB record, `22/ger` on the OENB's and
    `21` on the National Library of Greece's, all three on `082`. A reader that
    took `$2` off whatever field it had in hand would record a vocabulary called
    "21", and nothing would fail: the value is a string, the column is a string,
    and the mistake surfaces as a subject labelled with an edition number months
    later.

    **This class no longer guards which field is passed, and that is the
    correction rather than a narrowing.** Its first version counted **readers of
    the subfield** while its docstring claimed to enforce "a subject field
    only", so `_subject_vocabulary(fields["082"][0])` was legal, was the exact
    failure described, and left this green. That half is now the signature:
    `metadata._subject_vocabulary` takes the tag and raises outside
    `_DNB_SUBJECT_TAGS`, which no source scan can be evaded past. What is left
    here is the half a scan can do, which is that nothing else reads the
    subfield at all.

    **It matches the constant, not a list of spellings.** The first version
    enumerated `get`, `all` and a subscript, "three spellings because
    `_Subfields` offers three". `_Subfields` subclasses `dict`, so it offers
    every dict reader: measured against that version, **8 of 10** shapes
    carrying a literal `"2"` went unreported, including `e.pop("2", None)`,
    `e.setdefault("2", None)`, `dict.get(e, "2")`, `getattr(e, "get")("2")`,
    `e.get(*("2",))` and an `items()` loop testing `c == "2"`. A fourth arm
    would have been a fourth guess. The denominator is what makes the structural
    rule affordable: the whole backend carries **two** `"2"` string constants
    outside docstrings, and both are named in `SITES`.

    ## What the constant rule accepts that the spelling rule refused

    Asking that, rather than "is the new rule better", is what this class exists
    to record, because the answer was **yes, once**, and it took a second seat to
    find it. The replacement collected its sites into a **set** and compared
    `found == set(SITES)`, where the version it replaced accumulated a list. A
    set cannot see a second site that reports the same qualified name, and a
    method sharing a module level function's name is the ordinary shape of that,
    not a contrived one. Measured by appending a `class _Reader` with its own
    `_subject_vocabulary` to `metadata.py` in memory: the set form compared equal
    to `SITES` with the second reader present, and the list form reported
    `metadata._subject_vocabulary` twice. So the count is load bearing and the
    comparison is on sorted **lists**.

    **Identity is the path, not `path.stem`.** That is the same defect one level
    down and it came through the rewrite untouched from the first version.
    `_python_sources()` already holds **eight** colliding stems, `auth`,
    `backup`, `covers`, `imports`, `public`, `settings`, `sru` and `stats`, each
    a module at the root and one under `routers/` or `schemas/`. Neither
    `metadata` nor `marc` collides today, which is why nothing failed; a reader
    added to `routers/metadata.py` would have been indistinguishable from the
    allowlisted one.

    Everything else the audit compared came out stronger rather than weaker, and
    the cases are worth naming because two of them were blind spots the first
    version admitted to and this one closes: a code **bound to a name** first
    (`CODE = "2"` then `e.get(CODE)`), a code as a **default argument**, and a
    code in a **class body** outside every function are all reported here and
    were all invisible before. An `f"2"` and a `"\x32"` are reported too,
    checked by parsing rather than assumed, because both hold a `Constant` whose
    value is the code.

    **Blind spots, listed rather than left to be found.** A code assembled at
    run time dodges it: `chr(50)`, or `"12"[1]`, carry no `"2"` constant, and
    they are the honest floor of any rule that reads source rather than running
    it. A function whose entire docstring is `"2"` is exempt and harmless, since
    a docstring reads nothing. The test tree is not scanned, which is what lets
    the checks below build offending source at all.
    """

    #: The only two places in the backend that may spell the subfield code.
    #:
    #: One reader and one writer, as `(path below backend/, function)`. A path
    #: rather than a module name: see the docstring on the eight colliding
    #: stems.
    SITES = (
        ("marc.py", "_subject_fields"),
        ("metadata.py", "_subject_vocabulary"),
    )

    #: The subfield whose meaning depends on the field it sits in.
    #:
    #: Spelled plainly, and needing no dodge: `_python_sources` excludes the
    #: test tree, so this class cannot trip its own rule. That is worth saying
    #: rather than splitting the constant defensively, because a defence with no
    #: threat behind it is the kind of comment this file exists to stop.
    CODE = "2"

    @classmethod
    def _spells_the_code(cls, node: ast.AST) -> bool:
        return isinstance(node, ast.Constant) and node.value == cls.CODE

    @classmethod
    def _sites_in(cls, source: str, where: str) -> list[tuple[str, str]]:
        """Every `(where, function)` in this source spelling the subfield code.

        A **list**, and repeats are kept: two functions of one name in one file
        are two sites, and collapsing them is what let a second reader through.

        A constant at module level, or in a class body outside every function,
        is reported as `<module>`: the walk below descends into functions, so it
        would otherwise be invisible.
        """
        tree = ast.parse(source)
        docstrings = _docstring_nodes(tree)
        found: list[tuple[str, str]] = []
        in_a_function: set[ast.AST] = set()
        for parent in ast.walk(tree):
            if not isinstance(parent, ast.FunctionDef | ast.AsyncFunctionDef):
                continue
            owned = set(ast.walk(parent))
            in_a_function |= owned
            if any(
                cls._spells_the_code(node)
                for node in owned
                if node not in docstrings
            ):
                found.append((where, parent.name))
        if any(
            cls._spells_the_code(node)
            for node in ast.walk(tree)
            if node not in in_a_function and node not in docstrings
        ):
            found.append((where, "<module>"))
        return found

    def test_only_the_two_named_sites_spell_the_subfield_code(self):
        found: list[tuple[str, str]] = []
        for path in _python_sources():
            found += self._sites_in(
                path.read_text(), str(path.relative_to(BACKEND))
            )

        assert sorted(found) == sorted(self.SITES), sorted(found)

    def test_a_second_site_of_the_same_name_is_not_swallowed(self):
        """The defect the set form had, as a test rather than as a paragraph.

        A class method sharing the module level function's name reports the same
        pair twice. Under `==` on sorted lists that is a failure; under set
        equality it was invisible.
        """
        source = (
            'def _subject_vocabulary(e):\n    return e.get("2")\n\n\n'
            'class _Reader:\n    def _subject_vocabulary(self, e):\n'
            '        return e.get("2")\n'
        )
        found = self._sites_in(source, "metadata.py")

        assert found == [
            ("metadata.py", "_subject_vocabulary"),
            ("metadata.py", "_subject_vocabulary"),
        ]
        assert set(found) == {("metadata.py", "_subject_vocabulary")}

    def test_two_files_of_one_stem_are_two_sites(self):
        """`path.stem` was the identity and nine stems already collide.

        `metadata` is not one of them today, so nothing failed; a reader added
        to `routers/metadata.py` would have been indistinguishable from the
        allowlisted one. Asserted on the collision this file would actually see.
        """
        reader = 'def _subject_vocabulary(e):\n    return e.get("2")\n'

        assert self._sites_in(reader, "metadata.py") != self._sites_in(
            reader, "routers/metadata.py"
        )

    def test_the_stems_that_already_collide_are_still_only_these(self):
        """A count in prose does not recount itself, so this recounts it.

        The docstring names nine, and it named seven until `sru.py` arrived
        beside `routers/sru.py` and eight until `opds.py` did. If a tenth
        appears the number above is stale, and this says so at the rule rather
        than leaving the next reader to trust it.
        """
        stems: dict[str, list[str]] = {}
        for path in _python_sources():
            stems.setdefault(path.stem, []).append(str(path.relative_to(BACKEND)))
        colliding = {stem for stem, paths in stems.items() if len(paths) > 1}

        assert colliding == {
            "auth",
            "backup",
            "covers",
            "imports",
            "opds",
            "public",
            "settings",
            "sru",
            "stats",
        }
        assert not colliding & {"marc", "metadata"}

    def test_both_named_sites_still_spell_it_exactly_once(self):
        """A rule whose subject was deleted passes by having nothing to find.

        Twice in this repository a guard went green with its own subject gone,
        so each allowlisted site is asserted to be a real function that really
        spells the code. **Exactly once**, not merely present: an `in` test
        would accept a second spelling inside the same file, which is the same
        multiplicity hole the set form had, one scope down.
        """
        for where, function in self.SITES:
            found = self._sites_in((BACKEND / where).read_text(), where)

            assert found.count((where, function)) == 1, (where, found)

    @pytest.mark.parametrize(
        "spelling",
        [
            'def _sneak(e):\n    return e.get("2")\n',
            'def _sneak(e):\n    return e.get("2", "")\n',
            'def _sneak(e):\n    return e.all("2")\n',
            'def _sneak(e):\n    return e["2"]\n',
            'def _sneak(e):\n    return e.pop("2", None)\n',
            'def _sneak(e):\n    return e.setdefault("2", None)\n',
            'def _sneak(e):\n    return dict.get(e, "2")\n',
            'def _sneak(e):\n    return getattr(e, "get")("2")\n',
            'def _sneak(e):\n    return e.get(*("2",))\n',
            'def _sneak(e):\n    return e.get(f"2")\n',
            'def _sneak(e):\n    return e.get("\\x32")\n',
            'def _sneak(e):\n    code = "2"\n    return e.get(code)\n',
            'def _sneak(e, code="2"):\n    return e.get(code)\n',
            'def _sneak(e):\n    for c, v in e.items():\n        if c == "2":\n            return v\n',
            'def _sneak(e):\n    return next(v for c, v in e.items() if c == "2")\n',
            'async def _sneak(e):\n    return e.get("2")\n',
        ],
    )
    def test_every_shape_that_spells_the_code_is_caught(self, spelling):
        """Sixteen shapes, twelve of which the enumerating version missed.

        The point of the list is not that it is complete, which no list is. It
        is that every one of them has to write the code down, and the rule is
        about writing it down rather than about how it is then used. The last
        two added are the two blind spots the enumerating version admitted to
        and this one closes: a name bound first, and a default argument.
        """
        assert self._sites_in(spelling, "elsewhere.py") == [
            ("elsewhere.py", "_sneak")
        ]

    def test_a_constant_outside_every_function_is_caught(self):
        """Both shapes: module level, and a class body with no function in it."""
        assert self._sites_in('X = ENTRY.get("2")\n', "elsewhere.py") == [
            ("elsewhere.py", "<module>")
        ]
        assert self._sites_in('class C:\n    CODE = "2"\n', "elsewhere.py") == [
            ("elsewhere.py", "<module>")
        ]

    def test_prose_naming_the_subfield_is_not_a_site(self):
        """A rule that cannot be written down without tripping itself gets
        deleted rather than obeyed, so a docstring is not a site. This is the
        diagonal for the exemption: the same text as an expression **is**."""
        assert (
            self._sites_in('def _fine(e):\n    """$2 and e.get("2")."""\n', "x.py")
            == []
        )
        assert self._sites_in('def _bad(e):\n    """d"""\n    "2"\n', "x.py") == [
            ("x.py", "_bad")
        ]

    def test_another_subfield_is_not_reported(self):
        """The diagonal: the rule is about this code and not about subfield
        reads. Without it, a guard matching any `get` would pass its own
        fixtures while reporting every parser in the file."""
        assert self._sites_in('def _fine(e):\n    return e.get("a")\n', "x.py") == []
        assert self._sites_in('def _fine(e):\n    return e.all("0")\n', "x.py") == []
        assert self._sites_in('def _fine(e):\n    return e["b"]\n', "x.py") == []


class TestTheVocabularyReaderRefusesTheWrongField:
    """The half a source scan cannot do, asserted on the function itself.

    `TestOneReaderPerAmbiguousSubfield` used to claim this and could not deliver
    it. `metadata._subject_vocabulary` takes the tag, so the check runs on every
    call and no spelling gets past it.
    """

    ENTRY = metadata._Subfields((("a", "Ancient history"), ("2", "21")))

    def test_a_subject_tag_is_read(self):
        assert metadata._subject_vocabulary("650", self.ENTRY) == "21"

    def test_a_dewey_field_raises_rather_than_answering(self):
        """`082 $2` is the Dewey edition. This is the call the old docstring
        described as impossible while nothing stopped it."""
        with pytest.raises(ValueError, match="082"):
            metadata._subject_vocabulary("082", self.ENTRY)

    def test_every_subject_tag_this_app_reads_is_accepted(self):
        """Membership is `_DNB_SUBJECT_TAGS` rather than a second list, so a tag
        added there is admitted here in the same edit. Asserted over the whole
        tuple, so a divergence cannot hide in the one tag nobody tried."""
        for tag in metadata._DNB_SUBJECT_TAGS:
            assert metadata._subject_vocabulary(tag, self.ENTRY) == "21", tag

    def test_the_two_other_callers_pass_a_tag_this_accepts(self):
        """`_k10plus_record` and `marc._extra_headings` both pass `650` as a
        literal. If that stops being a member, both raise on every record, and
        this says so at the rule rather than in a traceback."""
        assert "650" in metadata._DNB_SUBJECT_TAGS


class TestEveryPythonFileCompilesWithoutAWarning:
    r"""A `SyntaxWarning` is a `SyntaxError` on a schedule, and nothing was reading one.

    CPython has an invalid escape sequence scheduled to become a `SyntaxError`.
    Until then a bare `\d` in a non raw string was a warning nobody saw:
    `pyproject.toml` configured no `filterwarnings` and the suite stayed green.
    When it lands the file stops importing. **The blast radius is this file**,
    which carries the shelf guard, the source order guard and the digit rule, so
    one escape in one docstring here retires every house rule at once, and
    `backend/tests/` is published to the mirror.

    **The tests and the migrations are in scope, and that is the whole scope
    question.** This rule is about a file loading at all, and that failure does
    not care which walk returned it. The defect that bought the test was a `\d`
    in a **docstring in this file**, which `_python_sources()` does not return,
    so a guard scoped to it could not have caught its own subject.
    `_every_python_file` states the rest of the reasoning.

    **Recorded, not raised, and the difference is not cosmetic.**
    `simplefilter("error", SyntaxWarning)` never surfaces a `SyntaxWarning`: the
    compiler converts it and raises `SyntaxError` instead, so `except
    SyntaxWarning` catches nothing, and compilation stops at the **first**
    warning in the file. Recording reports all of them, so one fix round clears
    a file rather than peeling it, and
    `test_two_warnings_in_one_file_are_both_reported` is what holds that rather
    than the sentence: the same fixture reports 2 recorded against 1 raised. The
    `except SyntaxError` arm is for a file that does not parse at all, which is
    the state this rule anticipates, and it also carries `IndentationError` and
    `TabError`, each with a fixture below asserting the category and not only
    the line, because `type(...)` is what names a subclass and a literal would
    not. **A null byte in the source is the
    one offence that names no line**, because CPython raises that `SyntaxError`
    with `lineno` unset, and it is reported as `None` rather than dropped.

    **`ruff` is the fast path and this is the backstop.** `W605` reports an
    invalid escape with a column and an autofix, in a CI job that runs before
    the suite, and `pyproject.toml` selects it for exactly that. It does not
    make this redundant, and the reason is a shape rather than an overlap:
    ruff's `select` is an enumeration, so it covers the compile time warnings
    somebody has written a rule for, today `W605`, `F631`, `F632` and `B012`,
    and no others. This asks the compiler, so a category CPython adds next
    release is caught the day the interpreter moves, with no rule to select and
    no ruff release to wait for.

    **Not a `filterwarnings` line in `pyproject.toml`, because import time
    cannot see this.** Measured 2026-09-02: importing a module holding a bare
    `\d` warns once and is **silent** on every import afterwards, because the
    second one loads a `.pyc` and never compiles the source. An ini setting
    therefore passes or fails on whether a `__pycache__` happens to exist, which
    is the environment deciding the verdict rather than the tree. Compiling the
    source explicitly has no such hole, and it is also the only form that can
    report a file nothing imports.

    **The corpus is stated as an exclusion and never as a total.** It is every
    file under `backend/` whose suffix is `.py` and whose path no tool owns:
    tests and migrations included, bytecode and a tool's own directory out.
    `test_the_walk_reaches_every_group_and_leaves_no_remainder` recomputes that
    from the walks rather than checking it against a number.

    **A total here is a number that stops being re-derived and starts being
    copied.** The one that stood in this docstring was measured once, was stale
    by thirty when somebody counted again, and never failed: the arm walks
    whatever the walk returns, so a count that has drifted low is a weaker claim
    about a wider walk. It had been spelled three times by then, twice worded to
    agree with the first by construction.

    This docstring is raw for the reason it exists.
    """

    def _offences(self, paths: list[Path]) -> list[str]:
        # `paths` is required, where the scanners above default it to their own
        # walk. A default here would be a scope no test can see: every file in
        # this tree compiles clean, so narrowing the walk changes no verdict.
        # Naming the list at the call site is what lets the test assert it.
        found: list[str] = []
        for path in paths:
            failure: SyntaxError | None = None
            # Read outside the block below, so that block holds one statement and
            # every warning it records belongs to the file being compiled. This
            # is not fastidiousness: the filter is set to every category, so an
            # `open(path).read()` in there attributes its own `ResourceWarning`
            # to every file in the walk. Measured while checking something else.
            #
            # Bytes, not `read_text()`. `compile` applies PEP 263, so a coding
            # cookie is honoured and the locale is never consulted. `read_text()`
            # decodes with the locale encoding and raises `UnicodeDecodeError` on
            # a file that compiles perfectly well, which is this guard failing on
            # itself.
            source = path.read_bytes()
            with warnings.catch_warnings(record=True) as caught:
                # Every category, not `SyntaxWarning` alone, because a list of
                # categories is an open set that goes stale silently. **Stated,
                # not tested**: 3.14 has no compile time warning outside
                # `SyntaxWarning` to pin it with, so narrowing this to
                # `("always", SyntaxWarning)` passes the whole file today. The
                # rung is the reason it is written down rather than assumed.
                # `"default"` is likewise indistinguishable here, measured over
                # three shapes: two warnings on two lines, the same warning twice
                # on one line, and one warning in each of two files, all reported
                # identically under both. Only `"once"` collapses them. So the
                # word is the intent rather than a load bearing choice.
                warnings.simplefilter("always")
                try:
                    compile(source, str(path), "exec")
                except SyntaxError as exc:
                    failure = exc
            found += [
                f"{_label(path)}:{entry.lineno}: {entry.category.__name__}: {entry.message}"
                for entry in caught
            ]
            if failure is not None:
                # `type(...)` rather than a literal, so a subclass names itself.
                found.append(
                    f"{_label(path)}:{failure.lineno}: {type(failure).__name__}: {failure.msg}"
                )
        return found

    def test_every_python_file_under_backend_compiles_clean(self) -> None:
        walked = _every_python_file()
        # Not a duplicate of the reach test below, which says the walk is wide.
        # These two say **this run** used the wide one. Narrowing the line above
        # to `_python_sources()` passes on a clean tree while silently dropping
        # the tests and the migrations, which is the scope the rule turns on.
        assert any("migrations" in path.parts for path in walked)
        assert any(path.name == "test_house_rules.py" for path in walked)
        offences = self._offences(walked)
        assert not offences, (
            "These warn at compile time, and CPython has this class of warning "
            "scheduled to become a SyntaxError, at which point the file stops "
            "importing:\n  " + "\n  ".join(offences)
        )

    def test_the_walk_reaches_every_group_and_leaves_no_remainder(self) -> None:
        """Vacuity, plus the one hole the two narrower walks have between them.

        `_python_sources` drops any path with `tests` among its parts and
        `_test_sources` only descends `backend/tests`, so a file at
        `backend/routers/tests/x.py` would be in neither. There is none today,
        and the equality below is what would say so.

        **The migrations are walked independently of the walk under test**, not
        sieved out of it. Sieving is what the first draft of this line did, and
        it made the claim circular: `_every_python_file` narrowed to drop
        `migrations/` would have emptied both sides at once and passed.
        """
        walked = set(_every_python_file())
        assert set(_python_sources()) <= walked
        assert set(_test_sources()) <= walked
        migrations = {
            path
            for path in (BACKEND / "migrations").rglob("*.py")
            if not _is_vendored(path)
        }
        assert migrations, "the migrations are why this walk is wider than the two above"
        assert walked == set(_python_sources()) | set(_test_sources()) | migrations

        # **The exclusion, derived, where a total used to stand.** Everything
        # under `backend/` that this walk leaves out is a tool's own (pruned by
        # `_is_vendored` in both instruments) or is not a `.py` file, which for
        # this corpus means bytecode, a lock file or a template. Stated as the
        # complement rather than as a count, because a count is what goes stale
        # without ever failing: the walk is whatever it returns, so a low number
        # beside it is a weaker claim about a wider walk and stays green.
        left_out = set(_every_file_a_tool_does_not_own()) - walked
        missed = sorted(path for path in left_out if path.suffix == ".py")
        assert not missed, (
            "These are Python files under backend/ that no tool owns and that "
            f"the walk did not return: {missed}. The corpus is every one of "
            "them, and a walk that returns fewer says so nowhere else."
        )
        # Anti vacuity for the line above, which passes over an empty
        # complement. There is always something under `backend/` that is not a
        # `.py` file, so a `left_out` that has gone empty is the second walk
        # failing rather than the tree being tidy.
        assert left_out, "the second walk returned nothing the first did not"

        # Vacuity, because every assertion above holds over an empty tree. Each
        # group non empty, plus the file making the assertion, rather than a
        # floor: a literal count here is the defect this class's docstring
        # records, and one that has drifted low never fails.
        assert set(_python_sources()) and set(_test_sources())
        assert Path(__file__).resolve() in {path.resolve() for path in walked}

    @pytest.mark.parametrize(
        ("shape", "source", "line", "category"),
        [
            ("a bare escape in a plain string", 'PATTERN = "\\d+"\n', 1, "SyntaxWarning"),
            (
                "a bare escape in a docstring, the shape that bought this",
                '"""Matches \\d."""\n',
                1,
                "SyntaxWarning",
            ),
            ("a bare escape in an f-string", 'x = 1\ny = f"{x}\\d"\n', 2, "SyntaxWarning"),
            ("a bare escape in a bytes literal", 'PATTERN = b"\\d+"\n', 1, "SyntaxWarning"),
            (
                "an assert on a tuple, always true",
                'def f(x):\n    assert (x, "x is unset")\n',
                2,
                "SyntaxWarning",
            ),
            (
                "identity against a literal",
                'def f(x):\n    return x is "book"\n',
                2,
                "SyntaxWarning",
            ),
            ("a file that does not parse at all", "def f(:\n", 1, "SyntaxError"),
            ("an indentation error", "def f():\nreturn 1\n", 2, "IndentationError"),
            (
                "a tab where the block used spaces",
                "def f():\n    if 1:\n        pass\n\tpass\n",
                4,
                "TabError",
            ),
        ],
    )
    def test_the_rule_sees_every_way_of_getting_it_wrong(
        self, tmp_path: Path, shape: str, source: str, line: int, category: str
    ) -> None:
        """One shape per case, so a shape that stops being reported names itself.

        **The report is read, not merely counted.** The rule this satisfies is
        that it fails naming the file and the line, and asserting `!= []` leaves
        that at the stated rung: replacing both f-strings in `_offences` with one
        fixed sentence passed the whole file.

        **The category is asserted too, and stopping before it was this test's
        own first draft.** `IndentationError` and `TabError` are subclasses that
        `type(...)` names and a `"SyntaxError"` literal would not, and the same
        field carries `SyntaxWarning` for the recorded half. Asserting through
        `f"...{line}: "` and no further left both spellings free: hard coding the
        literal, and dropping the category from the warning report, each passed
        the whole file.
        """
        fixture = tmp_path / "offender.py"
        fixture.write_text(source)
        offences = self._offences([fixture])
        assert len(offences) == 1, f"{shape} gave {offences}"
        assert offences[0].startswith(f"offender.py:{line}: {category}: "), (
            f"{shape} gave {offences[0]}"
        )

    @pytest.mark.parametrize(
        ("shape", "source"),
        [
            ("a raw string", 'PATTERN = r"\\d+"\n'),
            ("a raw docstring, which is how this tree fixes it", 'r"""Matches \\d."""\n'),
            ("a doubled backslash", 'PATTERN = "\\\\d+"\n'),
            ("a valid escape", 'X = "a\\nb"\n'),
            ("a tuple compared rather than asserted", "def f(x, y, z):\n    assert (x, y) == z\n"),
            ("equality against a literal", 'def f(x):\n    return x == "book"\n'),
        ],
    )
    def test_the_rule_leaves_the_correct_shape_alone(
        self, tmp_path: Path, shape: str, source: str
    ) -> None:
        """The other half of the diagonal: it must not report everything. A rule
        that grepped for a backslash would pass the cases above and fail here."""
        fixture = tmp_path / "innocent.py"
        fixture.write_text(source)
        assert self._offences([fixture]) == [], f"{shape} is reported and should not be"

    def test_two_warnings_in_one_file_are_both_reported(self, tmp_path: Path) -> None:
        """What recording buys over raising, which no single warning fixture can
        show. Under `simplefilter("error", SyntaxWarning)` this same file reports
        one offence and stops, because the compiler raises at the first."""
        fixture = tmp_path / "offender.py"
        fixture.write_text('P = "\\d"\nQ = "\\p"\n')
        offences = self._offences([fixture])
        assert len(offences) == 2, offences
        assert offences[0].startswith("offender.py:1: SyntaxWarning: ")
        assert offences[1].startswith("offender.py:2: SyntaxWarning: ")

    def test_a_null_byte_is_reported_with_no_line_rather_than_dropped(
        self, tmp_path: Path
    ) -> None:
        """The one offence that names no line, pinned so the docstring's
        exception stays true. CPython raises this `SyntaxError` with `lineno`
        unset, and `None` in the report is better than a file nobody checked."""
        fixture = tmp_path / "offender.py"
        fixture.write_bytes(b"X = 1\x00\n")
        offences = self._offences([fixture])
        assert len(offences) == 1, offences
        # The message text is CPython's and `requires-python` is `>=3.14`, so the
        # claim pinned here is the `None`, not the wording.
        assert offences[0].startswith("offender.py:None: SyntaxError: "), offences[0]

    def test_a_file_is_read_as_bytes_rather_than_through_the_locale(self, tmp_path: Path) -> None:
        """Why `read_bytes` is not decoration. `compile` honours the coding
        cookie; `read_text` decodes with the locale encoding first and would
        raise on this file, reporting a failure that is not one."""
        fixture = tmp_path / "cookie.py"
        fixture.write_bytes(b"# -*- coding: latin-1 -*-\nAUTHOR = '\xe9mile'\n")
        assert self._offences([fixture]) == []
        with pytest.raises(UnicodeDecodeError):
            fixture.read_text(encoding="utf-8")


#: The patterns in `.gitignore`, each with whether it is anchored to the root.
#:
#: **This file is the repository's own statement of what is not source**, it is
#: what `git` itself consults, and it is versioned, so a rule derived from it
#: moves when the repository does. That is the property a list of directory
#: names beside a walk cannot have.
#:
#: **Asking `git` would be better and is not available.** Measured 2026-09-06 in
#: the pod the suites actually run in: no `git` binary, and no `.git`, because
#: the runner ships a tar that excludes it. A rule calling `git ls-files` there
#: is a rule that fails or, worse, quietly answers nothing.
#:
#: **A pattern this cannot evaluate exactly raises, rather than being
#: approximated in either direction.** Approximating it wide drops a versioned
#: file from the walk, which is the defect the walk exists to stop. Approximating
#: it narrow walks a directory the repository ignores, which is how the publish
#: tooling's own output came to be read as source. So the refusal is a class and
#: not a list of forms: anything the two arms below cannot decide, which today
#: means a negation, a `**`, and a wildcard in an anchored pattern, because that
#: arm compares text rather than matching.
def _ignore_patterns(root: Path) -> list[tuple[str, bool]]:
    ignore_file = root / ".gitignore"
    assert ignore_file.is_file(), f"no .gitignore at {root}, so the walk has no rule"
    patterns: list[tuple[str, bool]] = []
    for line in ignore_file.read_text(encoding="utf-8").splitlines():
        entry = line.strip()
        if not entry or entry.startswith("#"):
            continue
        # A pattern with a slash left in it after the markers come off is
        # anchored to the root, which is git's own rule and the difference
        # between `backend/data/` meaning that one directory and meaning any
        # `data` anywhere.
        anchored = entry.startswith("/")
        entry = entry.strip("/")
        anchored = anchored or "/" in entry
        # The anchored arm compares text rather than matching, so a wildcard
        # there would read as "never matches" instead of raising. Refused as a
        # class, by the characters, rather than as two more names beside `!` and
        # `**`: naming forms one at a time is the shape this whole walk replaced.
        assert "!" not in entry and "**" not in entry and not (
            anchored and set(entry) & set("*?[")
        ), f"unsupported .gitignore form, teach this walk about it: {entry}"
        patterns.append((entry, anchored))
    return patterns


def _is_ignored(relative: Path, patterns: list[tuple[str, bool]]) -> bool:
    text = str(relative)
    return any(
        (text == pattern or text.startswith(f"{pattern}/"))
        if anchored
        else any(fnmatch(part, pattern) for part in relative.parts)
        for pattern, anchored in patterns
    )


#: Every Markdown file this repository versions.
#:
#: **An exclusion, because the inclusion it replaces went stale.** This globbed
#: the repository root and `docs/*.md`, which reached **14** of the **18** files
#: the publish gate publishes: measured 2026-09-06, `conformance/README.md` and
#: three files under the two test trees sat outside it, and a document added in a
#: directory nobody had thought of would have sat outside it too. A walk cannot
#: be kept in step with a tree by remembering to edit it.
#:
#: **Then it went stale a second way, and a name list is what did it.** The
#: replacement pruned a leading dot plus two names, which does not reach the
#: publish tooling's output directory. Measured 2026-09-06 on a checkout where
#: the gate had been run: **36** published files rather than 18, the extra 18
#: being the first 18 one directory down, walked as though a build output were
#: source. Adding that name would have been the third arm of the same list.
#:
#: **So the rule is what the repository versions**: not hidden, and not ignored.
#: The gate exports a committed ref, so an ignored file cannot be published by
#: construction, and the build output, the dependency trees, the caches, the
#: wave plan and the wave's working notes all fall out at once. The leading dot
#: stays beside it because `.gitignore` does not mention every hidden directory:
#: `.claude/` is not in it and carries a worktree per agent.
#:
#: **A wave's own drafts leave the walk with it, and that is the trade taken.**
#: An earlier version argued for keeping them, on the ground that a draft is what
#: a fold reads. Giving them up is safe because a fold's destinations are
#: versioned and still read here, so the fence that reaches a reader is still
#: counted; what is lost is catching it one step earlier, in the draft.
#:
#: **Wider than what is published, deliberately.** An unbalanced fence renders
#: everything after it as one code block for whoever opens the file next, and
#: that is the defect whether the reader came from the mirror or from this
#: checkout.
#:
#: **Pruned while walking rather than filtered afterwards**, so a directory that
#: is out of scope is never descended.
#:
#: `root` is a parameter so the mechanism can be driven over a fixture tree
#: rather than only over this one.
def _markdown_sources(root: Path | None = None) -> list[Path]:
    root = BACKEND.parent if root is None else root
    patterns = _ignore_patterns(root)
    found: list[Path] = []
    for directory, subdirectories, files in os.walk(root):
        here = Path(directory)
        subdirectories[:] = [
            name
            for name in subdirectories
            if not name.startswith(".")
            and not _is_ignored((here / name).relative_to(root), patterns)
        ]
        found += [
            here / name
            for name in files
            if name.endswith(".md")
            and not _is_ignored((here / name).relative_to(root), patterns)
        ]
    return sorted(found)


def _fence_lines(text: str) -> list[int]:
    """Line numbers of every fence, indented by up to three spaces as CommonMark
    allows. Counting only column zero reports a false odd on a fence inside a
    list."""
    fences = []
    for n, line in enumerate(text.splitlines(), start=1):
        body = line.lstrip(" ")
        # Four spaces is an indented code block, so the backticks there are
        # content. `line[:4].lstrip()` looks equivalent and is not: at an indent
        # of three it leaves one backtick and matches nothing.
        if len(line) - len(body) <= 3 and body.startswith("```"):
            fences.append(n)
    return fences


class TestEveryMarkdownFileHasBalancedCodeFences:
    """An odd number of fences renders everything after the last one as code.

    Two published registers carried one on 2026-09-03, both left by a previous
    wave folding a working draft in with its own scaffolding: `CHANGELOG.md`
    swallowed everything below its third entry, and `docs/decisions.md`
    everything below a `$2` decision, along with 42 lines of draft instructions
    addressed to a main session. Nothing failed. The register that records how
    this project makes decisions was unreadable on GitHub and the suite was
    green, because no test read a Markdown file for its shape.

    Parity is the whole check and it is deliberately not a parser. What it
    cannot see is a fence closed in the wrong place, which renders wrongly with
    an even count; what it catches is the one a fold leaves behind.
    """

    def test_no_markdown_file_has_an_odd_number_of_fences(self) -> None:
        repo = BACKEND.parent
        counts = {
            str(path.relative_to(repo)): len(_fence_lines(path.read_text(encoding="utf-8")))
            for path in _markdown_sources()
        }
        odd = {name: n for name, n in counts.items() if n % 2}
        assert odd == {}, f"{odd}, of {len(counts)} files walked"

    def test_the_walk_never_narrows_below_the_globs_it_replaced(self) -> None:
        """Anti vacuity, as a ratchet. A walk that returned nothing would pass
        the rule above in silence, which is the shape this repository calls an
        instrument that cannot see the failure reporting its absence, and the
        way this rule was weakest was a walk narrower than the tree rather than
        an empty one. So the floor is the two globs this replaced: whatever else
        changes, the root documents and `docs/*.md` are still read.

        The two registers are named as well because they are the files a fold
        writes into, which is where the defect that bought this rule came from.

        **The floor is the old globs minus what the repository ignores**, and
        leaving that out made this test green only while a checkout happened to
        hold no ignored root document. The wave plan and the technology
        evaluation beside it are both root Markdown, so they sat inside the old
        globs and are deliberately outside the walk now: on a checkout carrying
        either, this failed while nothing was wrong.
        """
        repo = BACKEND.parent
        patterns = _ignore_patterns(repo)
        walked = {path.relative_to(repo) for path in _markdown_sources()}
        replaced = {
            path.relative_to(repo)
            for path in [*repo.glob("*.md"), *repo.glob("docs/*.md")]
            if not _is_ignored(path.relative_to(repo), patterns)
        }
        assert replaced <= walked, sorted(str(p) for p in replaced - walked)
        assert Path("CHANGELOG.md") in walked
        assert Path("docs/decisions.md") in walked

    def test_a_file_the_repository_does_not_version_is_not_walked(
        self, tmp_path: Path
    ) -> None:
        """The gate exports a committed ref, so an ignored file cannot be
        published and has no business in a rule about published documents.

        The case that bought this is the gate's own output directory. It is a
        copy of the tree one level down, so walking it reads this rule's own
        subjects a second time, and once the copy is stale it reads content that
        no longer exists anywhere. Measured 2026-09-06 on a checkout where the
        gate had been run: 36 published files rather than 18.
        """
        # `notes/` rather than the real name of the wave's scratch directory,
        # which is on the publish gate's strip list. This file is published, and
        # a published file may not point at a stripped path: the literal passes
        # today only because the escape before it sits inside the gate's own
        # character class, which one reformat would undo.
        (tmp_path / ".gitignore").write_text(
            "/public/\nnotes/\nnode_modules/\nscratch.md\n"
        )
        (tmp_path / "docs").mkdir()
        (tmp_path / "docs" / "real.md").write_text("# real\n")
        (tmp_path / "public" / "docs").mkdir(parents=True)
        (tmp_path / "public" / "docs" / "real.md").write_text("# a copy of the above\n")
        (tmp_path / "notes").mkdir()
        (tmp_path / "notes" / "note.md").write_text("# a working note\n")
        (tmp_path / "node_modules" / "left-pad").mkdir(parents=True)
        (tmp_path / "node_modules" / "left-pad" / "README.md").write_text("# theirs\n")
        # `docs/scratch.md` is the case the directory prune cannot reach. Every
        # other file here is refused by pruning a directory, or by a pattern that
        # is the whole of its own path, so an unanchored match narrowed to whole
        # text equality lets them all through unchanged: measured, that mutation
        # was invisible to the entire suite. This one is ignored because an
        # unanchored pattern matches a name at any depth, which is git's rule and
        # the only thing the segment walk in `_is_ignored` buys.
        (tmp_path / "docs" / "scratch.md").write_text("# deeper than the pattern\n")
        walked = {str(path.relative_to(tmp_path)) for path in _markdown_sources(tmp_path)}
        assert walked == {"docs/real.md"}

    def test_a_hidden_directory_is_not_walked_even_where_the_ignore_file_is_silent(
        self, tmp_path: Path
    ) -> None:
        """Why the leading dot rule stays beside the ignore rule. `.claude/`
        carries a worktree per agent and is not in `.gitignore`, so the ignore
        rule alone would walk every other agent's copy of this tree."""
        (tmp_path / ".gitignore").write_text("\n")
        (tmp_path / ".claude" / "worktrees" / "other").mkdir(parents=True)
        (tmp_path / ".claude" / "worktrees" / "other" / "README.md").write_text("# x\n")
        (tmp_path / "README.md").write_text("# x\n")
        walked = {str(path.relative_to(tmp_path)) for path in _markdown_sources(tmp_path)}
        assert walked == {"README.md"}

    def test_an_ignore_form_this_cannot_honour_is_refused(self, tmp_path: Path) -> None:
        """Under-excluding walks something extra and says so; over-excluding
        drops a versioned file in silence. A negation is the form that would do
        the second, so it raises rather than being approximated."""
        (tmp_path / ".gitignore").write_text("docs/\n!docs/keep.md\n")
        with pytest.raises(AssertionError, match="unsupported .gitignore form"):
            _markdown_sources(tmp_path)

    def test_an_unbalanced_fence_is_reported(self, tmp_path: Path) -> None:
        fixture = tmp_path / "broken.md"
        fixture.write_text("# Title\n\n```\nsome code\n```\n\nprose\n```\n")
        assert len(_fence_lines(fixture.read_text(encoding="utf-8"))) == 3

    def test_a_balanced_pair_is_not_reported(self, tmp_path: Path) -> None:
        fixture = tmp_path / "fine.md"
        fixture.write_text("# Title\n\n```bash\nls\n```\n\nprose\n")
        assert len(_fence_lines(fixture.read_text(encoding="utf-8"))) == 2

    def test_a_fence_indented_inside_a_list_is_counted(self, tmp_path: Path) -> None:
        """Why the count tolerates indentation. At column zero only, this file
        reads as one fence and fails a rule it satisfies."""
        fixture = tmp_path / "listed.md"
        fixture.write_text("- item\n\n   ```\n   ls\n   ```\n\n```\nx\n```\n")
        assert len(_fence_lines(fixture.read_text(encoding="utf-8"))) == 4

    def test_four_spaces_is_an_indented_code_block_rather_than_a_fence(
        self, tmp_path: Path
    ) -> None:
        """The other edge of the same rule: at four spaces the backticks are
        content, so counting them would report a false odd."""
        fixture = tmp_path / "indented.md"
        fixture.write_text("prose\n\n    ```\n\n```\nx\n```\n")
        assert len(_fence_lines(fixture.read_text(encoding="utf-8"))) == 2


class TestAOneTimeCodeIsServedOnlyWhereItIsNamed:
    """A recovery code reaches the one response that exists to carry it.

    The same mechanism as `TestAnAddressIsServedOnlyWhereItIsNamed` and for a
    sharper reason: a code is a credential for the hour it lives, and it exists
    in plaintext exactly once, in the response to an approval. It is stored as a
    bcrypt hash, so no route **could** serve it a second time from the database;
    what this rule stops is a second response carrying it forward from the one
    that may, which no amount of hashing prevents.

    **Both schema modes**, because a request body naming a code is fine and a
    response naming one is not, and the two are told apart by which model it is
    rather than by which mode: `ResetRedeem` and `VerificationRedeem` take a code
    in and serve none back.

    The blind spots are the address rule's, unchanged, and stated there: a code
    served under a different property name, and a route with
    `response_model=None` returning a hand built dict. This adds one of its own:
    it says nothing about the **queue** response, which is checked by
    `tests/test_accounts.py::TestTheCodeIsNeverServedTwice` looking at the
    rendered body rather than at the schema.
    """

    #: The models allowed to carry a code, and what each is for.
    CODE_MODELS = {
        "ResetCodeOut": "the approval response, which is where a code exists once",
        "ResetRedeem": "the body that spends one",
        "VerificationRedeem": "the body that returns the mailed one",
    }

    CODE_FIELD = "code"

    def test_no_other_schema_carries_a_code(self) -> None:
        address_rule = TestAnAddressIsServedOnlyWhereItIsNamed()
        models = address_rule._our_models()
        assert models, "no models were found; this rule now inspects nothing"

        carriers: set[str] = set()
        unreadable: list[str] = []
        for name, model in models.items():
            try:
                schemas = [
                    model.model_json_schema(mode=mode)
                    for mode in ("validation", "serialization")
                ]
            except Exception as error:  # noqa: BLE001  (reported, never skipped)
                unreadable.append(f"{name}: {type(error).__name__}: {error}")
                continue
            if any(self._serves_a_code(schema) for schema in schemas):
                carriers.add(name)

        assert not unreadable, (
            "These models could not be asked what they put on the wire:\n  "
            + "\n  ".join(sorted(unreadable))
        )
        offenders = sorted(carriers - set(self.CODE_MODELS))
        assert not offenders, (
            "These put a one time code on the wire and are not one of the "
            f"schemas that may: {offenders}. A code is a credential and exists "
            "in plaintext once, in the approval response. Serve it from "
            + "; ".join(f"{name} ({why})" for name, why in self.CODE_MODELS.items())
            + " instead."
        )

    def _serves_a_code(self, schema: object) -> bool:
        """The address rule's walk, over the same flattened `$defs` document."""
        if isinstance(schema, dict):
            properties = schema.get("properties")
            if isinstance(properties, dict) and self.CODE_FIELD in properties:
                return True
            return any(self._serves_a_code(value) for value in schema.values())
        if isinstance(schema, list):
            return any(self._serves_a_code(item) for item in schema)
        return False


# ── Who may write a loan ──────────────────────────────────────────────────────


def _loans_only_columns() -> frozenset[str]:
    """The `loans` columns whose name belongs to no other table.

    **Derived from the metadata, and the exclusion is the whole of it.** The
    rule below reads attribute assignments, and an attribute name is all it has:
    `loan.returned_at = now` and `out.returned_at = now` are the same three
    tokens. So a column name shared with another table cannot be attributed to
    `loans` by name alone and is left out, which today drops `id` and `book_id`.

    Stating it the other way round, as a list of the seven that are unique,
    is what goes stale the day a second table grows a `due_at`: the rule would
    then report every write to that table as a loan.
    """
    loans = Base.metadata.tables["loans"]
    elsewhere = {
        column.name
        for table in Base.metadata.tables.values()
        if table.name != "loans"
        for column in table.columns
    }
    return frozenset({column.name for column in loans.columns} - elsewhere)


def _loan_names(tree: ast.Module) -> set[str]:
    """Every local name in one module that means `models.Loan`.

    `from models import Loan as L` and `Mk = Loan` both bind a name no rule
    looking for the literal `Loan` would ever ask about, and the second is the
    spelling `tests/test_shelf._entity_aliases` was written for after exactly
    that walked past it.

    **A second, smaller resolver rather than that one**, because this file is
    imported by that one for `_is_vendored` and importing back is a cycle under
    `--import-mode=importlib`. Smaller in one way that is stated rather than
    hidden: it does not follow `aliased(Loan)`, which is a query construct and
    builds no row. The `AnnAssign` form is followed, because the annotated
    binding is the more idiomatic half of this backend and a resolver reading
    only `Assign` would follow the less used spelling.
    """
    names = {"Loan"}
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module == "models":
            names |= {alias.asname or alias.name for alias in node.names if alias.name == "Loan"}
    # A second pass, because a rebinding may sit above or below the import.
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign | ast.AnnAssign):
            continue
        value = node.value
        if value is None:
            continue
        means_loan = (isinstance(value, ast.Name) and value.id in names) or (
            isinstance(value, ast.Attribute) and value.attr == "Loan"
        )
        names |= {
            target.id
            for target in _assignment_targets(node)
            if isinstance(target, ast.Name) and means_loan
        }
    return names


def _assignment_targets(node: ast.AST) -> list[ast.expr]:
    """What one statement assigns to, over all three assignment forms.

    One helper for both arms below. They read different forms once, so
    `loan.loaned_by_user_id: int = payload.issuer` was a write to one and
    invisible to the other, which is a disagreement about what a statement is
    rather than about what the rule says.
    """
    if isinstance(node, ast.Assign):
        return list(node.targets)
    if isinstance(node, ast.AugAssign | ast.AnnAssign):
        return [node.target]
    return []


def _names_the_model(call: ast.expr, local_names: set[str]) -> bool:
    """Whether this callee is one of the module's names for `Loan`."""
    return (isinstance(call, ast.Name) and call.id in local_names) or (
        isinstance(call, ast.Attribute) and call.attr == "Loan"
    )


def _loan_writes(source: str) -> list[tuple[str, str]]:
    """Every statement in one module that writes a loan, as `(kind, statement)`.

    Three shapes, and each is deliberately blunt about its receiver, for the
    reason `test_shelf._outbound_constructions` gives about `x.Outbound(...)`: a
    false report costs a person one look and a missed one costs the rule. So
    `self.loaned_to_name = ...` on a Pydantic model is reported like any other,
    and the table below carries the reason it is there.

    **The class is resolved rather than spelled**, by `_loan_names` above, so an
    import alias and a rebinding are read. The third shape reads the **columns**
    instead of the class, which are derived from the schema: a call carrying a
    keyword argument named after a column only `loans` has is building a loan
    row whatever it calls the class. That is what catches a Core insert, and it
    is what would catch a construction through a value this resolver cannot
    trace.
    """
    tree = ast.parse(source)
    columns = _loans_only_columns()
    local_names = _loan_names(tree)
    found: list[tuple[str, str]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            if _names_the_model(node.func, local_names):
                found.append(("constructs a Loan", ast.unparse(node)))
            if any(keyword.arg in columns for keyword in node.keywords):
                found.append(("builds a row shaped like a loan", ast.unparse(node)))
        for target in _assignment_targets(node):
            if isinstance(target, ast.Attribute) and target.attr in columns:
                found.append((f"writes loans.{target.attr}", ast.unparse(node)))
    return found


def _issuers(source: str) -> list[str]:
    """What every write of `loans.loaned_by_user_id` binds it to, as source.

    A construction that leaves it out reports `<omitted>`: the column is
    `nullable=False`, so an omission is a 500 rather than a loan, and a rule
    that read only what was written would have nothing to report about it.
    """
    tree = ast.parse(source)
    local_names = _loan_names(tree)
    found: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and _names_the_model(node.func, local_names):
            # The model, and not every call carrying the column, which is what
            # `_loan_writes` reads. A response model names the issuer to
            # **render** it (`LoanOut(loaned_by_user_id=loan.loaned_by_user_id)`),
            # and reading that as a write would put a read into a set this arm
            # pins to one expression.
            bound = [
                keyword.value
                for keyword in node.keywords
                if keyword.arg == "loaned_by_user_id"
            ]
            found += [ast.unparse(value) for value in bound] or ["<omitted>"]
        if isinstance(node, ast.Assign | ast.AugAssign | ast.AnnAssign):
            value = node.value
            found += [
                ast.unparse(value)
                for target in _assignment_targets(node)
                if value is not None
                and isinstance(target, ast.Attribute)
                and target.attr == "loaned_by_user_id"
            ]
    return found


class TestOneInstanceIssuesALoan:
    """Authority follows the physical object: the instance holding a copy is the
    only one that may issue a loan of it.

    **Why a rule rather than a comment.** `uq_loans_one_open_per_book` is a
    cross row invariant, so two writers of the same loan is not a conflict that
    a merge rule fixes: it is a book out with two people at once. With one
    authority per object there is no consensus to reach, no reconciliation and
    no window in which two instances both issue. A loan written by a non owning
    instance is what a peer, an importer or a mobile client adds without
    noticing, which is why this is a test and not a sentence.

    **What is testable today, said plainly, because the rest is not.** There is
    one instance, so "the owning instance issued it" reduces to two claims a
    rule can check: that the issuer of every loan is a member this instance
    resolved from a session, never a value that arrived in a payload; and that
    the set of places writing the table is a set somebody argued. The transport
    that would carry a loan between instances does not exist, so nothing here
    checks a wire.

    **What this cannot see:**

    * **A write that names no column and calls no class.** `setattr(loan,
      field, value)`, a Core `table.insert()` over rows read from somewhere, and
      `db.execute(text("UPDATE loans SET ..."))` all evade both arms, from any
      module. `backup.restore` is the live one and is the tree's named third way
      past a viewer, but the shape is an idiom rather than that file's quirk:
      `main.py` already writes a model through a `setattr` loop. A rule that saw
      these would watch the session at run time rather than read source.
    * **The migrations**, which `_source_modules()` does not return. One
      revision already closes every open loan but the earliest per book with an
      `UPDATE`, clearing the way for `uq_loans_one_open_per_book` rather than
      ending anybody's loan, and a revision is a record of what was applied
      rather than a place authority is decided.
    * **A second statement of a kind already argued, in a module already
      argued.** The table below is keyed on module and kind, so a new column
      written in a module, or any write in a new module, is a new key; a second
      `loan.returned_at = now` beside the first is not. The issuer arm is what
      covers the case that matters, since a write taking its authority from
      input changes what is bound rather than where.
    """

    #: Every place in the tree that writes a loan, and the authority it carries.
    #:
    #: **Asserted by equality, never as a subset**, so a writer that appears is
    #: a decision rather than an edit. A subset check forgives exactly the
    #: change this table exists to catch.
    WRITES_A_LOAN: Final = {
        "routers/loans.py: constructs a Loan": (
            "the lending desk: a member of this instance lends a book this "
            "instance holds, and is the issuer by being the caller"
        ),
        "routers/loans.py: builds a row shaped like a loan": (
            "the same statement, seen by the arm that reads columns rather "
            "than the class name. Both keys, deliberately: a construction that "
            "loses the name is still a loan"
        ),
        "serialisation.py: builds a row shaped like a loan": (
            "not a write at all: `LoanOut`, which renders a loan and shares "
            "its column names. Left reported rather than exempted, because an "
            "exemption for a module is what a real write would then arrive "
            "under"
        ),
        "routers/loans.py: writes loans.returned_at": (
            "the same desk closing the loan it issued"
        ),
        "routers/books.py: writes loans.returned_at": (
            "merging two records and trashing one both close an open loan, "
            "because the book they were about stops existing as that row"
        ),
        "notifications.py: writes loans.notified_at": (
            "when a reminder last went out, which is delivery state rather "
            "than the loan: it says nothing about who has the book or when it "
            "is due, and it is stamped only after a send that succeeded"
        ),
        "schemas/loan.py: writes loans.loaned_to_name": (
            "not the table at all: the request model normalising a blank name "
            "to null before it can be stored. Reported because this rule reads "
            "an attribute name and cannot see a receiver's type, and left here "
            "rather than exempted because it is the one write that decides "
            "what a borrower's name is"
        ),
    }

    def test_the_places_that_write_a_loan_are_the_argued_ones(self):
        found = {
            f"{name}: {kind}"
            for name, source in _source_modules().items()
            for kind, _ in _loan_writes(source)
        }
        assert found == set(self.WRITES_A_LOAN), (
            f"Added: {sorted(found - set(self.WRITES_A_LOAN))}. Gone: "
            f"{sorted(set(self.WRITES_A_LOAN) - found)}. A loan is issued by "
            "the instance holding the book, so every place that writes one "
            "carries an argument about whose authority it is acting on. Add "
            "the line, or route the write through the desk in "
            "`routers/loans.py`."
        )

    def test_the_issuer_of_a_loan_is_always_this_instances_caller(self):
        """The arm that survives a second store existing.

        `loaned_by_user_id` is the claim "this instance lent this book". A
        writer that takes it from its input is asserting somebody else's
        authority, which is exactly what a sync handler, an importer or a
        client outbox does by default. Nothing about the shape of such a
        feature makes it look wrong at review; this is what makes it red.
        """
        found = {
            source_of
            for _, source in _source_modules().items()
            for source_of in _issuers(source)
        }
        assert found == {"current_user.id"}, (
            f"These decide who lent a book: {sorted(found)}. Only the member "
            "this instance resolved from the session may be the issuer: a "
            "value from a payload is another instance's authority, and "
            "`uq_loans_one_open_per_book` is a cross row invariant that no "
            "merge rule repairs."
        )

    def test_there_are_writes_to_classify(self):
        """Anti vacuity. Both equalities above are satisfied by a resolver that
        finds nothing, which is what a rename of the model would produce."""
        found = [
            (name, kind)
            for name, source in _source_modules().items()
            for kind, _ in _loan_writes(source)
        ]
        assert len(found) >= 5
        assert {name for name, _ in found} >= {"routers/loans.py"}

    @pytest.mark.parametrize(
        "spelling",
        [
            "from models import Loan\nLoan(loaned_by_user_id=1)\n",
            "from models import Loan as L\nL(loaned_by_user_id=1)\n",
            "import models\nmodels.Loan(loaned_by_user_id=1)\n",
            "from models import Loan\nMk = Loan\nMk(loaned_by_user_id=1)\n",
            "from models import Loan\nMk: type = Loan\nMk(loaned_by_user_id=1)\n",
            "rows.insert().values(loaned_to_name='Ada')\n",
            "loan.returned_at = now\n",
            "loan.notified_at: datetime = now\n",
        ],
        ids=[
            "imported",
            "aliased",
            "attribute",
            "rebound",
            "rebound annotated",
            "a core insert naming no class",
            "an assignment",
            "an annotated assignment",
        ],
    )
    def test_a_loan_written_under_any_of_these_names_is_still_a_write(self, spelling):
        """The diagonal, one mutation each.

        A sample carrying two spellings passes with either arm deleted and never
        says which arm caught it. The last three are the reason the rule reads
        columns as well as the class: none of them names `Loan` anywhere.
        """
        assert _loan_writes(spelling) != []

    def test_something_that_is_not_a_loan_is_not_reported(self):
        """The other side of the diagonal. A rule that reported every call
        would be one somebody deletes, and the census is asserted by equality,
        so a false report is a failing build rather than a note."""
        assert _loan_writes("book.title = 'Dune'\nBook(title='Dune')\n") == []

    def test_the_columns_this_rule_reads_are_the_ones_only_loans_has(self):
        """The derivation, pinned where the rule cannot see it move.

        A column name arriving on a second table drops out of this set, and the
        rule then stops reading writes to it with nothing to say so. Asserted
        against the two halves rather than against a list of seven names.
        """
        columns = _loans_only_columns()
        loans = {column.name for column in Base.metadata.tables["loans"].columns}
        assert columns <= loans
        assert "loaned_by_user_id" in columns
        assert not columns & {"id", "book_id"}, (
            "A key is shared with every other table, so a rule reading "
            "attribute names cannot attribute one to `loans`."
        )

    def test_no_request_model_lets_a_caller_name_the_issuer(self):
        """The other door into the same defect, and it needs no new code to open.

        A schema field is how a sync payload or an import would carry an
        issuer, and it would reach the table through an ordinary
        `model_validate`. Derived by importing every module in `schemas/` and
        walking Pydantic's own subclass registry, so a model that is not
        exported from the package is read too.
        """
        for path in sorted((BACKEND / "schemas").glob("*.py")):
            if path.stem != "__init__":
                importlib.import_module(f"schemas.{path.stem}")

        seen: set[type[BaseModel]] = set()
        stack: list[type[BaseModel]] = [BaseModel]
        while stack:
            for subclass in stack.pop().__subclasses__():
                if subclass not in seen:
                    seen.add(subclass)
                    stack.append(subclass)
        declaring = {
            subclass.__name__
            for subclass in seen
            if subclass.__module__.startswith("schemas")
            and "loaned_by_user_id" in subclass.model_fields
        }
        assert declaring == {"LoanOut"}, (
            f"{sorted(declaring)} declare who issued a loan. `LoanOut` is a "
            "response and may say so; a model a caller can send is a way to "
            "claim another instance's authority for a row this one writes."
        )


class TestEverySchemeCheckListsItsOwnEnum:
    """A `ck_*_scheme` constraint names exactly the enum its column is typed as.

    **Written because widening `models._scheme_check` took the last thing that
    checked its argument, and nothing replaced it.** That helper used to be
    annotated `type[AuthorityScheme]`, so handing it the wrong enum was a mypy
    error; a second table needed it and the signature became `type[StrEnum]`,
    which accepts every enum in the tree. Measured by the design seat on
    2026-09-11: calling it with `AuthorityScheme` from `BookIdentifier`'s own
    `__table_args__` left mypy green and `tests/test_schema.py`,
    `tests/test_identifiers.py` and `tests/routers/test_books_identifiers.py`
    at **210 passed**.

    **The model's constraint is inert and that is exactly why this is needed.**
    `main.py` boots through `upgrade_to_head()` and the suite inherits that
    schema, so a `CheckConstraint` in `models.py` is a description of a
    revision rather than a second enforcement of it. The migration is what
    installs the DDL and `test_schema.py` is what asks the migrated database
    whether each member is storable, so nothing at all was reading the model
    side. A wrong enum here therefore fails no test and misleads every reader.

    **Both halves are derived, and the first version only got one of them
    right.** The enum is read off `Mapped[...]` on the mapped class, so a third
    table with a scheme constraint is paired without anybody remembering this
    test. Which constraints are read was a **naming convention** until the
    security seat renamed one and watched it leave the rule in silence, so it is
    now `_bounds_column` on the constraint's own text. Stating only the first
    half was this file's own recorded failure, a comment defending the part that
    is fine while the part that is not sits beside it.

    **What this does not cover, and what does.** A constraint **deleted** rather
    than given the wrong enum is not this rule's business and is already caught:
    `TestEveryEnumColumnIsConstrainedOrExemptWithAReason` is the half that asks
    whether a constraint exists, and this is the half that asks whether the one
    that exists says the right thing. Verified by the design seat, 2026-09-11,
    by deleting the constraint outright.

    **The exclusion, stated rather than left to be discovered**: a table whose
    `scheme` column carries no `ck_*_scheme` constraint is outside this rule and
    not a violation of it. `classifications` is that case deliberately, and
    `enums.ClassificationScheme` carries the reason: a CHECK costs a batch table
    rebuild every time the enum grows, which is a fair price for a closed enum
    and a recurring tax on one that is not.
    """

    #: The value list out of `scheme IN ('a', 'b')`, in the order written.
    #:
    #: **Extraction only. `_bounds_column` decides what is collected**, and the
    #: two have to agree about **which clause**, which is why this carries that
    #: helper's `(?<![A-Za-z0-9_])` rather than a looser spelling of it.
    #:
    #: **Without the lookbehind the pair fails silently**, and that is measured
    #: rather than argued. `_bounds_column` collects on the real clause and this
    #: extracts the **first** `scheme IN (` in the text, so they select
    #: different clauses whenever an earlier one ends in `scheme`. Measured in
    #: process by the design seat, 2026-09-11, against
    #: `"xscheme IN ('asin', 'google_books') AND scheme IN ('gnd')"`: the rule
    #: read `'asin', 'google_books'`, matched the enum and reported **clean**
    #: while the constraint permitted only `'gnd'`. That is this class's own
    #: defect restored, one spelling further out from the rename the security
    #: seat found, and the direction is a pass rather than a failure.
    #:
    #: No live instance either way: the only column whose name ends in `scheme`
    #: is `scheme`, over `Base.metadata`. The lookbehind changes nothing that
    #: exists, a clause at position 0 included, because a lookbehind there
    #: succeeds.
    AN_IN_LIST = re.compile(
        r"(?<![A-Za-z0-9_])scheme\s+IN\s*\(([^)]*)\)", re.IGNORECASE
    )

    @staticmethod
    def _enum_on(table_name: str, column_name: str = "scheme") -> type[StrEnum] | None:
        """The enum a table's column is annotated with, or `None`.

        Read through `inspect.get_annotations(eval_str=True)` rather than off
        the column, because SQLAlchemy stores `String(20)` and the enum lives
        only in the `Mapped[...]` annotation. Under PEP 649 that annotation is
        lazy, so it has to be evaluated rather than read as a string.

        **Through `_enum_types`, which already recurses.** This walked
        `get_args` at one fixed depth, which is the miss that helper was written
        to fix and its docstring records: `Mapped[E]` resolved and
        `Mapped[E | None]` answered `None`. `_enum_columns` measured that exact
        shape at 7 found against 11, the four missed being every nullable
        column, and **4 of the 12 mapped `StrEnum` columns in this tree are
        nullable today** (`books.condition`, `books.format`, `books.lending`,
        `classifications.kind`), so it is ordinary rather than hypothetical; it
        had simply not reached a `scheme` column yet.

        **The direction was loud and the explanation was false**, which is why
        it was worth deleting rather than correcting: a nullable scheme column
        made `_disagreement` take its `expected is None` arm, so
        `test_each_one_lists_exactly_its_own_enum` failed saying the constraint
        was "unguarded and silent" about a column that was correctly guarded.
        Found by the design seat, 2026-09-11, one round after the same shape in
        the regex.

        **`column_name` is a parameter so that this is testable, and that is
        the whole reason it is not hardcoded.** No `scheme` column in this
        schema is nullable, so a rule that could only be asked about one had
        nothing to discriminate the two walks with, and re-inlining the shallow
        one left the file green at 13 passed. It does not have to be asked
        about a `scheme` column: `books.format` is a live nullable `StrEnum`
        column and the two walks answer differently on it, as they do on
        `books.condition`, `books.lending` and `classifications.kind`.
        `test_it_reads_a_nullable_column_off_a_real_table` is that assertion,
        so the delegation is **tested** rather than stated. Raised by the design
        seat on 2026-09-11 against a docstring that had settled for stated one
        step early.
        """
        for mapper in Base.registry.mappers:
            if getattr(mapper.local_table, "name", None) != table_name:
                continue
            declared = inspect.get_annotations(mapper.class_, eval_str=True)
            return next(iter(_enum_types(declared.get(column_name))), None)
        return None

    @classmethod
    def _scheme_checks(cls) -> list[tuple[str, CheckConstraint]]:
        found = []
        for table in Base.metadata.tables.values():
            for constraint in table.constraints:
                if not isinstance(constraint, CheckConstraint):
                    continue
                # **On the shape, never on the name**, which is a correction
                # rather than a convenience: this collected on
                # `^ck_\w+_scheme$` against `constraint.name`, the one
                # attribute of a scheme constraint that says nothing about
                # whether it lists the right enum. Measured by the security
                # seat, 2026-09-11: renaming `ck_book_identifiers_scheme` to
                # `..._scheme_list` **and** passing the wrong enum gave 665
                # passed with nothing red, the exact defect this class exists
                # for, restored. A constraint cannot leave this rule by being
                # relabelled.
                #
                # **Through `_bounds_column`, which is the same question the
                # class next door asks**, rather than through a second pattern
                # of this class's own. That makes the two rules' agreement a
                # call instead of a coincidence: a CHECK this cannot see reads
                # as **no** constraint to `TestEveryEnumColumnIsConstrainedOr
                # ExemptWithAReason`, which is what closes the spelling one
                # further out from the rename. Raised by the design seat after
                # it went looking for exactly that hole and found the coupling
                # holding it shut by accident.
                #
                # **Deliberately not pre-filtered on whether the enum can be
                # read.** A table this rule cannot pair with an enum has to
                # reach `_disagreement` and be **reported**, because unguarded
                # and silent is the one outcome not available, which is what
                # `test_the_guard_would_notice_a_column_it_cannot_read_an_enum_
                # off` pins. Filtering here would make that test vacuous.
                if _bounds_column(str(constraint.sqltext), "scheme"):
                    found.append((table.name, constraint))
        return found

    def test_there_is_something_to_check(self):
        """A rule that found nothing would pass forever. Two tables carry one
        today, and the number is derived rather than stated: what this asserts
        is that the pattern still matches something.

        **It is not what catches a constraint leaving the rule**, and saying so
        is the point: it passed through the rename that hid one, because the
        other was still there. `_bounds_column` on the constraint's own text is
        what closes that; this only closes the whole set going empty.
        """
        assert self._scheme_checks()

    @classmethod
    def _disagreement(cls, table_name: str, sqltext: str, name: str) -> str | None:
        """What is wrong with one constraint, or `None` where nothing is.

        **One comparison, used by the rule and by the probe below**, which is
        the arrangement this class did not have on its first attempt: the probe
        compared two enums to each other and so passed on a tree where
        `_scheme_checks` found nothing and where `_enum_on` answered `None`. It
        was named for a mutation it could not observe, which is the shape
        `CLAUDE.md` records as recurring, and the design seat caught it.
        """
        expected = cls._enum_on(table_name)
        if expected is None:
            return (
                f"{name} sits on a table whose `scheme` column this rule could "
                "not read an enum off, so the constraint is unguarded and "
                "silent, which is the one outcome not available."
            )
        listed = cls.AN_IN_LIST.search(sqltext)
        if listed is None:
            return f"{name} is not a `scheme IN (...)` list, so this rule cannot read it."
        values = {value.strip().strip("'") for value in listed.group(1).split(",")}
        if values == {member.value for member in expected}:
            return None
        return (
            f"{name}: permits {sorted(values)}, "
            f"{expected.__name__} offers {sorted(m.value for m in expected)}"
        )

    def test_each_one_lists_exactly_its_own_enum(self):
        wrong = [
            found
            for table_name, constraint in self._scheme_checks()
            if (
                found := self._disagreement(
                    table_name, str(constraint.sqltext), str(constraint.name)
                )
            )
            is not None
        ]

        assert not wrong, (
            "A scheme constraint does not list the enum its own column is typed "
            "as. A value the application accepts and the database rejects "
            "arrives as an IntegrityError on somebody's first write:\n  "
            + "\n  ".join(wrong)
        )

    def test_the_guard_would_notice_the_wrong_enum(self):
        """A guard that cannot fail is not a guard, and this is the exact
        mutation that got past mypy and the suite: the right helper called with
        the neighbouring enum.

        **Through `_disagreement`, which is what the rule itself calls**, so
        this cannot pass on a tree where the enum could not be read or where
        the constraint list came back empty. Those were live holes in the first
        version, which compared `AuthorityScheme` and `BookIdentifierScheme` to
        each other and would have reported a difference on any tree at all.
        """
        from enums import AuthorityScheme

        reported = self._disagreement(
            "book_identifiers",
            orm._scheme_check(AuthorityScheme),
            "ck_book_identifiers_scheme",
        )

        # **The mismatch arm specifically, not merely "something was wrong".**
        # `_disagreement` has three ways to answer, and two of them mean this
        # rule's own machinery is broken rather than that the constraint is.
        # Without this line the probe passes on a tree where `_enum_on` or
        # `AN_IN_LIST` has stopped working, which is the overclaim it was
        # rewritten to close. Those two are loud anyway, in
        # `test_each_one_lists_exactly_its_own_enum`, which is what makes the
        # pair sound rather than this assertion alone.
        assert reported is not None and "permits" in reported

    def test_it_reads_the_clause_that_bounds_the_column(self):
        """Collection and extraction have to select the **same** clause.

        **The one arm of this class whose failure was a silent pass.** With the
        lookbehind on `_bounds_column` and not on `AN_IN_LIST`, the two selected
        different clauses whenever an earlier one ended in `scheme`: the
        constraint below was collected on its real clause and read off its
        decoy, so the rule matched `'asin', 'google_books'` against the enum and
        answered clean while the constraint permitted only `'gnd'`. Found by the
        design seat, 2026-09-11, in the round that introduced it.

        No table in this schema is shaped like this, and that is why the hole
        was invisible rather than why it was harmless: the other arms all fail
        loudly and this one did not fail at all.
        """
        decoy = "xscheme IN ('asin', 'google_books') AND scheme IN ('gnd')"

        reported = self._disagreement("book_identifiers", decoy, "ck")

        assert reported is not None and "permits" in reported
        # The clause that bounds the column, not the one that merely ends in
        # its name. Asserting the **values** rather than only that something
        # was reported: reading the decoy also reports, for the wrong reason,
        # and that arm keeps catching if the enum grows a third member and the
        # decoy stops equalling it.
        assert "gnd" in reported

    def test_it_reads_a_nullable_column_off_a_real_table(self):
        """`_enum_on` resolves `Mapped[E | None]`, asked about a live column.

        **Against the function rather than against the helper**, which is what
        moves this from stated to tested: a one level `get_args` walk answers
        `None` here and the delegation answers `BookFormat`. Four mapped columns
        discriminate the two today, `books.format`, `books.condition`,
        `books.lending` and `classifications.kind`, and none of them is a
        `scheme` column, which is why this rule takes a column name.

        `books.format` rather than a synthetic table, because a rule that reads
        annotations off real mappers has to be asked about a real mapper: a
        synthetic one would be testing the walk and not the lookup.
        """
        from enums import BookFormat

        assert self._enum_on("books", "format") is BookFormat

    def test_the_helper_this_rule_resolves_through_reads_both_spellings(self):
        """`_enum_types` answers for `Mapped[E]` and `Mapped[E | None]` alike.

        **This pins the helper, not `_enum_on`, and the difference is the whole
        honesty of the test.** `_enum_on` re-spelled a one-level walk past this
        helper until 2026-09-11, so a nullable `scheme` column would have been
        reported as "unguarded and silent" while being correctly guarded. The
        fix deletes that walk and delegates here.

        **Re-inlining the walk is caught by
        `test_it_reads_a_nullable_column_off_a_real_table`**, which asks
        `_enum_on` itself about `books.format`. This arm is the other half: it
        stops the helper regressing, where that one stops the rule walking past
        it. Both are needed and neither is the other.

        Named for what it does rather than for what the fix was about, because
        a fixture named for what it tests is not evidence that it tests it.
        """
        from sqlalchemy.orm import Mapped

        from enums import BookIdentifierScheme

        # Both spellings, because the rule has to be one rule: the shallow walk
        # resolved the first and answered `None` for the second.
        assert _enum_types(Mapped[BookIdentifierScheme]) == [BookIdentifierScheme]
        assert _enum_types(Mapped[BookIdentifierScheme | None]) == [
            BookIdentifierScheme
        ]

    def test_the_guard_would_notice_a_column_it_cannot_read_an_enum_off(self):
        """The other hole the first version had: a table this rule cannot pair
        with an enum has to be **reported**, never passed over, because
        unguarded and silent is the failure the whole file exists to prevent."""
        assert (
            self._disagreement(
                "books", "scheme IN ('asin')", "ck_books_scheme"
            )
            is not None
        )


class TestEveryTextCeilingBindsOnBytesToo:
    """A character ceiling in SQLite is not a ceiling until bytes are bounded too.

    `length()` on text counts characters **up to the first NUL**. Measured
    2026-09-10: `"a\\x00" + "x" * 10000` reports a `length()` of 1 and stores
    10,002 bytes, so `length(col) <= 2000` admits a value nothing bounded. Every
    such CHECK exists for `backup.restore`, which inserts through Core and runs
    no Pydantic model, and that is exactly the path where the character
    inequality does not bind.

    **Two arms close it and this accepts either.** A byte budget of four times
    the character budget, four bytes being UTF-8's widest character. Or a clause
    refusing a NUL outright, `instr(col, char(0)) = 0`, which
    `catalogue_credentials` and `opds_servers` already carry beside a charset
    rule. Naming one of the two would have made the other a violation.

    **Floors are not in the class.** A NUL shortens the count, so `length(x) > 0`
    and `length(x) >= 40` become stricter on the same value rather than weaker,
    and there is nothing to close.

    **This reads every `length(` in the constraint and refuses to skip one**,
    which is the difference between this rule and the version a critic evaded.
    That version matched two spellings, `<=` and `BETWEEN`, so the same bound on
    the same column written `length(x) < 121` was not a ceiling to it and shipped
    unarmed with nothing red: measured on `loans.loaned_to_name`, `<= 120` failed
    and `< 121` passed. **A longer list of operators would have been the same
    defect one spelling further out.** So each occurrence is classified as a
    ceiling, a floor or a byte arm, and one this cannot read is reported rather
    than passed over. The operator list is still here and is now load bearing in
    the other direction: getting it wrong fails loudly.

    **`GLOB` charset rules are a different class and are deliberately outside
    this rule**, stated so the boundary is a decision rather than a gap: GLOB is
    a C string operation and stops at the first NUL too, but the threat is a
    smuggled suffix in a value that reaches a query or a URL rather than an
    unbounded write, and the arm is the `instr` one rather than a budget. The
    ones that carry it bare are in the tracker.

    **A ceiling written as a negated floor is outside it too, and that one is a
    gap rather than a class.** `NOT (length(a) > 60)` is a real ceiling and this
    reads it as a floor, so it passes. Nothing in the tree is spelled that way
    and the cost of covering it is a negation pass over the whole expression, so
    it is named here rather than closed: knowing which of the two it is matters
    more than the line it would take.

    **This reads the model's declaration, which enforces nothing by itself**;
    `test_schema.py::TestEveryTextCeilingIsInstalledWithItsByteArm` is what holds
    that declaration against the DDL a migrated database actually carries.
    """

    #: What may follow a `length(...)` term, and what each means for the value.
    #:
    #: **A closed set rather than a growing one**: these are every SQL
    #: comparison, and the exhaustiveness check below is what says so at the
    #: moment the rule runs rather than in this comment.
    AN_UPPER_BOUND = ("<=", "<")
    A_LOWER_BOUND = (">=", ">")

    #: The names this rule reads, folded to the one spelling it compares
    #: against. SQL folds a function name and this file does not: `models.py`
    #: writes `CAST`, `BETWEEN`, `AND`, `GLOB` and `IN` upper case and `length`
    #: and `instr` lower, and a rule matching literal text has to fold the same
    #: way or it has a hole exactly where the next author disagrees about case.
    #:
    #: **`length` is the one whose absence is silent**, which is why this exists.
    #: A scan for `length(` never reaches `LENGTH(`, so the occurrence is neither
    #: classified nor reported as unreadable and the whole "refuses to skip one"
    #: armour is bypassed. Measured on `ONE_BORROWER_SQL`: the same bound written
    #: lower case fails the rule and written upper case passes it. The rest fold
    #: here for consistency, and getting one of them wrong is loud rather than
    #: quiet: a byte arm this cannot find is reported as missing.
    #:
    #: `length (x)` folds too, because the space is the same defect spelled with
    #: whitespace.
    FOLDED = (
        (r"\blength\s*\(", "length("),
        (r"\binstr\s*\(", "instr("),
        (r"\bcast\s*\(", "CAST("),
        (r"\bchar\s*\(", "char("),
        (r"\bas\s+blob\b", "AS BLOB"),
    )

    @classmethod
    def _canonical(cls, declared: str) -> str:
        for pattern, spelling in cls.FOLDED:
            declared = re.sub(pattern, spelling, declared, flags=re.IGNORECASE)
        return declared

    @classmethod
    def _has_a_top_level_or(cls, declared: str) -> bool:
        """Whether an `OR` sits outside every parenthesis in this constraint.

        **SQL binds `AND` tighter than `OR`**, so `X OR Y AND Z` is `X OR (Y AND
        Z)` and `Z` is not a rule about every row: on any row satisfying `X`
        neither `Y` nor `Z` binds. `_conjuncts` splits on `AND` alone and hands
        back `Z` as though it were top level, which cleared a ceiling that bound
        on nothing. Measured against `ck_quotes_page_bounds`, whose text already
        opens `page IS NULL OR (...)`: appending a real ceiling and a real NUL
        clause to it left the whole suite green.

        So a constraint shaped like that has its ceilings reported rather than
        cleared: this rule cannot say which rows a clause in it binds on, and
        saying so is the honest answer.

        **Depth zero specifically, not any `OR`.** `ck_quotes_text_bounds`
        depends on a correct conditional ceiling one level in, `(note IS NULL OR
        (...))`, and a rule refusing every `OR` would break the one conditional
        bound in the tree that is right.

        **It costs nothing today**, measured over `models.py` rather than
        assumed: nine constraints carry a depth zero `OR` and not one of them
        holds a `length(` term. The count is nine rather than the eight a first
        reading of the same file gave, which is why it is recomputed here by
        `test_the_or_rule_costs_what_it_is_said_to_cost` instead of being written
        down once.
        """
        depth = 0
        for position, character in enumerate(declared):
            if character == "(":
                depth += 1
            elif character == ")":
                depth -= 1
            elif depth == 0 and declared[position : position + 4].upper() == " OR ":
                return True
        return False

    @staticmethod
    def _conjuncts(declared: str) -> list[str]:
        """The constraint's top level `AND` terms, unparenthesised.

        **A clause is only a rule about every row if it is one of these.** The
        NUL branch below used to ask whether `instr(col, char(0)) = 0` appeared
        anywhere in the text, and `(page IS NULL OR instr(text, char(0)) = 0)`
        satisfies that while binding on no row carrying a page: measured, it
        cleared a 500 character ceiling with no byte arm and nothing went red.

        **It is not symmetric with the byte arm branch**, which is why this
        matters more than it looks. A ceiling cleared by a byte arm has a
        behavioural backstop, since `test_schema.py::_byte_armed_constraints`
        keys on `AS BLOB` and `test_every_byte_armed_constraint_has_a_behavioural
        _case` then forces a probe of it. A ceiling cleared by `instr` is not
        byte armed, so nothing probes it and this text is the whole of the rule.

        Splitting is naive about `BETWEEN`, whose own `AND` divides one term into
        two. That only ever produces more terms than there are, so a clause this
        finds is really a conjunct and a real one it splits in half is reported
        rather than cleared, which is the safe direction.
        """
        terms: list[str] = []
        depth = start = position = 0
        while position < len(declared):
            character = declared[position]
            if character == "(":
                depth += 1
            elif character == ")":
                depth -= 1
            elif depth == 0 and declared[position : position + 5].upper() == " AND ":
                terms.append(declared[start:position].strip())
                position += 5
                start = position
                continue
            position += 1
        terms.append(declared[start:].strip())
        return terms

    @staticmethod
    def _closing(text: str, opened: int) -> int:
        """Where the parenthesis opened at `opened` closes."""
        depth = 0
        for position in range(opened, len(text)):
            if text[position] == "(":
                depth += 1
            elif text[position] == ")":
                depth -= 1
                if depth == 0:
                    return position
        raise AssertionError(f"unbalanced parentheses in {text!r}")

    @classmethod
    def _ceilings(cls, declared: str) -> tuple[list[tuple[list[str], int]], list[str]]:
        """Every upper bound on a character length, and what could not be read.

        A bound's left side may be a sum, which is how `digital_references`
        bounds a root and a path **as a pair**, so the columns come back as a
        list and the byte arm this implies is a sum in the same shape.
        """
        declared = cls._canonical(declared)
        ceilings: list[tuple[list[str], int]] = []
        unreadable: list[str] = []
        chain: list[str] = []
        position = 0
        while (found := declared.find("length(", position)) != -1:
            close = cls._closing(declared, found + len("length"))
            inner = declared[found + len("length(") : close]
            rest = declared[close + 1 :].lstrip()
            position = close + 1
            if inner.startswith("CAST("):
                # **A byte arm only where the cast is to BLOB**, which is the
                # one target that makes `length()` count bytes.
                # `CAST(x AS TEXT)` is still text, so `length()` still stops at
                # the first NUL and the ceiling over it is the very class this
                # rule exists for: read as an arm it cleared itself, silently.
                # Any other cast is reported rather than believed.
                if not inner.rstrip().endswith("AS BLOB)"):
                    unreadable.append(f"length({inner})")
                # **A chain still open here is a sum mixing a character length
                # with a byte one**, which is neither, so it is reported rather
                # than dropped along with the reset.
                unreadable += [f"length({one}) + length({inner})" for one in chain]
                chain = []
                continue
            chain.append(inner.strip())
            if rest.startswith("+"):
                # A sum: the bound belongs to the last term in the chain. What is
                # added has to be another `length(...)`, and anything else, `+ 1`
                # for a separator being the obvious one, leaves the chain open
                # and is reported at the foot of this loop.
                continue
            number = re.match(r"(<=|<|>=|>)\s*(\d+)", rest)
            between = re.match(r"BETWEEN\s+\d+\s+AND\s+(\d+)", rest, re.IGNORECASE)
            if between:
                ceilings.append((chain, int(between.group(1))))
            elif number and number.group(1) in cls.AN_UPPER_BOUND:
                # `< N` bounds at `N - 1`, so the byte arm this implies is four
                # times that and not four times the literal. Getting it wrong
                # here would ask for an arm three bytes wider than the value it
                # is supposed to bound exactly.
                strict = 1 if number.group(1) == "<" else 0
                ceilings.append((chain, int(number.group(2)) - strict))
            elif number and number.group(1) in cls.A_LOWER_BOUND:
                pass
            else:
                unreadable.append(f"length({inner}){rest[:24]}")
            chain = []
        # **A chain still open when the scan ends is a bound this cannot read**,
        # and dropping it was the second hole in this rule: `length(a) + 1 <= 61`
        # left `ceilings` and `unreadable` both empty, so the bound was skipped
        # rather than cleared, which is the one thing the docstring above says
        # cannot happen. `length(root_label) + length(relative_path) + 1` is the
        # natural spelling the day `digital_references` counts its separator, and
        # that pair is the only summed bound in this tree.
        unreadable += [f"length({one}) + something this rule cannot read" for one in chain]
        return ceilings, unreadable

    @staticmethod
    def _wanted(columns: list[str], ceiling: int) -> str:
        """The byte arm one character ceiling implies, in the same shape.

        Built from the bound's own left side rather than per column, so a bound
        on a **pair** gets a byte arm on the pair. A rule stated per column would
        be satisfied on `digital_references` by a term bounding one half.

        **One spelling, deliberately.** A ceiling written some other way is told
        the arm to add in the spelling this file endorses rather than being met
        halfway, which is what keeps the constraints in this tree comparable.
        """
        terms = " + ".join(f"length(CAST({column} AS BLOB))" for column in columns)
        return f"{terms} <= {4 * ceiling}"

    @staticmethod
    def _declared() -> dict[str, str]:
        constraints: dict[str, str] = {}
        for table in Base.metadata.tables.values():
            for constraint in table.constraints:
                if isinstance(constraint, CheckConstraint) and isinstance(
                    constraint.name, str
                ):
                    constraints[constraint.name] = " ".join(
                        str(constraint.sqltext).split()
                    )
        return constraints

    @classmethod
    def _offences(cls, name: str, raw: str) -> list[str]:
        """What one constraint's text is doing wrong, if anything.

        **Separated from the sweep so it can be driven against text**, which is
        the only way the two clearing branches get tested at all: the sweep runs
        over `Base.metadata`, where every constraint is already correct, so a
        branch that cleared too readily was invisible there. Both branches had
        exactly that defect and both were found by mutation rather than reading.
        """
        declared = cls._canonical(raw)
        ceilings, unreadable = cls._ceilings(declared)
        offences = [
            f"{name}: this rule cannot read `{one}`, so it is skipping a "
            "bound rather than clearing it"
            for one in unreadable
        ]
        if ceilings and cls._has_a_top_level_or(declared):
            # Neither branch below can clear a ceiling here, because no clause in
            # this constraint is a rule about every row. See `_has_a_top_level_or`.
            return offences + [
                f"{name}: a ceiling of {ceiling} on {columns} shares a constraint "
                "with a top level OR, so nothing in it binds on every row"
                for columns, ceiling in ceilings
            ]
        conjuncts = cls._conjuncts(declared)
        for columns, ceiling in ceilings:
            # **A conjunct, not a substring.** A NUL clause inside a disjunction
            # binds on some rows and reads as a rule about all of them.
            if all(
                f"instr({column}, char(0)) = 0" in conjuncts for column in columns
            ):
                continue
            # **`(?!\d)`, because containment prefix matches a number.**
            # Widening a budget from 240 to 2400 in both copies left this clean,
            # since `<= 240` is a substring of `<= 2400`. The behavioural probe
            # in `test_schema.py` catches that one out, which is exactly why both
            # layers have to hold.
            wanted = cls._wanted(columns, ceiling)
            if re.search(f"{re.escape(wanted)}(?!\\d)", declared):
                continue
            offences.append(
                f"{name}: a ceiling of {ceiling} on {columns} wants `{wanted}`"
            )
        return offences

    #: One constraint's text, and whether this rule must object to it.
    #:
    #: Every row is a clearance that looked right and was not, which is why they
    #: are here rather than trusted to the sweep: over `Base.metadata` every
    #: constraint already passes, so a branch that cleared too readily reads
    #: clean there for ever.
    CLEARANCES: Final = (
        ("length(text) <= 500", True),
        ("length(text) <= 500 AND instr(text, char(0)) = 0", False),
        # Binds on no row carrying a page, and cleared the ceiling anyway.
        ("length(text) <= 500 AND (page IS NULL OR instr(text, char(0)) = 0)", True),
        ("length(text) <= 500 AND length(CAST(text AS BLOB)) <= 2000", False),
        # `<= 200` is a substring of `<= 2000`, and was accepted as the arm.
        ("length(text) <= 50 AND length(CAST(text AS BLOB)) <= 2000", True),
        # Still text, so `length()` still stops at the first NUL.
        ("length(CAST(text AS TEXT)) <= 500", True),
        # `AND` binds tighter than `OR`, so the NUL clause is inside the right
        # arm and binds on no row where `page = 1`. It read as top level.
        ("page = 1 OR length(text) <= 500 AND instr(text, char(0)) = 0", True),
        # The conditional ceiling this tree actually has, one level in, which
        # must keep clearing: a rule refusing every `OR` would break it.
        (
            "length(text) <= 2000 AND length(CAST(text AS BLOB)) <= 8000 "
            "AND (note IS NULL OR (length(note) <= 1000 "
            "AND length(CAST(note AS BLOB)) <= 4000))",
            False,
        ),
    )

    @pytest.mark.parametrize(("declared", "objects"), CLEARANCES)
    def test_what_clears_a_ceiling_and_what_only_looks_like_it(
        self, declared: str, objects: bool
    ) -> None:
        """The two clearing branches, driven against text.

        A ceiling cleared by a **byte arm** has a behavioural backstop, since
        `test_schema.py` forces a probe of every constraint carrying `AS BLOB`. A
        ceiling cleared by **`instr`** has none, because it is not byte armed, so
        the text is the whole of the rule and these rows are the whole of the
        test of it.
        """
        assert bool(self._offences("ck_under_test", declared)) is objects

    def test_the_or_rule_costs_what_it_is_said_to_cost(self) -> None:
        """`_has_a_top_level_or` reports every ceiling in such a constraint, and
        that is only affordable while no constraint has both.

        **Recomputed here rather than written down**, because the number moved
        between two readings of the same file: one gave eight and this gives
        nine, the missing one being `ck_password_reset_requests_approval`. A
        count in a docstring would have been copied forward wrong.

        If this ever fails it is not a defect in the constraint, it is this rule
        saying it cannot tell which rows that ceiling binds on. The answer then
        is to parenthesise the constraint, which is what makes it readable to a
        person too.
        """
        conditional = {
            name
            for name, raw in self._declared().items()
            if self._has_a_top_level_or(self._canonical(raw))
        }
        both = {
            name
            for name in conditional
            if self._ceilings(self._canonical(self._declared()[name]))[0]
        }

        assert len(conditional) >= 9, sorted(conditional)
        assert not both, sorted(both)

    def test_every_character_ceiling_carries_a_byte_arm_or_refuses_a_nul(self) -> None:
        offenders: list[str] = []

        for name, raw in self._declared().items():
            offenders += self._offences(name, raw)

        assert not offenders, (
            "these bound a text column by characters, which SQLite counts only "
            "up to the first NUL, so a Core insert walks past them: "
            + "; ".join(offenders)
        )

    #: One spelling per row, and what this rule must make of it.
    #:
    #: `None` is a bound that is not a ceiling and needs no arm. A pair is the
    #: ceiling it reads, columns and bound. `UNREADABLE` is a bound it cannot
    #: classify, which is reported rather than skipped: the whole armour of this
    #: rule is that the third answer exists.
    UNREADABLE: Final = "unreadable"
    SPELLINGS: Final = (
        ("length(a) <= 60", (["a"], 60)),
        ("length(a) < 61", (["a"], 60)),
        ("length(a) BETWEEN 1 AND 60", (["a"], 60)),
        ("length(a) + length(b) <= 60", (["a", "b"], 60)),
        ("length(a) > 0", None),
        ("length(a) >= 40", None),
        ("length(trim(a)) > 0", None),
        ("length(CAST(a AS BLOB)) <= 240", None),
        ("length(a) <> 60", UNREADABLE),
        ("LENGTH(a) <= 60", (["a"], 60)),
        ("length (a) <= 60", (["a"], 60)),
        ("length(a) + 1 <= 61", UNREADABLE),
        ("length(a) + length(b) + 1 <= 61", UNREADABLE),
        ("length(a) + length(CAST(b AS BLOB)) <= 60", UNREADABLE),
        # A cast that is not to BLOB. `length()` on text still stops at the
        # first NUL, so this is a character ceiling that read as its own arm.
        ("length(CAST(a AS TEXT)) <= 120", UNREADABLE),
    )

    @pytest.mark.parametrize(("spelling", "expected"), SPELLINGS)
    def test_the_rule_reads_every_spelling_of_a_bound(
        self, spelling: str, expected: object
    ) -> None:
        """The diagonal, against constraint text this builds.

        **Against constructed text, because against this tree it is vacuous.**
        Only the first spelling appears in the tree, so a matcher that had
        stopped reading any of the others would still pass the rule above.

        **Every row but the first came from a critic**, over three rounds and
        three axes. The operator axis: `< 61` and `<> 60`, against a version that
        matched `<=` and `BETWEEN`. The case axis: `LENGTH(`, against a version
        whose scan never reached it, which is the one shape that was neither
        classified nor reported. And the summation axis: `+ 1`, against a version
        that left the chain open and dropped it. **A guard's author is the worst
        person to choose its evasion**, and the first draft of this table proved
        it by holding only the cases the rewrite had been designed against.

        Three answers rather than two, and that is the rule's armour: a bound it
        cannot classify is reported. Two answers would make every future spelling
        a silent pass.
        """
        ceilings, unreadable = self._ceilings(spelling)

        if expected is None:
            assert (ceilings, unreadable) == ([], [])
        elif expected == self.UNREADABLE:
            assert unreadable and not ceilings
        else:
            assert ceilings == [expected] and not unreadable

    def test_the_rule_is_reading_the_constraints_it_thinks_it_is(self) -> None:
        """A matcher that stopped matching would retire the rule above in silence.

        The floor is what the tree holds today and is a lower bound rather than a
        census, so adding a ceiling never fails this.
        """
        ceilings = [
            one
            for declared in self._declared().values()
            for one in self._ceilings(declared)[0]
        ]

        assert len(ceilings) >= 9, ceilings
        assert self._wanted(["a", "b"], 10) == (
            "length(CAST(a AS BLOB)) + length(CAST(b AS BLOB)) <= 40"
        )


class TestEveryTableIsInTheDataModelDocument:
    """`docs/data-model.md` describes the schema, so a table with no section is
    a document that describes a different one.

    Four tables had none, two of which hold credentials, in the document where
    the privacy rule is stated **from the data side**. A reader checking what an
    operator can see read a document that did not mention them, and nothing said
    so: the totals the document used to carry were prose, and a number in prose
    goes stale rather than failing.

    **So this recomputes the set rather than restating a count.** There is no
    number here to be wrong: `Base.metadata` is asked at the moment the rule
    runs, and a table added tomorrow fails this until somebody writes its
    section. That is the difference between the rule and the sentence it
    replaces, which said sixteen of twenty when it was already both.

    **A section is a bolded paragraph opener that is nothing but the table's
    name**, which is how every one of them is written. The run has to be the
    names and no prose, and that is not fussiness: a matcher taking any
    backticked name inside any bold run reported `user_books` as documented
    because of a paragraph two hundred lines away opening "**A log, not a
    `current_page` column on `user_books`.**", so its own section could be
    deleted and the rule stayed green. Measured on this document: the loose
    matcher yields 26 names for 21 tables and covers `collections` twice; this
    one yields exactly 21.

    Matched on a single line, so a bold run spanning a paragraph cannot sweep up
    a name below it either. `test_the_matcher_reads_an_opener_and_not_a_mention`
    drives both refusals against a document it builds, because against this one a
    matcher that had stopped being selective would still pass.
    """

    DOCUMENT = BACKEND.parent / "docs" / "data-model.md"

    #: A paragraph opening with a bold run that is one table's name, or two
    #: joined, and nothing else. The trailing full stop is optional because two
    #: of the twenty one sections are written without it.
    AN_OPENER = re.compile(
        r"^\*\*(`[a-z_]+`(?: and `[a-z_]+`)*)\.?\*\*", re.MULTILINE
    )

    @classmethod
    def _documented(cls, prose: str) -> set[str]:
        return {
            name
            for run in cls.AN_OPENER.findall(prose)
            for name in re.findall(r"`([a-z_]+)`", run)
        }

    def test_every_table_has_a_section(self) -> None:
        undocumented = sorted(
            set(Base.metadata.tables) - self._documented(self.DOCUMENT.read_text())
        )

        assert not undocumented, (
            "these tables are in the schema and not in the document that "
            f"describes it: {undocumented}"
        )

    def test_the_matcher_reads_an_opener_and_not_a_mention(self) -> None:
        """Against a document this builds, because the rule above is satisfied
        by a matcher that has stopped being selective.

        Every direction in one document: the opener is found, the mention in
        ordinary prose is not, **the mention inside somebody else's bold opener
        is not**, and the joint opener naming two tables yields both.

        Neither negative is hypothetical. The joint opener is how
        `custom_fields` and `custom_field_values` are written, and the third line
        here is copied from the paragraph that made `user_books` look documented
        while its own section could be deleted.
        """
        found = self._documented(
            "**`books`.** The catalogue.\n"
            "\n"
            "A row in `loans` is one lending event.\n"
            "\n"
            "**A log, not a `current_page` column on `user_books`.** Not a section.\n"
            "\n"
            "**`custom_fields` and `custom_field_values`.** A fact.\n"
        )

        assert found == {"books", "custom_fields", "custom_field_values"}
