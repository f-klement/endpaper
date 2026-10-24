"""`tests/corpus.py` hands over what this project wrote, and nothing else walks a tree.

Three questions, one class each: whether the vendored rule decides by shape,
whether every population refuses vendored code on a tree planted with it and
still reaches this project's own, and whether this checkout's populations are
still the whole of it. The fourth class is the ratchet that keeps the walks in
one home.
"""

import ast
import inspect
from collections.abc import Callable, Iterable
from pathlib import Path
from typing import Any, Final

import pytest

from tests import corpus
from tests.bindings import SourceNames, assignments, source_of, stated
from tests.corpus import (
    BACKEND,
    application_modules,
    every_python_file,
    is_vendored,
    shipped_modules,
    suite_modules,
    unowned_files,
)
from tests.declaration import SENTENCE, declares

TREE_GUARDS = {
    "TestEveryWalkSaysWhichTestsMakeIt": ("suite_modules",),
    "TestOnlyTheCorpusWalks": ("suite_modules",),
    "TestThisCheckoutsPopulationsAreTheWholeOfIt": (
        "application_modules",
        "every_python_file",
        "shipped_modules",
        "suite_modules",
        "unowned_files",
    ),
}


class TestTheVendoredRuleIsAShape:
    """`is_vendored` answers by a dotted part or a tool's directory, never by a list of tools."""

    def test_a_tool_nobody_has_written_yet_is_vendored(self) -> None:
        assert is_vendored(BACKEND / ".some-tool-nobody-has-written-yet" / "mod.py")
        assert is_vendored(BACKEND / "env" / "lib" / "site-packages" / "pydantic" / "main.py")
        assert not is_vendored(BACKEND / "shelf.py")
        assert not is_vendored(BACKEND / "routers" / "loans.py")

    def test_the_rule_holds_from_the_repository_root(self) -> None:
        """The dotted part is a level deeper from the repository, and a wrong
        root raises rather than answering about nothing."""
        repo = corpus.REPO

        assert is_vendored(BACKEND / ".uv-cache" / "pygments" / "lexers.py", repo)
        assert not is_vendored(repo / "frontend" / "src" / "main.tsx", repo)
        with pytest.raises(ValueError, match="is not in the subpath of"):
            is_vendored(repo / "frontend" / "src" / "main.tsx")


#: One vendored directory of each kind a population has to refuse, keyed by what it is.
#:
#: **Planted beside the application, inside the test tree and inside the
#: browser's source**, because a population that descends one of those never
#: sees a directory planted beside it. The pipeline's cache and an environment
#: with no dot are here because each was a real red pipeline; the last two are
#: the ones no list of names can hold.
VENDORED_KINDS: Final = {
    "a virtualenv": ".venv/lib/python3.14/site-packages/pydantic",
    "an environment whose directory is not hidden": "env/lib/python3.14/site-packages/pydantic",
    "the cache the pipeline creates under backend": ".uv-cache/cyclonedx/model",
    "bytecode beside a module of ours": "routers/__pycache__",
    "a dependency tree": "node_modules/marked/lib",
    "a tool nobody has written yet": ".some-tool/wheel",
    "an environment known only by its marker file": "tools/bin",
}

#: The kinds whose first directory is an environment's root and carries its marker.
_MARKED: Final = {"an environment known only by its marker file"}

#: What every population must still reach with all of that planted around it.
FIRST_PARTY: Final = (
    "shelf.py",
    "routers/loans.py",
    # Two packages, so a population that lost a whole directory is a
    # difference rather than a smaller set that still holds one.
    "schemas/book.py",
    "tests/test_shelf.py",
    "migrations/versions/a1.py",
    "README.md",
    # Emptied by the fixture: an ignore file with entries would let a walk pass
    # by reading the file rather than by applying the rule.
    ".gitignore",
    "frontend/src/main.tsx",
)

_THE_APP: Final = {"shelf.py", "routers/loans.py", "schemas/book.py"}
_THE_TESTS: Final = {"tests/test_shelf.py"}
_THE_MIGRATIONS: Final = {"migrations/versions/a1.py"}

