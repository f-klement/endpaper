"""What `@pytest.mark.sqlite_only(reason=...)` means, and the guard that keeps it true.

The suite runs on SQLite unless `ENDPAPER_TEST_DATABASE_URL` points it at Postgres.
A test asserting SQLite's own behaviour on purpose (a pragma, the `sqlite_master`
catalogue, dynamic typing, the `sqlite3` driver) carries the mark, and
`tests/conftest.py` skips it on any other engine with the reason it names. So a
Postgres run reports such a test as not applicable. What still fails there is an
application defect on that engine or a test assuming SQLite without the mark, such
as raw SQL calling `datetime()` or a match on SQLite's error wording.

**Only SQLite, and that is deliberate.** A test bound to Postgres is a whole file
that skips itself at module level, as `test_database_tls_on_a_real_server.py`
does, because the coverage register refuses a collected test carrying a skip on
the default run (`test_nothing_collected_is_skipped_or_left_expected_to_fail`).
A mark skipping on SQLite would be exactly that.

**The guard** watches the statements a test executes on the suite's engine, on
whichever engine the run is on. A statement spelled in the test tree that uses
SQLite's own statement (`PRAGMA`) or its reserved namespace (`sqlite_`, which
SQLite keeps for its own objects) fails the test unless it is marked, or unless
the statement, or a call in the test tree on the way to it, sits under
`if ... dialect.name == "sqlite"`, the shape a portable test uses for an SQLite
only step.

What it lets through, stated rather than implied: a SQLite only function or cast
(`typeof`, `CAST(... AS BLOB)`, `char(0)`, `GLOB`), which is an open list rather
than a namespace; a test asserting `engine.dialect.name` without executing
anything; a statement on an engine the test built itself; and a statement sent
through the raw DBAPI cursor, which no SQLAlchemy event sees. A statement
SQLAlchemy's own dialect or Alembic spells while reflecting or migrating is
portable by construction and is not the test's.
"""

from __future__ import annotations

import ast
import functools
import re
from collections.abc import Mapping
from pathlib import Path
from types import FrameType
from typing import Any

import sqlalchemy

#: The mark's name, as `pyproject.toml` declares it.
MARK = "sqlite_only"

TESTS = Path(__file__).resolve().parent

#: As the module names itself rather than resolved, because a frame carries the
#: same spelling and a resolved path would miss it under a symlinked environment.
_SQLALCHEMY = Path(sqlalchemy.__file__).parent
#: Statements spelled here are SQLAlchemy's own, such as the `PRAGMA table_info`
#: behind `inspect(engine).get_columns`, which ports because the dialect does.
_DIALECTS = _SQLALCHEMY / "dialects"

#: `PRAGMA` is SQLite's statement, `pragma_` its table valued form
#: (`SELECT name FROM pragma_table_info('books')`), and `sqlite_` the prefix SQLite
#: reserves for its own tables (`sqlite_master`, `sqlite_sequence`). Without the
#: `pragma_` arm the table valued form passes, because `_` is a word character and
#: `\b` never falls between it and `PRAGMA`. A word merely starting with the letters,
#: such as `pragmatic`, matches neither arm.
_SQLITES_OWN = re.compile(r"\bPRAGMA(?:\b|_\w)|\bsqlite_\w", re.IGNORECASE)

#: The test whose statements the listener in `tests/conftest.py` is judging, and
#: whether it is marked. Set and cleared there by `sqlite_only_sql_is_marked`; a
#: statement outside a test, such as the session's schema build, is judged by
#: nothing. Here rather than in conftest so a test can switch it, which is how
#: `test_sqlite_only.py` proves the listener is registered at all.
JUDGING: dict[str, Any] = {}


def spells_sqlites_own_sql(statement: str) -> bool:
    """Whether the statement uses SQLite's own statement or reserved namespace."""
    return _SQLITES_OWN.search(statement) is not None


def reason_of(args: tuple[object, ...], kwargs: Mapping[str, object]) -> str:
    """The mark's reason, or a refusal naming what is wrong with it.

    A keyword, because a mark called with one class or function as its only
    positional argument decorates it instead. And required, because a skip on
    Postgres that does not say why reads the same as a test nobody looked at.
    """
    reason = kwargs.get("reason")
    if args or set(kwargs) != {"reason"} or not isinstance(reason, str) or not reason.strip():
        raise ValueError(
            f"{MARK} takes one keyword, reason=, naming the SQLite behaviour the "
            f"test asserts; got args={args!r} kwargs={kwargs!r}"
        )
    return reason


def authors_of(frame: FrameType | None) -> tuple[tuple[Path, int], ...]:
    """Where the statement executing under `frame` was spelled, then every line of
    the test tree it was called through, innermost first. Empty when the test
    tree did not spell it.

    Walks outward past SQLAlchemy's own plumbing to the first caller. A frame in
    SQLAlchemy's dialects on the way out means the dialect wrote the statement,
    so nobody in the test tree did. The first frame outside SQLAlchemy is the
    author: under `tests/` it is the test's, anywhere else (the application,
    Alembic) it is not.

    **The callers are kept** because a gate in any of them keeps the statement
    off another engine: a helper in `tests/helpers.py` called under
    `if connection.dialect.name == "sqlite":` runs only on SQLite, though its own
    line is under no gate.
    """
    while frame is not None:
        path = Path(frame.f_code.co_filename)
        if not path.is_relative_to(_SQLALCHEMY):
            break
        if path.is_relative_to(_DIALECTS):
            return ()
        frame = frame.f_back
    found: list[tuple[Path, int]] = []
    while frame is not None:
        path = Path(frame.f_code.co_filename).resolve()
        if path.is_relative_to(TESTS):
            found.append((path, frame.f_lineno))
        elif not found:
            return ()
        frame = frame.f_back
    return tuple(found)


def needs_the_mark(authors: tuple[tuple[Path, int], ...]) -> bool:
    """Whether a statement with these `authors_of` runs on another engine too:
    the test tree spelled it, and no line on the way to it is gated."""
    return bool(authors) and not any(is_gated(*author) for author in authors)


def _is_the_sqlite_comparison(node: ast.AST) -> bool:
    """`<anything>.dialect.name == "sqlite"`, either way round."""
    if not isinstance(node, ast.Compare) or len(node.ops) != 1 or not isinstance(node.ops[0], ast.Eq):
        return False
    sides = (node.left, node.comparators[0])

    def names_the_dialect(side: ast.AST) -> bool:
        return (
            isinstance(side, ast.Attribute)
            and side.attr == "name"
            and isinstance(side.value, ast.Attribute)
            and side.value.attr == "dialect"
        )

    def is_sqlite(side: ast.AST) -> bool:
        return isinstance(side, ast.Constant) and side.value == "sqlite"

    return any(names_the_dialect(a) and is_sqlite(b) for a, b in (sides, sides[::-1]))


@functools.cache
def _gated_spans(path: Path) -> tuple[tuple[int, int], ...]:
    """The line spans of this file that run only on SQLite: the test and the body
    of every `if` whose condition compares the dialect's name with `"sqlite"`.

    **Not the `else`**, which is exactly the branch that runs on another engine.
    """
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    spans: list[tuple[int, int]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.If) and any(_is_the_sqlite_comparison(n) for n in ast.walk(node.test)):
            last = node.body[-1]
            spans.append((node.lineno, last.end_lineno or last.lineno))
    return tuple(spans)


def is_gated(path: Path, line: int) -> bool:
    """Whether `line` of `path` runs only when the dialect is SQLite."""
    return any(start <= line <= end for start, end in _gated_spans(path))
