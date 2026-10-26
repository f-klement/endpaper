"""Every dev dependency is pinned exactly, and every runtime dependency is a range.

A dev dependency is any entry of a `[dependency-groups]` group, of
`[build-system].requires` and of `[tool.uv].dev-dependencies` in
`backend/pyproject.toml`, and any entry of `devDependencies` in
`frontend/package.json`: the linters, the type checker, the formatter, the test
runners and their plugins, and the build tools. A runtime dependency is any entry
of `[project].dependencies`, of `[project.optional-dependencies]`, and of
`dependencies`, `optionalDependencies` and `peerDependencies`. The rule is read
off the group an entry sits in, so an entry added to either side is held without
a list here learning its name, and a dev tool written into a runtime group is
held as runtime. Why the split falls there is the decision on dev dependencies
being exact in `docs/decisions.md`.

**A dependency table neither side names is a failure**, so a new one is classified
here by whoever adds it rather than passing unread.

Exact means one version: `==` in Python, and in npm a bare version, an `npm:`
alias to one, or a git URL fixed to a full commit. A runtime npm range has a floor
and a ceiling, so `*`, `latest` and a bare `>=` are refused. A dev entry naming a
runtime library carries that library's runtime range, so the dev group does not
fix the version locked for the runtime one. A Python git or URL pin in a dev group
is refused, a shape this tree does not use.

An override in `package.json`, and a `resolutions` entry, holds a transitive dev
tool only, and exactly: it names the dev dependency that pulls the package in, in
`_OVERRIDDEN_FOR`, and it stays inside the range that parent asks for.
"""

from __future__ import annotations

import json
import re
import tomllib
from pathlib import Path
from typing import Any, cast

from packaging.requirements import Requirement
from packaging.utils import canonicalize_name

_REPO = Path(__file__).resolve().parents[2]

#: Each override, by the dev dependency whose own range for it the override must
#: satisfy. vite asks for rolldown `~1.2.12`, so lock maintenance moved rolldown
#: with vite held exactly, and rolldown 1.2.14 broke the autopatch night of
#: 2026-10-24. **A pin in `devDependencies` would not hold it**: the parent's own
#: range still resolves the copy the parent loads. **bun applies an override
#: whatever the parent asks**, so a vite release asking for a rolldown the override
#: refuses would run on the old one and say nothing; the range arm below reds that
#: vite merge request instead. The frozen install every pod runs refuses an
#: override the lock does not record.
_OVERRIDDEN_FOR = {"rolldown": "vite"}

#: What `bun add --exact` writes, and the `=` and `v` spellings semver reads as the
#: same single version.
_NPM_EXACT = re.compile(r"[=v]?\d+\.\d+\.\d+(-[0-9A-Za-z.-]+)?")

#: A git dependency fixed to a full commit, in the spellings npm and bun read.
_NPM_GIT_COMMIT = re.compile(r"(git\+(https|ssh)://\S+|(github:)?[\w.-]+/[\w.-]+)#[0-9a-f]{40}")

_NPM_VERSION = r"[=v]?\d+(\.\d+){0,2}(-[0-9A-Za-z.-]+)?"

#: A range with a floor and a ceiling: caret, tilde, an `x` range, or `>=a <b`.
_NPM_RANGE = re.compile(rf"[\^~]{_NPM_VERSION}|\d+(\.\d+)?\.[x*]|>=?\s*{_NPM_VERSION}\s+<=?\s*{_NPM_VERSION}")

#: `npm:<name>@<specifier>`, an alias; the specifier after it is what the rule reads.
_NPM_ALIAS = re.compile(r"npm:(@[\w.-]+/)?[\w.-]+@(?P<wanted>.*)")

#: Each `package.json` key holding dependencies, by the rule its entries keep.
_FRONTEND_TABLES = {
    "devDependencies": "dev",
    "dependencies": "runtime",
    "optionalDependencies": "runtime",
    "peerDependencies": "runtime",
    "overrides": "override",
    "resolutions": "override",
    # Names or metadata, with no specifier to hold.
    "bundleDependencies": "names",
    "bundledDependencies": "names",
    "peerDependenciesMeta": "names",
    "trustedDependencies": "names",
}