#: What each population reaches out of `FIRST_PARTY`, keyed by its name in `tests/corpus.py`.
#:
#: **Compared as a whole against the module's public functions**, so a
#: population added there fails here until somebody states what it is for.
WHAT_EACH_POPULATION_REACHES: Final = {
    "unowned_files": set(FIRST_PARTY),
    "every_python_file": _THE_APP | _THE_TESTS | _THE_MIGRATIONS,
    "application_modules": _THE_APP,
    "shipped_modules": _THE_APP | _THE_MIGRATIONS,
    "suite_modules": _THE_TESTS,
    "application_sources": _THE_APP,
    "project_files": set(FIRST_PARTY),
    "markdown_files": {"README.md"},
    "browser_modules": {"frontend/src/main.tsx"},
}


def _populations() -> dict[str, Callable[[Path], Iterable[Path | str]]]:
    return {
        name: function
        for name, function in inspect.getmembers(corpus, inspect.isfunction)
        if function.__module__ == corpus.__name__ and not name.startswith("_") and name != "is_vendored"
    }


def _a_tree_with_vendored_code_in_it(root: Path, kind: str) -> None:
    for relative in FIRST_PARTY:
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("x = 1\n")
    (root / ".gitignore").write_text("")
    vendored = VENDORED_KINDS[kind]
    for base in (root, root / "tests", root / "frontend" / "src"):
        for name in ("mod.py", "notes.md", "view.tsx"):
            path = base / vendored / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("x = 1\n")
        if kind in _MARKED:
            (base / Path(vendored).parts[0] / "pyvenv.cfg").write_text("")


class TestEveryPopulationRefusesVendoredCode:
    """Each kind against every population, on a tree this builds.

    **Against a planted tree, not this checkout**: the directories in question
    are absent from a developer's `backend/` and present in the pipeline's.
    **Equality per population**, so one assertion says both halves: nothing
    vendored was read, and nothing of ours was lost.
    """

    def test_every_population_states_what_it_reaches(self) -> None:
        assert set(_populations()) == set(WHAT_EACH_POPULATION_REACHES)

    @pytest.mark.parametrize("kind", sorted(VENDORED_KINDS))
    def test_no_population_reads_this_kind(self, kind: str, tmp_path: Path) -> None:
        # Under a directory called `tests`, which is what says the populations
        # match their names below the root and not along the whole path.
        root = tmp_path / "tests" / "backend"
        _a_tree_with_vendored_code_in_it(root, kind)

        # `application_sources` keys by the relative path already.
        reached = {
            name: {
                str(path.relative_to(root)) if isinstance(path, Path) else path for path in population(root)
            }
            for name, population in _populations().items()
        }

        assert reached == WHAT_EACH_POPULATION_REACHES


class TestThisCheckoutsPopulationsAreTheWholeOfIt:
    """The backend populations on this tree, against instruments that do not route through the corpus.

    **A narrowing written in the one home takes every guard at once**, so this
    is where it has to red. Each arm compares a population with a glob of its
    own, which degrades differently from the walk under test. The repository
    populations are armed elsewhere: `markdown_files` by the internal Markdown
    guard's own walk, `browser_modules` by the diagonal above and by the
    module the Google Books guard anchors on.
    """

    def test_the_application_has_the_packages_it_has(self) -> None:
        """Reds by name on a narrowing by directory, and on a new package, which
        is a decision about what every rule over the application reads."""
        directories = sorted(
            {
                path.relative_to(BACKEND).parts[0]
                for path in application_modules()
                if len(path.relative_to(BACKEND).parts) > 1
            }
        )

        assert directories == ["routers", "schemas", "scripts"]

    def test_the_application_has_every_module_at_its_root(self) -> None:
        roots = {path.name for path in application_modules() if path.parent == BACKEND}
        globbed = {path.name for path in BACKEND.glob("*.py") if not path.name.startswith(".")}

        assert roots == globbed
        assert {"models.py", "shelf.py", "main.py"} <= roots

    def test_the_suite_is_every_python_file_under_the_test_tree(self) -> None:
        """No tool directory under `tests/` holds a `.py` file, so the exclusion
        is empty; this file being in the population is what says it is not
        empty for a worse reason."""
        walked = set(suite_modules())
        globbed = set((BACKEND / "tests").rglob("*.py"))

        assert sorted(map(str, globbed ^ walked)) == []
        assert Path(__file__).resolve() in walked

    def test_every_python_file_is_the_application_the_tests_and_the_migrations(self) -> None:
        """The migrations are globbed rather than sieved out of the walk under
        test, so a narrowing that dropped them would empty both sides at once
        only if written twice. `shipped_modules` is held to the same parts,
        since the diagonal plants no `scripts/` and a narrowing there would
        otherwise take every guard over the image unseen."""
        walked = set(every_python_file())
        migrations = set((BACKEND / "migrations").rglob("*.py"))

        assert migrations
        assert walked == set(application_modules()) | set(suite_modules()) | migrations
        assert set(shipped_modules()) == set(application_modules()) | migrations

    def test_what_the_walk_leaves_out_is_a_tools_or_not_python(self) -> None:
        """The complement, so a filename narrowing reds by name.

        `unowned_files` takes file names unfiltered and `every_python_file`
        drops a dotted one, which is the one difference between them. So a
        dotted module left out is not reported here.
        """
        left_out = set(unowned_files()) - set(every_python_file())

        assert (
            sorted(str(path) for path in left_out if path.suffix == ".py" and not path.name.startswith("."))
            == []
        )
        assert left_out, "the backend holds files that are not Python"


