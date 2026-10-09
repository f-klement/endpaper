"""What a rule written in one engine's own SQL IS, once there are two engines.

SQLite is what the shipped image creates and what CI runs; Postgres is the
supported optional drop in. A CHECK constraint is where the two part, because
the bounds in `models.py` are written in SQLite's dialect: `GLOB`, `instr`,
`char(0)`, `typeof` and `length(CAST(x AS BLOB))` have no Postgres spelling,
`= 1` on a boolean is a type error there, and the NUL arms have nothing to say
on an engine whose `text` cannot hold one.

**One construct rather than a branch at each site**, for `database.MonthBucket`'s
reason: the rule is one concept and the spelling is per engine. Both halves stay
where the rule is, so a reviewer reads the two arms side by side and the SQLite
one against `git show` of the revision that installed it.

## Why a construct and not a string

**No compile can see inside a CHECK written as a string.** `CheckConstraint`
takes text and SQLAlchemy emits it verbatim, so rendering every table in
`Base.metadata` against the Postgres dialect raised nothing on a schema that
could not be created at all: measured 2026-09-17, all 22 tables rendered, nine of
them carrying SQLite only SQL inside a CHECK. A `DialectSQL` is a
`ColumnElement`, so the compiler visits it and a dialect with no arm is refused
where it is rendered rather than by the server, later, as a syntax error.

## The three arms, and the fourth that is not a dialect

`sqlite` and `postgresql` are the two spellings. **Any other named dialect
raises**, rather than falling through to a generic rendering, which is
`MonthBucket`'s rule and the reason it is restated at this site: a silent
fallthrough hands one engine another engine's security bound.

**`default` is not a database and is answered with the SQLite arm.**
`str(constraint.sqltext)` compiles against SQLAlchemy's `DefaultDialect`, whose
`name` is `"default"`, and that is how every reader of a constraint's text in
this tree asks what a bound says: `tests/test_house_rules.py` walks
`Base.metadata` for byte arms, enum lists and column bounds and compares each
against the constraints a **SQLite** database reports. Answering those with the
SQLite arm keeps that comparison the one it has always been. No `Engine` can
reach this arm: `create_engine` resolves a concrete dialect and every concrete
dialect names itself. `tests/test_dialect.py::TestTheStringifierIsNotAnEngine`
is what stops that sentence going stale.

## No SQL lives here

This module holds the dispatch and the shape a revision states a swapped rule
in, and no SQL at all. Every spelling stays at its own site, which is what lets a
revision stay frozen while the dispatch under it moves: a third engine is an arm
here, a field on `SwappedRule`, and a branch at every site, never a constant here
that changes what a revision installed.
"""

from typing import Any, Final, NamedTuple

from sqlalchemy import exc
from sqlalchemy.engine import Connection, Dialect
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.sql.expression import ColumnElement

#: SQLAlchemy's name for the dialect `str()` uses. Not a database.
_STRINGIFIER: Final = "default"


class DialectSQL(ColumnElement[Any]):
    """One rule, spelled once per engine.

    Each arm is the whole expression rather than a fragment, so the pair reads
    against itself and against the revision that installed the SQLite one.

    Untyped on purpose: it stands in a CHECK constraint, where SQLAlchemy needs
    something to render and not something to compare, and in
    `for_bind` below, where the arms are whole statements.
    """

    inherit_cache = True

    def __init__(self, *, sqlite: str, postgresql: str) -> None:
        self.sqlite = sqlite
        self.postgresql = postgresql


@compiles(DialectSQL, "sqlite")
def _dialect_sql_sqlite(element: DialectSQL, compiler: Any, **kw: Any) -> str:
    return element.sqlite


@compiles(DialectSQL, "postgresql")
def _dialect_sql_postgresql(element: DialectSQL, compiler: Any, **kw: Any) -> str:
    return element.postgresql


@compiles(DialectSQL)
def _dialect_sql_unsupported(element: DialectSQL, compiler: Any, **kw: Any) -> str:
    """Every other dialect refused, and `str()` answered with the live engine.

    Without the raise, SQLAlchemy renders a `ColumnElement` through whatever
    generic path it has and a third engine silently receives one of these two
    spellings inside a security bound. The module docstring carries why
    `default` is not that case.
    """
    if compiler.dialect.name == _STRINGIFIER:
        return element.sqlite
    raise exc.CompileError(
        f"DialectSQL has no spelling for the {compiler.dialect.name} dialect. "
        "SQLite and Postgres are the two spelled here; add an arm in "
        "backend/dialect.py and a branch at every site, rather than letting one "
        "engine receive another engine's rule."
    )


class SwappedRule(NamedTuple):
    """One CHECK a revision replaces, in both directions and on both engines.

    **Named fields rather than positions**, because a reader of any one of these
    tables wants two of the six and a third engine would otherwise widen every
    signature that unpacks one. `before` is what `downgrade()` installs and is
    checked against the schema the revision **found**: `drop_constraint` takes a
    name, so `upgrade()` never reads it and a wrong one breaks only the way back,
    in the one situation nobody is watching.
    """

    table: str
    constraint: str
    before: str
    before_pg: str
    after: str
    after_pg: str


def for_bind(bind: Connection | Dialect, *, sqlite: str, postgresql: str) -> str:
    """The arm this connection's engine wants, as text.

    For the places a rule is executed as a statement rather than rendered into
    DDL: a data migration's `UPDATE` and a downgrade's `DELETE`. It compiles a
    `DialectSQL`, so the refusal above is the only one in this module and a
    third dialect is refused identically wherever it arrives.
    """
    dialect = bind.dialect if isinstance(bind, Connection) else bind
    return str(DialectSQL(sqlite=sqlite, postgresql=postgresql).compile(dialect=dialect))
