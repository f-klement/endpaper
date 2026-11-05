"""The `sqlite_only` mark's guard: which statements it attributes to a test."""

from __future__ import annotations

import sys
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import pytest
from sqlalchemy import Connection, event, inspect, text

from database import engine
from tests import sqlite_only
from tests.helpers import rows_at_the_engine
from tests.test_schema import _driver

Authors = tuple[tuple[Path, int], ...]


@pytest.fixture
def authors() -> Iterator[list[Authors]]:
    """Where each statement run on the suite's engine was spelled and called
    from, in order."""
    seen: list[Authors] = []

    def record(*_args: object) -> None:
        seen.append(sqlite_only.authors_of(sys._getframe(1)))

    event.listen(engine, "before_cursor_execute", record)
    try:
        yield seen
    finally:
        event.remove(engine, "before_cursor_execute", record)


@contextmanager
def judged(*, marked: bool) -> Iterator[list[str]]:
    """Judge the block as a test that is `marked` or not, and hand back what the
    guard recorded against it. The test's own judging is put back after, so the
    entries recorded here are never charged to the test running this."""
    own = dict(sqlite_only.JUDGING)
    recorded: list[str] = []
    sqlite_only.JUDGING.update(marked=marked, seen=recorded)
    try:
        yield recorded
    finally:
        sqlite_only.JUDGING.clear()
        sqlite_only.JUDGING.update(own)


def _foreign_keys_on(connection: Connection) -> int:
    """A helper in the test tree, the shape a gated step is extracted into.
    Answers the line that executes."""
    line = sys._getframe().f_lineno + 1
    connection.execute(text("PRAGMA foreign_keys=ON"))
    return line


class TestTheGuardKnowsWhoSpelledAStatement:
    @pytest.mark.sqlite_only(reason="executes a pragma")
    def test_a_statement_written_in_a_test_is_the_test_s(self, authors) -> None:
        with engine.connect() as connection:
            line = sys._getframe().f_lineno + 1
            connection.execute(text("PRAGMA foreign_keys"))

        assert authors == [((Path(__file__).resolve(), line),)]

    def test_a_statement_the_dialect_writes_while_reflecting_is_nobody_s(self, authors) -> None:
        """On SQLite this is `PRAGMA table_info`, which a test asking for the
        columns did not write and which ports because the dialect does."""
        inspect(engine).get_columns("books")

        assert authors
        assert set(authors) == {()}

    @pytest.mark.sqlite_only(reason="executes a pragma")
    def test_an_unmarked_test_running_a_pragma_is_recorded(self) -> None:
        """The listener in conftest is the whole guard: without it registered,
        every arm here still passes and no unmarked test is ever refused."""
        with judged(marked=False) as recorded, engine.connect() as connection:
            line = sys._getframe().f_lineno + 1
            connection.execute(text("PRAGMA foreign_keys"))

        assert [entry.split(": ", 1)[0] for entry in recorded] == [f"tests/test_sqlite_only.py:{line}"]


class TestTheRowCounterIsSeenAsWellAsTheStatements:
    """The row counter reads through a `sqlite3` row factory rather than a
    statement, so the listener never sees it, and it records itself instead."""

    @pytest.mark.sqlite_only(reason="runs the row counter, a sqlite3 row_factory")
    def test_an_unmarked_caller_is_recorded(self) -> None:
        with judged(marked=False) as recorded, rows_at_the_engine():
            pass

        assert len(recorded) == 1
        assert recorded[0].startswith("tests/helpers.py:")
        assert "row counter" in recorded[0]

    @pytest.mark.sqlite_only(reason="runs the row counter, a sqlite3 row_factory")
    def test_a_caller_under_the_sqlite_gate_is_not(self) -> None:
        with judged(marked=False) as recorded:
            if engine.dialect.name == "sqlite":
                with rows_at_the_engine():
                    pass

        assert recorded == []

    @pytest.mark.sqlite_only(reason="runs the row counter, a sqlite3 row_factory")
    def test_a_marked_caller_is_not(self) -> None:
        with judged(marked=True) as recorded, rows_at_the_engine():
            pass

        assert recorded == []