#: Every published module under `backend/tests` that walks a tree itself, and how many calls.
#:
#: **Equality**, so a new walk reds by name and so does one removed without its
#: row moving. A guard needing a corpus asks `tests/corpus.py` for one by name;
#: a row here is a walk that cannot, and says why.
#:
#: **A module the mirror strips states its own count, in `WALKS_OF_MY_OWN`**,
#: for the reason `tests.bindings.stated` gives.
WALKS: Final = {
    # The home.
    "corpus.py": 1,
    # The instruments the arming above compares the populations against, which
    # must not route through the walk they check.
    "test_corpus.py": 2,
}


def _stated(source: str, relative: str) -> int:
    """How many walks a module is allowed: its row in `WALKS`, or its own if it is internal."""
    return stated(source, relative, WALKS, "WALKS_OF_MY_OWN", 0)


def _walk_calls(source: str) -> int:
    """How many calls in `source` read a tree rather than one directory.

    **The callee is asked of `tests/bindings.py`**, so an import alias or a
    rebinding of `os.walk`, `glob.glob` or `glob.iglob` is the function it
    stands for. A callee nothing imported, such as `path.rglob` on a local, is
    read by its own attribute name. `rglob` counts, and so does `walk` on
    anything but `ast`; `glob` or `iglob` counts where its pattern is a `**`
    literal or not a literal at all. **A pattern this cannot read counts**,
    because a named constant or an f-string is the first spelling an author
    writes, and assuming it does not recurse would make naming it the evasion.

    Past it: a hand rolled `iterdir` or `scandir` recursion, `os.fwalk`,
    `pkgutil.walk_packages`, a bound method held in a variable unless its
    receiver was imported, a bound method handed to `functools.partial` or
    `map`, and a `git ls-files` subprocess. Each takes a deliberate act rather
    than the line a guard's author writes first.
    """
    tree = ast.parse(source)
    names = SourceNames(tree)
    count = 0
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        meanings = names.means(node.func)
        if meanings:
            verbs = {meaning.rpartition(".")[2] for meaning in meanings - {"ast.walk"}}
        elif isinstance(node.func, ast.Attribute):
            verbs = {node.func.attr}
        else:
            verbs = set()
        if verbs & {"rglob", "walk"}:
            count += 1
        elif verbs & {"glob", "iglob"}:
            count += _may_recurse(node)
    return count


def _may_recurse(call: ast.Call) -> bool:
    """Whether a `glob` call's pattern is a `**` literal, or one this cannot read."""
    keywords = {keyword.arg: keyword.value for keyword in call.keywords}
    pattern = call.args[0] if call.args else keywords.get("pattern", keywords.get("pathname"))
    if not (isinstance(pattern, ast.Constant) and isinstance(pattern.value, str)):
        return True
    return "**" in pattern.value


def _private_reads(source: str, package: str = "tests") -> list[str]:
    """Every private name of `tests/corpus.py` that `source` imports or reads off an import of it.

    **Asked of `tests/bindings.py`**, so any import of `tests.corpus` counts
    under any alias, relative ones resolved against `package`, and so does a
    plain rebinding of it. A local variable called `corpus` bound by anything else is
    not the module. Each import of a private name counts once and each attribute
    read once. Past it: a re-export of the module from another test module, and
    `getattr`, `importlib` and `__dict__`, which are deliberate.
    """
    tree = ast.parse(source)
    names = SourceNames(tree, package=package)

    def private(target: str) -> str | None:
        rest = target.removeprefix("tests.corpus.")
        if rest == target or "." in rest or not rest.startswith("_") or rest.startswith("__"):
            return None
        return rest

    found = sorted(
        name
        for binding in names.bindings
        if binding.written is not None and (name := private(binding.target))
    )
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute):
            found += sorted(name for target in names.means(node) if (name := private(target)))
    return found


