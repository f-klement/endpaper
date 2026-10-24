"""What this project wrote, as named populations. A guard asks here and never walks.

**One home for the rule and for every corpus built on it.** The rule is
`is_vendored`. Before this module it lived in `test_house_rules.py`, was
imported under private names by most of the test tree, and was rebuilt inline
by a dozen more modules, each with a name list of its own. Every rebuilt copy
was right on a developer's checkout and wrong in the pipeline, which unpacks a
cache and an environment inside `backend/`; a layer of guards then grew to
police where walks could be written. A population asked for by name has
nothing to police: `test_corpus.py` holds the modules that still walk a tree
themselves, by count, and why each one may.

**Every population takes a root**, so a test can hand it a tree it planted.
The vendored directories that matter are absent from a developer's checkout
and present in the pipeline's, so an assertion over this checkout alone is
vacuous where it is usually run. `test_corpus.py` plants every kind and asks
every population.

**Two roots, because two kinds of question.** The backend populations answer
"which Python here is ours" and default to `backend/`; the repository
populations answer "which file here would git version" and default to the
repository root, where the ignore file lives.

**A test module calling a population names the tests that do**, as a module
level dict bound to `TREE_GUARDS` from each such test to the populations it
calls, because such a test judges files it does not live in, so a run choosing
tests by what a change touched adds it when the change touched a path one of
them holds. A walking test
left out of that set on purpose is named in `TREE_GUARDS_LEFT_OUT` with its
reason. `test_corpus.py` holds each declaration to what its module calls.
"""

from __future__ import annotations

import os
from collections.abc import Callable
from pathlib import Path

# **The only import from this test tree, and it has to stay the only one.**
# Tooling outside the suite loads this file by path, where this tree is not a
# package, and registers the ignore rule under this name before it does. An
# import of any other module from here fails that load; the checker's own test
# names it.
from tests.ignorefile import ignore_patterns, is_ignored

BACKEND = Path(__file__).resolve().parent.parent
REPO = BACKEND.parent

#: The tool directories that carry no leading dot, and so have to be named.
#:
#: **A leading dot means a tool owns it**, which covers `.venv`, `.uv-cache`,
#: `.mypy_cache`, `.ruff_cache`, `.pytest_cache` and the next one without an edit
#: here. A name per tool is what this used to be, and it failed the day the
#: pipeline set `UV_CACHE_DIR` inside `backend/`: a guard reported a dependency's
#: module for reading a member's address, red on every push and green locally.
#:
#: **The last two are an environment rather than a tool.** A virtualenv is
#: `.venv` by convention only, and the pipeline has built one under `backend/`
#: with no dot, after which a walk reported the standard library's own `xml`.
#: Everything installed into an environment sits under one of these two, which
#: is the closed fact the open directory name is not. Public because a copy is
#: kept outside this package, and a test compares the two.
TOOL_DIRECTORIES = frozenset({"__pycache__", "node_modules", "site-packages", "dist-packages"})


def is_vendored(path: Path, root: Path = BACKEND) -> bool:
    """Whether `path` sits under a directory a tool owns, or is itself dotted.

    **A path predicate, answerable without the filesystem**, so a caller can ask
    it of a path that does not exist. Asked against `root` because the dotted
    part is one level deeper from the repository than from `backend/`; the
    wrong root raises `ValueError` rather than answering about nothing.
    """
    return any(part.startswith(".") or part in TOOL_DIRECTORIES for part in path.relative_to(root).parts)


def _environment(directory: Path) -> bool:
    """Whether `directory` is the root of a Python environment, whatever its name.

    **The filesystem half that `is_vendored` cannot ask.** An environment always
    carries `pyvenv.cfg` at its root, and its scripts under `bin/` sit outside
    `site-packages`, so the name rule alone reads them as ours.
    """
    return (directory / "pyvenv.cfg").is_file()


def _walk(top: Path, prune: Callable[[Path], bool]) -> list[Path]:
    """Every file under `top`, sorted, never descending a directory `prune` refuses.

    **Pruned while walking rather than filtered afterwards**, because an
    environment holds tens of thousands of files and no population should pay
    for reading one.
    """
    found: list[Path] = []
    for directory, subdirectories, files in os.walk(top):
        here = Path(directory)
        subdirectories[:] = [name for name in subdirectories if not prune(here / name)]
        found += [here / name for name in files]
    return sorted(found)


# The backend populations. Each is a filter over `unowned_files`, so the rule
# about tools is applied once and the populations differ only in which of this
# project's own directories they take.


