"""`.env.example` is operator documentation, and it goes stale silently.

It documented **three** of thirty variables for four months, because nothing
connected it to the code: `config.py` grew `AUTH_MODE`, then eight `LDAP_*`,
then seven `MAIL_*` and two Telegram keys, and none of those changes had any
reason to touch a sample file.

So this reads `config.py` rather than restating it. A hand written list of
expected names would be the same defect one level up: a rule written as its
instances regenerates the hole the moment the instances change. That is the
lesson `conftest.py` learned when its masking guard went vacuous because it
popped one environment variable by name instead of reading `_ENV_OVERRIDES`.

**Names only.** The prose in the sample is free to change without breaking
this; only a variable appearing or disappearing does.

`docs/configuration.md` is held to every name the application or a migration
reads, and to the default each literal read falls back to. A row there is a line of a table
whose header line starts `| Variable |` exactly, with one name in backticks as
its first cell; a table headed any other way is not read at all.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path
from typing import NamedTuple

import config
import credentials
import settings_store
from tests.corpus import BACKEND, shipped_modules

REPO = Path(__file__).resolve().parents[2]
SAMPLE = REPO / ".env.example"
CONFIG = Path(config.__file__)
REFERENCE = REPO / "docs" / "configuration.md"

#: Read by `config.py` and deliberately absent from the sample, with the reason.
#:
#: Empty today, and that is the point: an entry here is a decision somebody made
#: on purpose, not a name that slipped through.
UNDOCUMENTED: dict[str, str] = {}

TREE_GUARDS = {"TestTheConfigurationReferenceDocumentsWhatTheCodeReads": ("shipped_modules",)}


def _read_by_config() -> set[str]:
    """Every environment name `config.py` reads, from both places it reads them.

    Two sources, and missing either is how this test would pass while being
    wrong: a direct `os.getenv("X")`, and the `_ENV_OVERRIDES` table that maps a
    settings key to the variable that pins it.
    """
    tree = ast.parse(CONFIG.read_text())
    direct = {
        node.args[0].value
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr in {"getenv", "get"}
        and node.args
        and isinstance(node.args[0], ast.Constant)
        and isinstance(node.args[0].value, str)
        and node.args[0].value.isupper()
        and len(node.args[0].value) > 3
    }
    return direct | set(config._ENV_OVERRIDES.values())


def _documented() -> set[str]:
    return set(re.findall(r"^([A-Z][A-Z0-9_]*)=", SAMPLE.read_text(), re.MULTILINE))


class TestTheSampleDocumentsWhatTheCodeReads:
    def test_every_variable_the_code_reads_is_in_the_sample(self):
        missing = _read_by_config() - _documented() - set(UNDOCUMENTED)
        assert not missing, (
            "These are read by config.py and absent from .env.example, so an "
            f"operator has no way to know they exist: {sorted(missing)}"
        )

    def test_the_sample_documents_nothing_the_code_ignores(self):
        """The other direction, and it is the quieter failure: a variable that
        was renamed leaves a line somebody will set and wonder about."""
        stale = _documented() - _read_by_config()
        assert not stale, f"These are in .env.example and read nowhere in config.py: {sorted(stale)}"

    def test_the_reader_finds_both_sources(self):
        """A tripwire. If `_read_by_config` ever returns only one of its two
        sources the tests above pass while enforcing half the rule, which is the
        shape of every guard defect this repository has found."""
        found = _read_by_config()
        assert "SECRET_KEY" in found, "the direct os.getenv pass found nothing"
        assert "MAIL_PASSWORD" in found, "the _ENV_OVERRIDES pass found nothing"

    def test_every_secret_carries_a_placeholder_that_states_its_requirement(self):
        """A secret with an empty value reads as optional, and a plausible fake
        is the kind of thing that gets shipped. Both are refused."""
        text = SAMPLE.read_text()
        for name in ("SECRET_KEY", "MAIL_PASSWORD", "TELEGRAM_BOT_TOKEN", "LDAP_BIND_PASSWORD"):
            match = re.search(rf"^{name}=(.*)$", text, re.MULTILINE)
            assert match, f"{name} is not in the sample"
            value = match.group(1).strip()
            assert value.startswith("replace-with-"), (
                f"{name} should carry a placeholder naming what it needs, not {value!r}"
            )


#: Each read whose name is computed, by its module, the function it sits in and
#: the expression that names it, with where the test finds those names instead.
#: Keyed by call site rather than by module, so a helper added beside one of these
#: (`_flag(name, default)` in `config.py`) is a new site and refused: its names
#: would otherwise owe no row.
COMPUTED_NAMES: dict[tuple[str, str, str], str] = {
    ("config.py", "env_override", "name"): "the values of `_ENV_OVERRIDES`, added by `_operator_variables`",
    ("credentials.py", "from_env", "env_variable_name(source)"): "owed one row spelled `<SOURCE>`",
    ("credentials.py", "is_from_env", "env_variable_name(source)"): "owed one row spelled `<SOURCE>`",
}

#: The directory of development helpers, read by the walk not at all. The
#: premise is who runs a module there: a developer from a checkout, or the
#: pipeline (`python scripts/<name>.py`), never an operator, so what it reads is
#: their environment, not a deployment's. "Never imported" is not the premise:
#: `recover.py` is never imported either, and an operator runs it in the
#: container, so the walk reads it. Two tests hold the premise: the server
#: imports nothing from here, and no operator document offers a command here.
DEVELOPMENT_HELPERS = "scripts"

#: The documents an operator follows, any of which offering a command under
#: `DEVELOPMENT_HELPERS` would make that helper an operator command.
OPERATOR_DOCUMENTS = (REPO / "README.md", REFERENCE, REPO / "docs" / "handbook.md")

#: A path into the helpers, bare or under `backend/`, or a `-m` module name there.
#: The lookbehind keeps `frontend/scripts/` out, which is the frontend's own.
OFFERS_A_HELPER = re.compile(rf"(?<![\w/.-])(?:backend/)?{DEVELOPMENT_HELPERS}/|-m {DEVELOPMENT_HELPERS}\.")

#: Variables whose Default cell describes the fallback rather than spelling the
#: literal, with the reason.
DESCRIBED_DEFAULTS: dict[str, str] = {
    "SECRET_KEY": "the literal is a placeholder startup refuses, not a value to offer",
    "APP_ENV": "empty means production, and the cell says what it means",
    "CREDENTIAL_ENCRYPTION_KEY_FILE": "empty means the key file in DATA_DIR, which the cell names",
}


def _is_environ(node: ast.expr) -> bool:
    """`os.environ`, or `environ` imported by name."""
    if isinstance(node, ast.Attribute):
        return node.attr == "environ" and isinstance(node.value, ast.Name) and node.value.id == "os"
    return isinstance(node, ast.Name) and node.id == "environ"


class _Read(NamedTuple):
    """One environment read: its name, or None where the name is computed, the
    fallback it passes, and where it sits, as the enclosing function and the
    source of the name expression."""

    name: str | None
    fallback: ast.expr | None
    function: str
    spelled: str


def _environment_reads(source: str) -> list[_Read]:
    """Each environment read in one module.

    Reads `os.getenv`, `getenv`, `os.environ.get`, `os.environ[...]` and `in
    os.environ`. A write (`os.environ[...] = ...`) is not a read.
    """
    reads: list[_Read] = []

    def read(name: ast.expr, fallback: ast.expr | None, function: str) -> None:
        literal = name.value if isinstance(name, ast.Constant) and isinstance(name.value, str) else None
        reads.append(_Read(literal, fallback, function, ast.unparse(name)))

    def visit(node: ast.AST, function: str) -> None:
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            function = node.name
        if isinstance(node, ast.Call) and node.args:
            func = node.func
            getenv = (
                isinstance(func, ast.Attribute)
                and func.attr == "getenv"
                and isinstance(func.value, ast.Name)
                and func.value.id == "os"
            ) or (isinstance(func, ast.Name) and func.id == "getenv")
            environ_get = isinstance(func, ast.Attribute) and func.attr == "get" and _is_environ(func.value)
            if getenv or environ_get:
                read(node.args[0], node.args[1] if len(node.args) > 1 else None, function)
        elif isinstance(node, ast.Subscript) and isinstance(node.ctx, ast.Load) and _is_environ(node.value):
            read(node.slice, None, function)
        elif (
            isinstance(node, ast.Compare)
            and len(node.ops) == 1
            and isinstance(node.ops[0], ast.In | ast.NotIn)
            and _is_environ(node.comparators[0])
        ):
            read(node.left, None, function)
        for child in ast.iter_child_nodes(node):
            visit(child, function)

    visit(ast.parse(source), "<module>")
    return reads


def _walked() -> dict[str, Path]:
    """Every shipped module but the development helpers, by its path under `backend/`."""
    return {
        path.relative_to(BACKEND).as_posix(): path
        for path in shipped_modules()
        if path.relative_to(BACKEND).parts[0] != DEVELOPMENT_HELPERS
    }


def _backend_reads() -> dict[str, list[_Read]]:
    return {
        module: reads for module, path in _walked().items() if (reads := _environment_reads(path.read_text()))
    }


def _operator_variables() -> set[str]:
    """Every name the reference owes a row: each literal name a shipped module
    outside the development helpers reads, and the computed ones
    `COMPUTED_NAMES` says where to find."""
    literal = {read.name for reads in _backend_reads().values() for read in reads if read.name is not None}
    return (
        literal
        | set(config._ENV_OVERRIDES.values())
        | set(credentials.ENV_VARIABLES)
        | {credentials.env_variable_name("<source>")}
    )


def _code_defaults() -> dict[str, str]:
    """What each variable falls back to where the code spells it as a literal: the
    second argument of a read, or the stored default of a pinnable setting."""
    defaults = {
        read.name: read.fallback.value
        for reads in _backend_reads().values()
        for read in reads
        if read.name is not None
        and isinstance(read.fallback, ast.Constant)
        and isinstance(read.fallback.value, str)
    }
    for key, name in config._ENV_OVERRIDES.items():
        defaults[name] = settings_store.DEFAULTS.get(key, "")
    return defaults


def _reference_table() -> dict[str, str]:
    """The Default cell of every row in a `| Variable |` table of the reference,
    by the name in its first cell.

    Read by table rather than by any backticked capital, so a name mentioned in
    prose, or a value table such as the TLS modes, is not mistaken for a row.
    """
    rows: dict[str, str] = {}
    in_table = False
    for line in REFERENCE.read_text().splitlines():
        if line.startswith("| Variable |"):
            in_table = True
            continue
        if not line.startswith("|"):
            in_table = False
            continue
        match = re.match(r"\|\s*`([A-Z][A-Z0-9_]*(?:<SOURCE>)?)`\s*\|([^|]*)\|", line)
        if in_table and match:
            rows[match.group(1)] = match.group(2).strip()
    return rows


def _as_written(cell: str) -> str:
    """A Default cell as the value it states: `empty` is the empty string."""
    return "" if cell == "empty" else cell.replace("`", "")


class TestTheConfigurationReferenceDocumentsWhatTheCodeReads:
    def test_every_variable_the_code_reads_has_a_row(self):
        missing = _operator_variables() - set(_reference_table())
        assert not missing, (
            "These are read by the backend and have no row in a Variable table of "
            f"docs/configuration.md: {sorted(missing)}"
        )

    def test_every_row_names_a_variable_the_code_reads(self):
        stale = set(_reference_table()) - _operator_variables()
        assert not stale, f"These have a row in docs/configuration.md and are read nowhere: {sorted(stale)}"

    def test_a_computed_name_is_read_only_where_the_test_knows_its_names(self):
        unknown = sorted(
            site
            for module, reads in _backend_reads().items()
            for read in reads
            if read.name is None and (site := (module, read.function, read.spelled)) not in COMPUTED_NAMES
        )
        assert not unknown, (
            "These read an environment variable whose name the test cannot see, so "
            "no row is owed for it. Spell the name, or add the site to COMPUTED_NAMES "
            f"and its names to _operator_variables, as (module, function, name): {unknown}"
        )

    def test_every_computed_site_the_test_knows_still_reads(self):
        """The other direction: a site renamed or removed leaves an exemption that
        a new read could take over under the old name."""
        sites = {
            (module, read.function, read.spelled)
            for module, reads in _backend_reads().items()
            for read in reads
        }
        assert not set(COMPUTED_NAMES) - sites, f"No longer read: {sorted(set(COMPUTED_NAMES) - sites)}"

    def test_the_server_imports_no_development_helper(self):
        """Half of what lets the walk skip `scripts/`: the server never imports
        from it, so nothing there runs inside a request."""
        importing = sorted(
            module
            for module, path in _walked().items()
            for node in ast.walk(ast.parse(path.read_text()))
            if (isinstance(node, ast.ImportFrom) and (node.module or "").split(".")[0] == DEVELOPMENT_HELPERS)
            or (
                isinstance(node, ast.Import)
                and any(a.name.split(".")[0] == DEVELOPMENT_HELPERS for a in node.names)
            )
        )
        assert not importing, (
            f"These import a development helper, so its reads reach a deployment: {importing}"
        )

    def test_no_operator_document_offers_a_development_helper(self):
        """The other half: an operator is never told to run a helper, which is
        what separates `scripts/` from `recover.py`. A helper offered there reads
        the deployment's environment and owes its names a row."""
        offering = sorted(
            document.name
            for document in OPERATOR_DOCUMENTS
            if OFFERS_A_HELPER.search(document.read_text(encoding="utf-8"))
        )
        assert not offering, f"These offer a command from backend/{DEVELOPMENT_HELPERS}/: {offering}"

    def test_the_reader_finds_a_read_outside_config(self):
        """A tripwire: the walk has to reach past `config.py`, or every module it
        was written to cover goes unread and the first arm stays green."""
        assert "SQLITE_SYNCHRONOUS" in _operator_variables()

    def test_every_literal_default_matches_its_row(self):
        table = _reference_table()
        wrong = {
            name: (table[name], default)
            for name, default in _code_defaults().items()
            if name in table and name not in DESCRIBED_DEFAULTS and _as_written(table[name]) != default
        }
        assert not wrong, (
            f"These rows state a default the code does not fall back to, as (row, code): {wrong}"
        )