class TestOnlyTheCorpusWalks:
    """A guard asks `tests/corpus.py` for a population by name and never walks.

    **A ratchet on call sites rather than a policing of what each walk reaches.**
    Every hand built walk this replaced was right on a developer's checkout and
    wrong in the pipeline, because each decided for itself what was vendored.
    One home for the decision leaves nothing per walk to check; what is left to
    check is that a new walk is not written.
    """

    def test_only_the_stated_modules_walk_a_tree(self) -> None:
        tests = BACKEND / "tests"
        sources = {path.relative_to(tests).as_posix(): source_of(path) for path in suite_modules()}
        wrong = {
            relative: f"{_walk_calls(source)} walks, {_stated(source, relative)} stated"
            for relative, source in sources.items()
            if _walk_calls(source) != _stated(source, relative)
        }

        assert wrong == {}, (
            "a module walks a tree itself, or stopped. A guard needing a corpus "
            "asks tests/corpus.py for a population by name, and a new kind of "
            "population is a function there with a row in "
            "WHAT_EACH_POPULATION_REACHES. A walk over a tree the test itself "
            "builds takes a row in WALKS saying so. A glob whose pattern is not a "
            "literal counts, so write a pattern that does not recurse inline. "
            "Lower a row when a walk goes."
        )
        assert set(WALKS) <= set(sources), sorted(set(WALKS) - set(sources))

    def test_a_bare_carriage_return_starts_no_line_for_the_declaration(self, tmp_path: Path) -> None:
        """The gate publishes a module whose declaration follows a bare carriage
        return, so its walks are counted from a row here, not from its own word."""
        written = f'"""Notes.\r\r{SENTENCE}\r"""\rWALKS_OF_MY_OWN = 2\r'
        module = tmp_path / "test_walks.py"
        module.write_bytes(written.encode("utf-8"))

        assert not declares(module.read_bytes())
        assert _stated(source_of(module), "test_walks.py") == 0
        # The same module with newlines is internal, so the fixture can tell.
        assert _stated(written.replace("\r", "\n"), "test_walks.py") == 2

    def test_no_module_reaches_past_the_populations_into_the_walk(self) -> None:
        """`_walk` takes the caller's own prune, so calling it is a walk that
        decides for itself what is vendored, and the count above cannot see it."""
        tests = BACKEND / "tests"
        reaching = {
            relative.as_posix(): names
            for path in suite_modules()
            if (relative := path.relative_to(tests)).as_posix() not in {"corpus.py", "test_corpus.py"}
            and (
                names := _private_reads(
                    path.read_text(encoding="utf-8"),
                    ".".join(("tests", *relative.parent.parts)),
                )
            )
        }

        assert reaching == {}, reaching

    @pytest.mark.parametrize(
        ("source", "names"),
        [
            ("from tests.corpus import _walk", ["_walk"]),
            ("from tests import corpus\ncorpus._walk(root, prune)", ["_walk"]),
            ("from tests import corpus as c\nc._environment(root)", ["_environment"]),
            ("from tests.corpus import project_files", []),
            ("from tests import corpus\ncorpus.__name__", []),
            ("corpus = load()\ncorpus._private", []),
            ("import tests.corpus\ntests.corpus._walk(root, prune)", ["_walk"]),
            ("import tests.corpus as c\nc._walk(root, prune)", ["_walk"]),
            ("from . import corpus\ncorpus._walk(root, prune)", ["_walk"]),
            ("from .corpus import _walk", ["_walk"]),
            ("from tests import corpus\nc = corpus\nc._walk(root, prune)", ["_walk"]),
        ],
    )
    def test_what_counts_as_reaching_past(self, source: str, names: list[str]) -> None:
        assert _private_reads(source) == names

    def test_a_relative_import_resolves_from_the_package_it_sits_in(self) -> None:
        """Two dots from a module under `tests/routers` is the test tree itself."""
        source = "from .. import corpus\ncorpus._walk(root, prune)"

        assert _private_reads(source, "tests.routers") == ["_walk"]

    def test_an_internal_module_states_its_own_count(self) -> None:
        """The stated count is read off the module, and only off one the gate strips."""
        internal = f'"""{SENTENCE}"""\nWALKS_OF_MY_OWN = 2\n'
        published = '"""Published."""\nWALKS_OF_MY_OWN = 2\n'

        assert _stated(internal, "test_x.py") == 2
        assert _stated(published, "test_x.py") == 0

    def test_a_flag_is_not_a_count(self) -> None:
        """`True` is an `int` to `isinstance`, so it read as one walk allowed."""
        assert _stated(f'"""{SENTENCE}"""\nWALKS_OF_MY_OWN = True\n', "test_x.py") == 0

    @pytest.mark.parametrize(
        ("source", "calls"),
        [
            ('BACKEND.rglob("*.py")', 1),
            ('BACKEND.glob("**/*.py")', 1),
            ('PATTERN = "**/*.py"\nBACKEND.glob(PATTERN)', 1),
            ('BACKEND.glob(f"**/*{SUFFIX}")', 1),
            ('glob.glob(os.path.join(R, "**", "*.py"), recursive=True)', 1),
            ("glob.iglob(pathname=PATTERN)", 1),
            ("os.walk(BACKEND)", 1),
            ("BACKEND.walk()", 1),
            ("from os import walk\nwalk(BACKEND)", 1),
            ('from glob import glob\nglob("**/*.py", recursive=True)', 1),
            ("from glob import iglob as g\ng(P)", 1),
            ('from glob import glob\nglob("*.py")', 0),
            ('BACKEND.glob("*.py")', 0),
            ("import ast\nast.walk(tree)", 0),
            ("import ast as a\na.walk(tree)", 0),
            ("import os as o\nw = o.walk\nw(BACKEND)", 1),
            ('from tests.corpus import BACKEND\nfind = BACKEND.rglob\nfind("*.py")', 1),
            ("import os\nw = os\nw = w.walk\nw(BACKEND)", 1),
            ('from tests.corpus import BACKEND\nfind = BACKEND\nfind = find.rglob\nfind("*.py")', 1),
            ('ROOT = Path(__file__).parent\nfind = ROOT.rglob\nfind("*.py")', 0),
            ("def walk(node):\n    pass\nwalk(node)", 0),
        ],
    )
    def test_what_counts_as_a_walk(self, source: str, calls: int) -> None:
        assert _walk_calls(source) == calls