class TestTheDriverConnectionIsSeenToo:
    """`_driver` in `test_schema.py` hands a test the `sqlite3` connection,
    whose reads are no statement the listener sees, so it records itself. Without
    its call, a copy of its marked caller left unmarked is green on SQLite."""

    @pytest.mark.sqlite_only(reason="reads the sqlite3 connection under a SQLAlchemy one")
    def test_an_unmarked_caller_is_recorded(self) -> None:
        with engine.connect() as connection, judged(marked=False) as recorded:
            _driver(connection)

        assert len(recorded) == 1
        assert recorded[0].startswith("tests/test_schema.py:")
        assert "sqlite3 driver connection" in recorded[0]


class TestAStatementUnderTheSqliteGateIsAllowed:
    SOURCE = (
        "def step(connection):\n"
        '    if connection.dialect.name == "sqlite":\n'
        '        connection.execute(text("PRAGMA foreign_keys=ON"))\n'
        "    else:\n"
        '        connection.execute(text("SET x"))\n'
        '    connection.execute(text("PRAGMA foreign_keys=ON"))\n'
    )

    @pytest.fixture
    def path(self, tmp_path: Path) -> Path:
        written = tmp_path / "gated.py"
        written.write_text(self.SOURCE, encoding="utf-8")
        return written

    def test_the_body_of_the_gate_is_gated(self, path: Path) -> None:
        assert sqlite_only.is_gated(path, 3)

    def test_the_else_branch_is_not(self, path: Path) -> None:
        assert not sqlite_only.is_gated(path, 5)

    def test_a_statement_after_the_gate_is_not(self, path: Path) -> None:
        assert not sqlite_only.is_gated(path, 6)

    @pytest.mark.sqlite_only(reason="executes a pragma")
    def test_a_helper_called_under_the_gate_is_gated_by_its_caller(self, authors) -> None:
        spelled = called = 0
        with engine.connect() as connection:
            if connection.dialect.name == "sqlite":
                called = sys._getframe().f_lineno + 1
                spelled = _foreign_keys_on(connection)

        here = Path(__file__).resolve()
        assert authors == [((here, spelled), (here, called))]
        assert not sqlite_only.needs_the_mark(authors[0])

    @pytest.mark.sqlite_only(reason="executes a pragma")
    def test_the_same_helper_called_outside_any_gate_needs_the_mark(self, authors) -> None:
        with engine.connect() as connection:
            _foreign_keys_on(connection)

        assert len(authors) == 1
        assert sqlite_only.needs_the_mark(authors[0])


class TestWhatCountsAsSqlitesOwnSql:
    @pytest.mark.parametrize(
        "statement",
        [
            "PRAGMA foreign_keys",
            "SELECT name FROM pragma_table_info('books')",
            "SELECT sql FROM sqlite_master",
            "DELETE FROM sqlite_sequence",
        ],
    )
    def test_the_pragma_and_the_reserved_namespace_are(self, statement: str) -> None:
        assert sqlite_only.spells_sqlites_own_sql(statement)

    @pytest.mark.parametrize(
        "statement",
        ["SELECT id FROM books", "SELECT 'pragmatic'"],
        ids=["portable", "a word starting pragma"],
    )
    def test_a_portable_statement_is_not(self, statement: str) -> None:
        assert not sqlite_only.spells_sqlites_own_sql(statement)


class TestTheMarkNamesItsReason:
    def test_the_reason_is_what_the_skip_says(self) -> None:
        assert sqlite_only.reason_of((), {"reason": "reads a pragma"}) == "reads a pragma"

    @pytest.mark.parametrize(
        ("args", "kwargs"),
        [((), {}), ((), {"reason": " "}), (("reads a pragma",), {}), ((), {"reason": "x", "why": "y"})],
        ids=["absent", "blank", "positional", "a second keyword"],
    )
    def test_anything_else_is_refused(self, args: tuple[object, ...], kwargs: dict[str, object]) -> None:
        with pytest.raises(ValueError, match="reason="):
            sqlite_only.reason_of(args, kwargs)