#: A key npm, bun or yarn reads as holding dependencies, so a table to classify.
_FRONTEND_TABLE_KEY = re.compile(r"(?i).*dependenc.*|resolutions|overrides|catalogs?|workspaces|pnpm")

#: Each `pyproject.toml` path holding requirements, by the rule its entries keep.
#: A `[dependency-groups]` group and an extra are matched by their parent.
_PYTHON_TABLES = {
    ("dependency-groups",): "dev",
    ("build-system", "requires"): "dev",
    ("tool", "uv", "dev-dependencies"): "dev",
    ("project", "dependencies"): "runtime",
    ("project", "optional-dependencies"): "runtime",
}

#: A key uv, pip or a build backend reads as holding requirements.
_PYTHON_TABLE_KEY = re.compile(r"(.*-)?(dependencies|requires)")


def _pyproject() -> dict[str, Any]:
    with (_REPO / "backend/pyproject.toml").open("rb") as f:
        return tomllib.load(f)


def _manifest() -> dict[str, Any]:
    return cast(dict[str, Any], json.loads((_REPO / "frontend/package.json").read_text()))


def _python_exact(requirement: str) -> bool:
    """Whether the specifier admits one version: a single `==` or `===` with no wildcard."""
    specs = list(Requirement(requirement).specifier)
    return len(specs) == 1 and specs[0].operator in {"==", "==="} and not specs[0].version.endswith(".*")


def _python_tables(node: Any, path: tuple[str, ...] = ()) -> dict[tuple[str, ...], Any]:
    """Every path in `pyproject.toml` whose key names requirements, wherever it sits."""
    found: dict[tuple[str, ...], Any] = {}
    if isinstance(node, dict):
        for key, value in node.items():
            here = (*path, key)
            if here in _PYTHON_TABLES or _PYTHON_TABLE_KEY.fullmatch(key):
                found[here] = value
            else:
                found |= _python_tables(value, here)
    return found


def _python_entries(side: str) -> list[str]:
    entries: list[str] = []
    for path, value in _python_tables(_pyproject()).items():
        if _PYTHON_TABLES.get(path) != side:
            continue
        # A group or an extra is a table of lists; an `{include-group = ...}`
        # table names another group, which is checked itself.
        lists = value.values() if isinstance(value, dict) else [value]
        entries += [entry for entry in (e for lst in lists for e in lst) if isinstance(entry, str)]
    return entries


def _python_runtime_ranges() -> dict[str, set[str]]:
    # A set per name: a library in the dependencies and in an extra has two ranges.
    ranges: dict[str, set[str]] = {}
    for e in _python_entries("runtime"):
        ranges.setdefault(canonicalize_name(Requirement(e).name), set()).add(str(Requirement(e).specifier))
    return ranges


def _frontend_entries(side: str, manifest: dict[str, Any] | None = None) -> list[tuple[str, str]]:
    """Every `(name, specifier)` on one side. A list, because a name keyed merge lets the
    last table hide an earlier entry: `dependencies.react = "*"` behind a peer range."""
    manifest = _manifest() if manifest is None else manifest
    return [
        (name, wanted)
        for key, rule in _FRONTEND_TABLES.items()
        if rule == side
        for name, wanted in manifest.get(key, {}).items()
    ]


def _npm_unaliased(wanted: str) -> str:
    alias = _NPM_ALIAS.fullmatch(wanted)
    return alias["wanted"] if alias else wanted


def _npm_exact(wanted: str) -> bool:
    return bool(_NPM_EXACT.fullmatch(_npm_unaliased(wanted)) or _NPM_GIT_COMMIT.fullmatch(wanted))


def _npm_range(wanted: str) -> bool:
    return bool(_NPM_RANGE.fullmatch(_npm_unaliased(wanted).strip()))