def _bound(statement: ast.stmt) -> set[str]:
    """The module level names one statement binds."""
    if isinstance(statement, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
        return {statement.name}
    return {
        name.id
        for target, _value in assignments(statement)
        for name in ast.walk(target)
        if isinstance(name, ast.Name)
    }


def _mentions(statement: ast.stmt) -> set[str]:
    """Every name a statement could reach a module level binding by.

    A loaded name, a parameter, which is how a test asks for a fixture, and a
    string, which is how `usefixtures` and an indirect parametrisation do.
    """
    found: set[str] = set()
    for node in ast.walk(statement):
        if isinstance(node, ast.Name):
            found.add(node.id)
        elif isinstance(node, ast.arg):
            found.add(node.arg)
        elif isinstance(node, ast.Constant) and isinstance(node.value, str):
            found.add(node.value)
    return found


def _is_a_test(statement: ast.stmt) -> bool:
    return (isinstance(statement, ast.ClassDef) and statement.name.startswith("Test")) or (
        isinstance(statement, (ast.FunctionDef, ast.AsyncFunctionDef)) and statement.name.startswith("test")
    )


#: The population a call to `project_files` reads when it passes `readmit`: the
#: directories the tool rule prunes as well, so a path the others never reach.
READMITTED: Final = "project_files.readmit"


def _populations_of(call: ast.Call, names: SourceNames) -> set[str]:
    """The populations one call reads: none where it calls none."""
    called = {
        meaning.removeprefix("tests.corpus.")
        for meaning in names.means(call.func)
        if meaning.startswith("tests.corpus.")
    } & set(_populations())
    if any(keyword.arg == "readmit" for keyword in call.keywords) and "project_files" in called:
        called = called - {"project_files"} | {READMITTED}
    return called


def _walking_tests(source: str, package: str = "tests") -> tuple[dict[str, set[str]], set[str]]:
    """The module level tests whose run calls a population, each with the populations it
    reads, and the walks no test reaches.

    **A call counts by what it means, through `tests/bindings.py`**, so an alias
    or a module import of `tests.corpus` is the population, and a string holding
    its name is not. A test reads what it calls and what every module level
    binding it names reads, to any depth. The second set holds each module level
    name that walks and that no test names, which is a walk this cannot say
    which test makes, and so a walk in a helper module or a `conftest.py`
    fixture is reported: the module whose test judges with a population calls
    it. Past it: a population reached through another test module or
    `getattr`, and one used by value, handed to `parametrize` or a helper or
    re-exported from a helper module, which goes undeclared.
    """
    tree = ast.parse(source)
    names = SourceNames(tree, package=package)
    called = {
        id(node): populations
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and (populations := _populations_of(node, names))
    }
    # The declarations name the walking tests, so read as a mention they would walk too.
    statements = [
        s
        for s in tree.body
        if not isinstance(s, (ast.Import, ast.ImportFrom))
        and not _bound(s) & {"TREE_GUARDS", "TREE_GUARDS_LEFT_OUT"}
    ]
    reads: dict[str, set[str]] = {}
    for statement in statements:
        direct = set().union(*(called.get(id(node), set()) for node in ast.walk(statement)))
        if direct:
            for name in _bound(statement) or {f"<line {statement.lineno}>"}:
                reads.setdefault(name, set()).update(direct)
    grew = True
    while grew:
        grew = False
        for statement in statements:
            reached = set().union(*(reads[m] for m in _mentions(statement) & set(reads)))
            for name in _bound(statement):
                if reached - reads.get(name, set()):
                    reads.setdefault(name, set()).update(reached)
                    grew = True
    tests = {name: reads[name] for s in statements if _is_a_test(s) for name in _bound(s) & set(reads)}
    named: set[str] = set()
    reached_statements = [s for s in statements if _is_a_test(s)]
    while reached_statements:
        mentioned = set().union(*(_mentions(s) for s in reached_statements)) - named
        named |= mentioned
        reached_statements = [s for s in statements if _bound(s) & mentioned and not _is_a_test(s)]
    return tests, set(reads) - set(tests) - named


def _declared(source: str, constant: str) -> Any:
    """The value a module binds to `constant` at module level, or None where it binds none."""
    for statement in ast.parse(source).body:
        for target, value in assignments(statement):
            if isinstance(target, ast.Name) and target.id == constant:
                return ast.literal_eval(value)
    return None


def _misdeclared(
    source: str, package: str = "tests"
) -> tuple[dict[str, list[str]], dict[str, list[str]], list[str]] | None:
    """What a module's declarations get wrong against what it calls, or None.

    Returned as the tests that walk with what each reads, the tests declared
    with what each is said to read, and the walks no test reaches.
    """
    walking, unreached = _walking_tests(source, package)
    declared = _declared(source, "TREE_GUARDS")
    said = {name: set(populations) for name, populations in dict(declared or {}).items()}
    left_out = set(_declared(source, "TREE_GUARDS_LEFT_OUT") or ())
    if (
        set(said) | left_out == set(walking)
        and not set(said) & left_out
        and not unreached
        and (declared is not None) == bool(walking)
        and all(said[name] == walking[name] for name in said)
    ):
        return None
    return (
        {name: sorted(populations) for name, populations in walking.items()},
        {name: sorted(populations) for name, populations in said.items()},
        sorted(unreached),
    )


class TestEveryWalkSaysWhichTestsMakeIt:
    """A test module calling a population names the tests that do, in `TREE_GUARDS`,
    each with the populations it reads.

    A run choosing tests by the paths a branch changed can then add such a test
    by its populations, so a change is judged by the guards reading it and not
    only by the files it touched; twice a targeted run was green and the full run
    red on such a guard. A declaration is read and never derived at run time, so
    this holds the tests and their populations to what the module calls. A test
    left out of the added set on purpose is in `TREE_GUARDS_LEFT_OUT` instead,
    with its reason.
    """

    def test_every_module_declares_exactly_the_tests_that_walk(self) -> None:
        tests = BACKEND / "tests"
        wrong = {}
        for path in suite_modules():
            relative = path.relative_to(tests)
            if relative.as_posix() == "corpus.py":
                continue
            source = path.read_text(encoding="utf-8")
            package = ".".join(("tests", *relative.parent.parts))
            if (found := _misdeclared(source, package)) is not None:
                wrong[relative.as_posix()] = found

        assert wrong == {}, (
            "each module calling a population binds TREE_GUARDS, at module level, to a "
            "dict from each test that walks to the populations it reads, and a module "
            "calling none binds nothing. Per module: the tests that walk with what each "
            "reads, the tests declared, the walks no test reaches. A walk no test reaches "
            "in a helper module or a conftest.py fixture is moved into the test module "
            "that judges with it, which then declares it; no declaration clears it where "
            "it is."
        )

    @pytest.mark.parametrize(("constant", "opening"), [("TREE_GUARDS", "{"), ("TREE_GUARDS_LEFT_OUT", "(")])
    def test_a_declaration_starts_one_line_with_its_name(self, constant: str, opening: str) -> None:
        """A declaration is also read as text rather than parsed, from the line it starts."""
        wrong = [
            path.name
            for path in suite_modules()
            if (source := path.read_text(encoding="utf-8")).count(f"\n{constant} = {opening}")
            != (_declared(source, constant) is not None)
        ]

        assert wrong == []

    @pytest.mark.parametrize(
        ("source", "tests"),
        [
            (
                "from tests.corpus import suite_modules\nclass TestA:\n    def test_a(self):\n"
                "        suite_modules()\n",
                {"TestA": {"suite_modules"}},
            ),
            (
                "from tests import corpus as c\ndef test_a():\n    c.project_files()\n",
                {"test_a": {"project_files"}},
            ),
            (
                'X = "from tests.corpus import suite_modules"\nclass TestA:\n    def test_a(self):\n'
                "        print(X)\n",
                {},
            ),
            (
                "from tests.corpus import suite_modules\nclass TestA:\n    def test_a(self):\n"
                '        "suite_modules()"\n',
                {},
            ),
            (
                "from tests.corpus import application_modules\nMODULES = application_modules()\n"
                "def _names():\n    return MODULES\nclass TestA:\n    def test_a(self):\n"
                "        _names()\nclass TestB:\n    def test_b(self):\n        pass\n",
                {"TestA": {"application_modules"}},
            ),
            (
                "import pytest\nfrom tests.corpus import markdown_files\n"
                "@pytest.fixture\ndef files():\n    return markdown_files()\n"
                "def test_a(files):\n    pass\n",
                {"test_a": {"markdown_files"}},
            ),
            (
                'from tests.corpus import suite_modules\nTREE_GUARDS = {"TestA": ("suite_modules",)}\n'
                "class TestA:\n    def test_a(self):\n        suite_modules()\n",
                {"TestA": {"suite_modules"}},
            ),
            (
                "from tests.corpus import browser_modules, suite_modules\nTOP = suite_modules()\n"
                "class TestA:\n    def test_a(self):\n        browser_modules()\n        print(TOP)\n",
                {"TestA": {"browser_modules", "suite_modules"}},
            ),
            (
                "from tests.corpus import project_files\ndef test_a():\n"
                "    project_files(readmit=lambda _: True)\n",
                {"test_a": {"project_files.readmit"}},
            ),
        ],
        ids=[
            "a call in a test",
            "a module alias",
            "a fixture's string naming one",
            "a string inside a test",
            "through a constant and a helper",
            "through a fixture",
            "beside its own declaration",
            "two populations, one through a constant",
            "the ignore file's directories readmitted",
        ],
    )
    def test_what_counts_as_a_test_that_walks(self, source: str, tests: dict[str, set[str]]) -> None:
        assert _walking_tests(source) == (tests, set())

    def test_a_walk_no_test_names_is_reported(self) -> None:
        source = (
            "from tests.corpus import suite_modules\nMODULES = suite_modules()\ndef test_a():\n    pass\n"
        )

        assert _walking_tests(source) == ({}, {"MODULES"})

    def test_a_walker_declared_with_another_population_is_refused(self) -> None:
        """A walker is added to a run by its declared populations, so one declared
        reading the test tree while it reads the application would not run for an
        application change."""
        source = (
            "from tests.corpus import application_modules\n"
            'TREE_GUARDS = {"TestA": ("suite_modules",)}\n'
            "class TestA:\n    def test_a(self):\n        application_modules()\n"
        )

        assert _misdeclared(source) is not None

    def test_a_walker_declared_with_what_it_reads_is_accepted(self) -> None:
        source = (
            "from tests.corpus import application_modules\n"
            'TREE_GUARDS = {"TestA": ("application_modules",)}\n'
            "class TestA:\n    def test_a(self):\n        application_modules()\n"
        )

        assert _misdeclared(source) is None
