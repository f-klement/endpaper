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
from typing import Final

import pytest

from tests import corpus
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
        if function.__module__ == corpus.__name__
        and not name.startswith("_")
        and name != "is_vendored"
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
                str(path.relative_to(root)) if isinstance(path, Path) else path
                for path in population(root)
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
        roots = {
            path.name for path in application_modules() if path.parent == BACKEND
        }
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

        assert sorted(
            str(path) for path in left_out if path.suffix == ".py" and not path.name.startswith(".")
        ) == []
        assert left_out, "the backend holds files that are not Python"


#: Every published module under `backend/tests` that walks a tree itself, and how many calls.
#:
#: **Equality**, so a new walk reds by name and so does one removed without its
#: row moving. A guard needing a corpus asks `tests/corpus.py` for one by name;
#: a row here is a walk that cannot, and says why.
#:
#: **A module the mirror strips states its own count, in `WALKS_OF_MY_OWN`**,
#: because this file publishes and a row naming a stripped module would fail
#: in a mirror clone, which does not carry it. Which modules those are is read
#: off the declaration the publish gate already demands of them.
WALKS: Final = {
    # The home.
    "corpus.py": 1,
    # The instruments the arming above compares the populations against, which
    # must not route through the walk they check.
    "test_corpus.py": 2,
}

def _source(path: Path) -> str:
    """A module's text with its line endings as written.

    `_stated` asks `declares` of it, which follows the gate in ending a line only
    at a newline. Universal newlines would turn a bare carriage return into one,
    and call internal a module the gate publishes.
    """
    return path.read_text(encoding="utf-8", newline="")


def _stated(source: str, relative: str) -> int:
    """How many walks a module is allowed: its row here, or its own statement if it is internal."""
    if not declares(source.encode("utf-8")):
        return WALKS.get(relative, 0)
    tree = ast.parse(source)
    for node in tree.body:
        if (
            isinstance(node, ast.AnnAssign | ast.Assign)
            and "WALKS_OF_MY_OWN"
            in [
                target.id
                for target in (node.targets if isinstance(node, ast.Assign) else [node.target])
                if isinstance(target, ast.Name)
            ]
            and isinstance(node.value, ast.Constant)
            and isinstance(node.value.value, int)
        ):
            return node.value.value
    return 0


def _walk_calls(source: str) -> int:
    """How many calls in `source` read a tree rather than one directory.

    **By name, and plain about it**: `rglob`; `walk` on anything but `ast`, or
    bare where `os` gave it; `glob` or `iglob` whose pattern is a `**` literal
    or is not a literal at all. **A pattern this cannot read counts**, because a
    named constant or an f-string is the first spelling an author writes, and
    assuming it does not recurse would make naming it the evasion.

    A bare `glob` or `iglob` imported from `glob` is asked the same question,
    under whatever name the import binds.

    Past it: a hand rolled `iterdir` or `scandir` recursion, `os.fwalk`,
    `pkgutil.walk_packages`, a bound method held in a variable or handed to
    `functools.partial` or `map`, and a `git ls-files` subprocess. Each takes a
    deliberate act rather than the line a guard's author writes first. The
    import spellings this reads by name close structurally with a name
    resolver rather than with a further spelling here.
    """
    tree = ast.parse(source)
    from_os = {
        alias.asname or alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module == "os"
        for alias in node.names
        if alias.name == "walk"
    }
    from_glob = {
        alias.asname or alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module == "glob"
        for alias in node.names
        if alias.name in {"glob", "iglob"}
    }
    count = 0
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if isinstance(node.func, ast.Name):
            if node.func.id in from_os:
                count += 1
            elif node.func.id in from_glob:
                count += _may_recurse(node)
            continue
        if not isinstance(node.func, ast.Attribute):
            continue
        name = node.func.attr
        receiver = node.func.value
        if name == "rglob":
            count += 1
        elif name == "walk":
            count += not (isinstance(receiver, ast.Name) and receiver.id == "ast")
        elif name in {"glob", "iglob"}:
            count += _may_recurse(node)
    return count


def _may_recurse(call: ast.Call) -> bool:
    """Whether a `glob` call's pattern is a `**` literal, or one this cannot read."""
    keywords = {keyword.arg: keyword.value for keyword in call.keywords}
    pattern = call.args[0] if call.args else keywords.get("pattern", keywords.get("pathname"))
    if not (isinstance(pattern, ast.Constant) and isinstance(pattern.value, str)):
        return True
    return "**" in pattern.value


def _private_reads(source: str) -> list[str]:
    """Every private name of `tests/corpus.py` that `source` imports or reads.

    By the two spellings the tree uses, `from tests.corpus import ...` and an
    attribute on the module bound by `from tests import corpus`, under any
    alias. Only a name that import binds is asked, so a local variable called
    `corpus` is not. Past it: `import tests.corpus` with or without an alias,
    and a relative import, which close with a name resolver rather than a
    spelling here; `getattr`, `importlib` and `__dict__`, which are deliberate.
    """
    tree = ast.parse(source)
    bound: set[str] = set()
    found: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module == "tests":
            bound |= {alias.asname or alias.name for alias in node.names if alias.name == "corpus"}
        elif isinstance(node, ast.ImportFrom) and node.module == "tests.corpus":
            found += [alias.name for alias in node.names if alias.name.startswith("_")]
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Attribute)
            and isinstance(node.value, ast.Name)
            and node.value.id in bound
            and node.attr.startswith("_")
            and not node.attr.startswith("__")
        ):
            found.append(node.attr)
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
        sources = {
            path.relative_to(tests).as_posix(): _source(path)
            for path in suite_modules()
        }
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

    def test_a_bare_carriage_return_starts_no_line_for_the_declaration(
        self, tmp_path: Path
    ) -> None:
        """The gate publishes a module whose declaration follows a bare carriage
        return, so its walks are counted from a row here, not from its own word."""
        written = f'"""Notes.\r\r{SENTENCE}\r"""\rWALKS_OF_MY_OWN = 2\r'
        module = tmp_path / "test_walks.py"
        module.write_bytes(written.encode("utf-8"))

        assert not declares(module.read_bytes())
        assert _stated(_source(module), "test_walks.py") == 0
        # The same module with newlines is internal, so the fixture can tell.
        assert _stated(written.replace("\r", "\n"), "test_walks.py") == 2

    def test_no_module_reaches_past_the_populations_into_the_walk(self) -> None:
        """`_walk` takes the caller's own prune, so calling it is a walk that
        decides for itself what is vendored, and the count above cannot see it."""
        tests = BACKEND / "tests"
        reaching = {
            relative: names
            for path in suite_modules()
            if (relative := path.relative_to(tests).as_posix()) not in {"corpus.py", "test_corpus.py"}
            and (names := _private_reads(path.read_text(encoding="utf-8")))
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
        ],
    )
    def test_what_counts_as_reaching_past(self, source: str, names: list[str]) -> None:
        assert _private_reads(source) == names

    def test_an_internal_module_states_its_own_count(self) -> None:
        """The stated count is read off the module, and only off one the gate strips."""
        internal = f'"""{SENTENCE}"""\nWALKS_OF_MY_OWN = 2\n'
        published = '"""Published."""\nWALKS_OF_MY_OWN = 2\n'

        assert _stated(internal, "test_x.py") == 2
        assert _stated(published, "test_x.py") == 0

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
            ("ast.walk(tree)", 0),
            ("def walk(node):\n    pass\nwalk(node)", 0),
        ],
    )
    def test_what_counts_as_a_walk(self, source: str, calls: int) -> None:
        assert _walk_calls(source) == calls