def unowned_files(root: Path = BACKEND) -> list[Path]:
    """Every file under `root` in a directory no tool owns, of any suffix.

    **File names are not asked.** A dotted file such as `.gitignore` is this
    project's, and only a directory marks a tool's territory. The Python
    populations below are narrower: they drop a dotted module name too.
    """
    return _walk(root, lambda directory: is_vendored(directory, root) or _environment(directory))


def every_python_file(root: Path = BACKEND) -> list[Path]:
    """Every Python file this project wrote under `root`: the application, the tests, the migrations.

    **The working tree, not what git tracks.** The suite runner ships the
    working tree, so an untracked module is read before it is committed.
    """
    return [path for path in unowned_files(root) if path.suffix == ".py" and not is_vendored(path, root)]


def _relative_parts(path: Path, root: Path) -> set[str]:
    """The parts of `path` below `root`. Matched there rather than against the
    whole path, because a checkout under a directory called `tests` would
    otherwise drop every file it holds."""
    return set(path.relative_to(root).parts)


def application_modules(root: Path = BACKEND) -> list[Path]:
    """Every application module: no tests, no migrations.

    The rules over application semantics read this, because a fixture or a
    generated revision has no share in them.
    """
    return [
        path for path in every_python_file(root) if not {"tests", "migrations"} & _relative_parts(path, root)
    ]


def shipped_modules(root: Path = BACKEND) -> list[Path]:
    """The application and its migrations: what the image carries, a test excluded."""
    return [path for path in every_python_file(root) if "tests" not in _relative_parts(path, root)]


def suite_modules(root: Path = BACKEND) -> list[Path]:
    """Every Python file under `root/tests`.

    **Not named `test_...`**, since pytest would collect a function of that name
    imported into a test module and fail it for want of a `root` fixture.
    """
    return [path for path in every_python_file(root) if path.relative_to(root).parts[0] == "tests"]


def application_sources(root: Path = BACKEND) -> dict[str, str]:
    """`application_modules` read, keyed by the path relative to `root`."""
    return {str(path.relative_to(root)): path.read_text() for path in application_modules(root)}


# The repository populations. They honour the root ignore file, through the one
# reader of it in `tests/ignorefile.py`, because the question there is what the
# repository versions and the ignore file is git's own answer.


def _unignored(root: Path, top: Path, readmit: Callable[[Path], bool]) -> list[Path]:
    patterns = ignore_patterns(root / ".gitignore", refuse_empty=False)

    def prune(directory: Path) -> bool:
        relative = directory.relative_to(root)
        if relative.parts[0] == ".git" or is_ignored(relative, patterns, is_dir=True):
            return True
        owned = is_vendored(directory, root) or _environment(directory)
        return owned and not readmit(relative)

    return [
        path for path in _walk(top, prune) if not is_ignored(path.relative_to(root), patterns, is_dir=False)
    ]


def project_files(root: Path = REPO, *, readmit: Callable[[Path], bool] = lambda _: False) -> list[Path]:
    """Every file under `root` the ignore file does not cover, in a directory no tool owns.

    **Dotted file names are kept**, as `unowned_files` keeps them: a census of
    configuration needs `.gitignore` and `.ruff.toml`.

    **`readmit` is for the guards that must read a directory the tool rule
    prunes**, asked with the path relative to `root`: the scanner that reads
    what the publish gate strips, and the census of a value that may be
    inlined in the pipeline file. `.git` and what the ignore file covers stay
    pruned whatever it answers. A caller passing it states why at its site.
    """
    return _unignored(root, root, readmit)


def markdown_files(root: Path = REPO) -> list[Path]:
    """Every Markdown document the repository versions, a working note it ignores excluded.

    **Wider than what is published, deliberately.** A broken document is broken
    for whoever opens it next, from the mirror or from this checkout.
    """
    return [path for path in project_files(root) if path.suffix == ".md"]


#: The two languages the browser's own source is written in.
_BROWSER_SUFFIXES = frozenset({".ts", ".tsx"})


def browser_modules(root: Path = REPO) -> list[Path]:
    """Every TypeScript module under `frontend/src`, the browser's own source.

    **A rule written in a `.js` or `.mts` there, or under `frontend/public/`, is
    outside this.** None exists, and the frontend's own corpus module refuses a
    new kind of file under `src/` by name.
    """
    top = root / "frontend" / "src"
    if not top.is_dir():
        return []
    return [
        path
        for path in _unignored(root, top, lambda _: False)
        if path.suffix in _BROWSER_SUFFIXES and not is_vendored(path, root)
    ]
