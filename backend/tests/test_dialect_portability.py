"""What holds a second dialect's spelling in place, and what does not.

SQLite is the target and what CI runs. Postgres is the supported optional drop
in, and since the dialect branches landed it is one: the whole chain applies to
head there and the pipeline's `test:postgres` job runs it. This file holds the
query side and the indexes; `test_dialect.py` holds the construct and the CHECK
constraints, which is where the two engines' SQL actually differs.

## Two facts that decide what an arm here can be worth

**Compiling against a dialect does not refuse an unknown function.** Measured
2026-09-17: `select(func.strftime(...)).compile(dialect=postgresql.dialect())`
renders `strftime(%(strftime_2)s, books.added_at)` and raises nothing. So
"it compiles for Postgres" is worth almost nothing on its own; only a construct
whose compiler **refuses**, like `MonthBucket`'s default arm, turns a wrong
dialect into an error. Everything else here is a check on the rendered text.

**`Base.metadata` is not the deployed schema.** `main.py`'s `init_db` runs
Alembic and has no `create_all`, on purpose, so the DDL a fresh database
executes lives in `backend/migrations/versions/`. A dialect keyword in
`models.py` is the schema's **description**. The index arm below holds that
description and **cannot see the deployment**, which is where those same two
partial indexes still name SQLite alone.

## What each arm covers

Said plainly, because a guard that reads thorough is believed to be one.

* **`TestTheMonthBucket`** is the construct: two spellings and a refusal for
  every other dialect. It says nothing about who calls it.
* **`TestTheStatsEndpointsUseThePostgresSpelling`** renders **every** statement
  the two month bucket endpoints execute and reads the text: both buckets must
  arrive as `to_char`, and no statement may carry `strftime`. So a `strftime`
  added to one of those queries is caught. **It reaches no other endpoint**, and
  it is a check for one token rather than for portability: a different SQLite
  only function in those same queries renders happily and goes green.
* **`TestPartialIndexesAgreeAcrossDialects`** is parametrised over
  `Base.metadata` rather than a list of known indexes, so a partial index added
  to a model is covered the moment it exists. **It sees the `where` clause
  only**, and it sees `models.py` only. The four revisions that carried a
  `sqlite_where` and no Postgres twin now carry both, so the widening this file
  could not see is closed; the instrument that sees it is the Postgres job,
  which reads `pg_indexes` by running the chain.
"""

import re

import pytest
from sqlalchemy import (
    Column,
    DateTime,
    Index,
    Integer,
    MetaData,
    Table,
    event,
    exc,
    select,
    text,
)
from sqlalchemy.dialects import mysql, postgresql, sqlite
from sqlalchemy.orm import Session
from sqlalchemy.schema import CreateIndex

from database import Base, MonthBucket
from models import Book

SQLITE = sqlite.dialect()
POSTGRESQL = postgresql.dialect()


def _compiled(statement, dialect) -> str:
    return str(statement.compile(dialect=dialect))


class TestTheMonthBucket:
    """One concept, one spelling per dialect, and a refusal for the rest."""

    def test_sqlite_gets_strftime(self):
        assert "strftime('%Y-%m', books.added_at)" in _compiled(
            select(MonthBucket(Book.added_at)), SQLITE
        )

    def test_postgres_gets_to_char(self):
        """`to_char`, and its pattern carries no `%`.

        A `%` in compiled SQL is a bind placeholder under psycopg2's pyformat
        paramstyle, so the SQLite spelling would have to be doubled here and
        nowhere else. Choosing a pattern without one keeps that trap out of the
        dialect that has it.
        """
        compiled = _compiled(select(MonthBucket(Book.added_at)), POSTGRESQL)
        assert "to_char(books.added_at, 'YYYY-MM')" in compiled
        assert "%" not in compiled

    def test_an_unsupported_dialect_is_refused_at_compile_time(self):
        """Loudly, and naming this app.

        Without the default arm, SQLAlchemy compiles a `FunctionElement`
        generically into `month_bucket(...)`, which no database defines: the
        failure then arrives from the server as an unknown function and says
        nothing about where to fix it.
        """
        with pytest.raises(exc.CompileError, match="no spelling for the mysql dialect"):
            _compiled(select(MonthBucket(Book.added_at)), mysql.dialect())

    def test_the_two_dialects_do_not_share_a_spelling(self):
        """The arms above would both pass if one dialect fell through to the
        other's compiler, which is what a missing `@compiles` target looks
        like."""
        assert _compiled(select(MonthBucket(Book.added_at)), SQLITE) != _compiled(
            select(MonthBucket(Book.added_at)), POSTGRESQL
        )


@pytest.fixture
def captured_statements():
    """Every statement executed through a Session while this is held.

    `do_orm_execute` hands over the statement **before** compilation, which is
    what lets the same object be compiled a second time against another dialect.
    A `before_cursor_execute` listener would arrive with SQLite's SQL already
    rendered and could say nothing about Postgres.
    """
    seen: list[object] = []

    def _collect(state) -> None:
        seen.append(state.statement)

    event.listen(Session, "do_orm_execute", _collect)
    try:
        yield seen
    finally:
        event.remove(Session, "do_orm_execute", _collect)


