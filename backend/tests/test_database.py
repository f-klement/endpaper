"""Tests for backend/database.py: engine setup and the session dependency."""

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session
from sqlalchemy.pool import QueuePool

import database
from database import Base, engine, get_db


class TestEngine:
    def test_is_pointed_at_the_test_database(self):
        assert "sqlite" in str(engine.url)

    def test_sqlite_thread_check_is_disabled(self):
        """FastAPI runs sync endpoints in a worker thread pool, so a session
        opened on one thread is used on another."""
        assert engine.dialect.name == "sqlite"
        assert Base.metadata.tables


class TestSqlitePragmas:
    """Every one of these is off or too short by default in SQLite."""

    @pytest.fixture
    def pragma(self):
        def _read(name: str):
            with engine.connect() as connection:
                return connection.execute(text(f"PRAGMA {name}")).scalar()

        return _read

    def test_foreign_keys_are_enforced(self, pragma):
        """Off by default, which makes every ForeignKey in models.py and the
        ON DELETE CASCADE on book_tags decorative."""
        assert pragma("foreign_keys") == 1

    def test_a_dangling_reference_is_refused(self, pragma):
        """The pragma reading 1 only proves it is set. This proves it bites."""
        with engine.connect() as connection, pytest.raises(Exception, match="FOREIGN KEY"):
            connection.execute(
                text("INSERT INTO notes (book_id, user_id, content) VALUES (9999, 9999, 'x')")
            )

    def test_the_journal_is_write_ahead(self, pragma):
        """Without WAL a long write, an import or a restore, blocks every read
        for its duration."""
        assert pragma("journal_mode").lower() == "wal"

    def test_a_busy_database_waits_rather_than_erroring(self, pragma):
        assert pragma("busy_timeout") == 5000


class TestForeignKeyIndexes:
    """Migration a17c5b2e94d0. Without these, SQLite scans the child table once
    per deleted parent row now that foreign keys are checked."""

    @pytest.mark.parametrize(
        ("table", "column"),
        [
            ("books", "added_by_user_id"),
            ("user_books", "book_id"),
            ("loans", "book_id"),
            ("loans", "loaned_to_user_id"),
            ("notes", "book_id"),
            ("book_tags", "tag_id"),
        ],
    )
    def test_the_column_leads_an_index(self, table, column):
        with engine.connect() as connection:
            indexes = connection.execute(text(f"PRAGMA index_list('{table}')")).fetchall()
            leading = {
                connection.execute(text(f"PRAGMA index_info('{row[1]}')")).fetchall()[0][2]
                for row in indexes
            }
        assert column in leading


class TestGetDb:
    def test_yields_a_session(self):
        gen = get_db()
        session = next(gen)
        assert isinstance(session, Session)
        gen.close()

    def test_closes_the_session_afterwards(self):
        gen = get_db()
        session = next(gen)
        gen.close()
        assert not session.is_active or session.get_bind() is not None

    def test_each_call_yields_a_distinct_session(self):
        """A shared session would leak uncommitted state between requests."""
        first_gen, second_gen = get_db(), get_db()
        first, second = next(first_gen), next(second_gen)
        assert first is not second
        first_gen.close()
        second_gen.close()


class TestMetadata:
    def test_every_expected_table_is_registered(self):
        assert {
            "users", "books", "tags", "book_tags", "user_books", "loans", "notes"
        } <= set(Base.metadata.tables)


class TestSynchronousIsWhitelisted:
    """`SQLITE_SYNCHRONOUS` reaches a statement that cannot be parameterised.

    `_synchronous()` interpolates its result into `PRAGMA synchronous={...}`, so
    the whitelist is the only thing between an environment variable and SQL. The
    docstring said it could not leak and nothing pinned that, which is the shape
    of a guard that gets simplified away.
    """

    @pytest.mark.parametrize(
        "value",
        ["OFF; DROP TABLE books", "1", "", "  ", "NORMAL --", "FULL; PRAGMA foo"],
    )
    def test_anything_not_on_the_list_falls_back_to_full(
        self, value: str, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("SQLITE_SYNCHRONOUS", value)
        assert database._synchronous() == "FULL"

    @pytest.mark.parametrize(
        ("value", "expected"),
        [("off", "OFF"), ("OFF", "OFF"), (" normal ", "NORMAL"), ("Full", "FULL")],
    )
    def test_a_listed_mode_is_accepted_in_any_case(
        self, value: str, expected: str, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("SQLITE_SYNCHRONOUS", value)
        assert database._synchronous() == expected

    def test_the_default_is_durable(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Unset means FULL. This database is somebody's only copy."""
        monkeypatch.delenv("SQLITE_SYNCHRONOUS", raising=False)
        assert database._synchronous() == "FULL"


def _the_queue_pool() -> QueuePool:
    """The engine's pool, narrowed to the class whose defaults the figures are about.

    **The narrowing is what makes the private reads type check**, and it is also the
    premise of both arms: `size`, `_max_overflow` and `_timeout` are `QueuePool`'s,
    and neither figure is a statement about a pool that does not queue. Narrowing
    rather than casting is the honest assertion, because this file's own argument for
    asserting the capacity instead of setting it is that `pool_size` is a `TypeError`
    on a pool that does not queue: a URL producing one makes these figures meaningless
    rather than wrong, and that is worth failing on by name once.
    """
    pool = database.engine.pool
    assert isinstance(pool, QueuePool), (
        f"the engine's pool is a {type(pool).__name__}, which has neither of the "
        "defaults the two arms below are about"
    )
    return pool


class TestThePoolsCapacityIsTheFigureTwoArgumentsRestOn:
    """The pool admits fifteen connections, and three comments argue from that.

    **Nothing in this repository sets it.** `create_engine` is called with no
    `pool_size` and no `max_overflow`, so the fifteen is `QueuePool`'s own default
    of five plus ten, and `pyproject.toml` asks for `sqlalchemy>=2.0.38` with no
    upper bound. A bump can move a number that three pieces of reasoning stand on
    without touching a line of this tree.

    **What rests on it.** `metadata._HARDER_AT_ONCE` refuses to let anything wait
    on its semaphore, because a waiter holds one of these for as long as it waits.
    `routers/books.py`'s backfill deadline is derived from how many of them one
    member may hold. Both are arguments about availability, so a silent change is
    the kind nobody notices until a pool is empty.

    **Asserted rather than set**, because the engine is built from a URL that is
    not always file backed and `pool_size` is a `TypeError` on a pool class that
    does not queue. So this is the instrument: it fails on the bump rather than
    after it, and it names the comments to correct.

    The overflow has no public accessor, which is why it is read privately here.
    """

    def test_the_pool_admits_fifteen(self) -> None:
        pool = _the_queue_pool()

        assert pool.size() + pool._max_overflow == 15, (
            "the pool's capacity moved. Three comments argue from fifteen: "
            "`metadata._HARDER_AT_ONCE`, and the backfill's deadline and slot "
            "comments in `routers/books.py`. Correct them, or set the size "
            "explicitly here and say why this number"
        )

    def test_a_waiter_gives_up_rather_than_waiting_for_ever(self) -> None:
        """The other default the availability arguments rest on."""
        assert _the_queue_pool()._timeout == 30.0, (
            "`pool_timeout` moved, which changes how long a request parked on an "
            "exhausted pool holds its worker"
        )