def test_every_dependency_table_is_classified() -> None:
    # Unknown is red rather than unread: a loose entry there would pass every arm below.
    python = [path for path in _python_tables(_pyproject()) if path not in _PYTHON_TABLES]
    frontend = [
        key for key in _manifest() if _FRONTEND_TABLE_KEY.fullmatch(key) and key not in _FRONTEND_TABLES
    ]
    assert (python, frontend) == ([], [])


def test_every_python_dev_dependency_is_exact() -> None:
    runtime = _python_runtime_ranges()

    def held(entry: str) -> bool:
        name = canonicalize_name(Requirement(entry).name)
        if name in runtime:
            return str(Requirement(entry).specifier) in runtime[name]
        return _python_exact(entry)

    assert [entry for entry in _python_entries("dev") if not held(entry)] == []


def test_every_python_runtime_dependency_is_a_range() -> None:
    # A bare name is refused with an exact pin: it drops the floor the code was written against.
    runtime = _python_entries("runtime")
    unranged = [e for e in runtime if _python_exact(e) or not Requirement(e).specifier]
    assert unranged == []


def test_a_name_in_two_tables_is_read_in_each() -> None:
    manifest = {"dependencies": {"react": "*"}, "peerDependencies": {"react": "^19.0.0"}}
    assert [wanted for _, wanted in _frontend_entries("runtime", manifest)] == ["*", "^19.0.0"]


def test_every_frontend_dev_dependency_is_exact() -> None:
    dev = _frontend_entries("dev")
    assert [(name, wanted) for name, wanted in dev if not _npm_exact(wanted)] == []


def test_every_frontend_runtime_dependency_is_a_range() -> None:
    runtime = _frontend_entries("runtime")
    assert [(name, wanted) for name, wanted in runtime if not _npm_range(wanted)] == []


def test_every_override_is_exact_and_held_for_a_dev_dependency() -> None:
    # Missing reds too: without it lock maintenance moves rolldown inside vite's range.
    dev = {name for name, _ in _frontend_entries("dev")}
    overrides = _frontend_entries("override")
    loose = [(name, wanted) for name, wanted in overrides if not _NPM_EXACT.fullmatch(wanted)]
    unowned = [name for name, _ in overrides if _OVERRIDDEN_FOR.get(name) not in dev]
    missing = [name for name in _OVERRIDDEN_FOR if name not in {name for name, _ in overrides}]
    assert (loose, unowned, missing) == ([], [], [])


def _bun_lock() -> dict[str, Any]:
    # bun writes JSON with trailing commas, which `json` refuses.
    text = (_REPO / "frontend/bun.lock").read_text()
    return cast(dict[str, Any], json.loads(re.sub(r",(\s*[}\]])", r"\1", text)))


def _satisfies(version: str, wanted: str) -> bool:
    """Whether `version` is inside `wanted`: exact, `~` or `^`, the forms these parents use."""
    m = re.fullmatch(r"([~^]?)(\d+)\.(\d+)\.(\d+)", wanted)
    assert m, f"a range this cannot read: {wanted!r}"
    floor = tuple(int(part) for part in m.groups()[1:])
    have = tuple(int(part) for part in version.split("."))
    if m.group(1) == "~" or (m.group(1) == "^" and floor[0] == 0 and floor[1] > 0):
        return have >= floor and have[:2] == floor[:2]
    if m.group(1) == "^" and floor[0] > 0:
        return have >= floor and have[0] == floor[0]
    return have == floor


def test_each_override_satisfies_the_range_its_parent_asks_for() -> None:
    packages = _bun_lock()["packages"]
    # An override that is loose or names no parent is the test above's to refuse.
    held = [
        (name, wanted.lstrip("=v"), packages[_OVERRIDDEN_FOR[name]][2]["dependencies"][name])
        for name, wanted in _frontend_entries("override")
        if name in _OVERRIDDEN_FOR and _NPM_EXACT.fullmatch(wanted)
    ]
    assert [entry for entry in held if not _satisfies(entry[1], entry[2])] == []