class TestTheStatsEndpointsUseThePostgresSpelling:
    """The two month bucket endpoints, rendered against the other dialect.

    `GET /api/stats` reaches both sites: its own `by_month` aggregation, and
    `Reading.finished_by_month`, which it calls on every request.

    **Rendered and read, not compiled and accepted.** Compilation accepts a
    function Postgres does not have, so the assertion is on the SQL text.
    """

    @pytest.fixture
    def a_finished_book(self, client, admin, make_book):
        """A book with a `finished_at`, which is what puts a row in the second
        month bucket. The status is stamped, never typed in: READ is what
        `_stamp_reading_dates` reads to set the date."""
        book = make_book(admin["headers"], title="Finished")
        response = client.put(
            f"/api/books/{book['id']}/status",
            json={"status": "read"},
            headers=admin["headers"],
        )
        assert response.status_code == 200, response.text
        return book

    def test_both_month_buckets_reach_postgres_as_to_char(
        self, client, admin, a_finished_book, captured_statements
    ):
        """Two statements carry a bucket, `books.added_at` and
        `user_books.finished_at`, and both must arrive at the Postgres spelling.

        The `strftime` half is the one that catches a regression: a call site
        reverted to `func.strftime` renders that token here and compiles
        without complaint everywhere else.
        """
        captured_statements.clear()
        client.get("/api/stats", headers=admin["headers"])
        rendered = [_compiled(statement, POSTGRESQL) for statement in captured_statements]
        bucketed = [sql for sql in rendered if "to_char" in sql]

        assert len(bucketed) == 2, bucketed
        assert any("to_char(books.added_at, 'YYYY-MM')" in sql for sql in bucketed)
        assert any("to_char(user_books.finished_at, 'YYYY-MM')" in sql for sql in bucketed)
        assert not [sql for sql in rendered if "strftime" in sql], "a SQLite spelling survived"

    def test_sqlite_still_answers_with_a_month(self, client, admin, a_finished_book):
        """The live half. Compilation says the SQL renders; this says the engine
        this app actually runs on returns the label the schema promises."""
        body = client.get("/api/stats", headers=admin["headers"]).json()
        assert body["by_month"], body
        assert body["finished_by_month"], body
        for row in body["by_month"] + body["finished_by_month"]:
            assert re.fullmatch(r"\d{4}-\d{2}", row["month"]), row


def _where_clause(index, dialect) -> str:
    """The `WHERE` of a rendered `CREATE INDEX`, or "" when there is none.

    Read off the DDL rather than off `index.dialect_kwargs`, because the kwarg
    is what was written and the DDL is what the database is sent. An index whose
    clause is set for one dialect and not the other has identical kwargs on
    every engine and different SQL on each.
    """
    sql = " ".join(str(CreateIndex(index).compile(dialect=dialect)).split())
    _, separator, where = sql.partition(" WHERE ")
    return where if separator else ""


def _indexes() -> list[Index]:
    return sorted(
        (index for table in Base.metadata.tables.values() for index in table.indexes),
        key=lambda index: index.name or "",
    )


@pytest.mark.parametrize("index", _indexes(), ids=lambda index: index.name)
class TestPartialIndexesAgreeAcrossDialects:
    """Every index in the schema, and both dialects must render one predicate.

    An equality rather than a search for known partial indexes: an index with
    `sqlite_where` and no `postgresql_where` is a **plain unique index** on
    Postgres, a stricter rule than the model states and no error anywhere.
    `uq_loans_one_open_per_book` widened that way means a book can be lent
    exactly once, ever.

    Parametrised over the metadata, so a partial index added to a model is
    covered with no edit here, and an index with no predicate passes as two
    empty strings rather than being excluded by name.

    **This is the description, not the deployment.** Alembic creates the schema,
    so what this class reads is `models.py` and never a revision. The four
    `sqlite_where` keywords that stood alone in `backend/migrations/versions/`
    were the live version of exactly this widening, invisible here, and they now
    carry a `postgresql_where` beside them. Measured 2026-09-17 on PostgreSQL
    16.2 from `pg_indexes` after the chain: `uq_loans_one_open_per_book` and
    `uq_books_isbn_single_copy` had no WHERE clause at all.
    """

    def test_the_predicate_is_the_same_on_both(self, index):
        assert _where_clause(index, SQLITE) == _where_clause(index, POSTGRESQL)


class TestTheIndexArmBites:
    """Most rows above are an equality between two empty strings, so the arm
    would pass on a schema with no partial index at all. These two say which
    indexes it is actually holding, and that it fails when one is wrong."""

    def test_these_are_the_partial_indexes(self):
        """Named rather than counted. A count landing on three says nothing
        about which three, and the next partial index should have to be written
        down here by somebody who checked it carries both clauses."""
        assert {index.name for index in _indexes() if _where_clause(index, SQLITE)} == {
            "uq_books_isbn_single_copy",
            "uq_loans_one_open_per_book",
            "uq_password_reset_requests_live",
        }

    def test_an_index_with_only_a_sqlite_clause_is_caught(self):
        """The evasion, run rather than reasoned about, on a throwaway table so
        that nothing in the real schema is mutated to prove it."""
        metadata = MetaData()
        table = Table(
            "evasion",
            metadata,
            Column("id", Integer),
            Column("closed_at", DateTime),
        )
        index = Index(
            "uq_evasion",
            table.c.id,
            unique=True,
            sqlite_where=text("closed_at IS NULL"),
        )

        assert _where_clause(index, SQLITE) == "closed_at IS NULL"
        assert _where_clause(index, POSTGRESQL) == ""
