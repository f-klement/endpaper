import os
from collections.abc import Generator
from typing import Any, Final

from sqlalchemy import String, create_engine, event, exc
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker
from sqlalchemy.sql.functions import FunctionElement

from config import database_url

DATABASE_URL = database_url()

engine = create_engine(
    DATABASE_URL,
    # SQLite guards connections against cross-thread use; FastAPI hands the
    # session to worker threads, so that guard has to be lifted.
    connect_args={"check_same_thread": False} if "sqlite" in DATABASE_URL else {},
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


@event.listens_for(engine, "connect")
def _sqlite_pragmas(connection: Any, _record: Any) -> None:
    """The three settings SQLite does not give you by default.

    Applied per connection, because that is the only scope SQLite has for two
    of them.

    **`foreign_keys`** is off by default, which makes every `ForeignKey` in
    `models.py` and the `ON DELETE CASCADE` on `book_tags` decorative: they
    describe intent and enforce nothing. That is not theoretical here.
    Migration `d4a91f3c72e8` had to delete association rows by hand for
    exactly this reason, and `delete_tag` clears them itself rather than
    trusting the cascade. Turning it on makes the schema mean what it says.

    **WAL** lets a reader and the writer work at once. Without it, any write
    blocks every read for its duration, and this app has writes that are not
    short: an import, a restore, emptying the trash.

    **`busy_timeout`** is what turns the remaining contention into a wait
    rather than an immediate "database is locked" error. Five seconds is long
    enough for any write this app makes and short enough not to hide a
    deadlock.
    """
    if "sqlite" not in DATABASE_URL:
        return
    cursor = connection.cursor()
    try:
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA busy_timeout=5000")
        cursor.execute(f"PRAGMA synchronous={_synchronous()}")
    finally:
        cursor.close()


#: What `PRAGMA synchronous` may be set to. Anything else is refused rather than
#: passed through, because this value is read from the environment and reaches a
#: statement that cannot be parameterised.
_SYNCHRONOUS_MODES: Final = frozenset({"OFF", "NORMAL", "FULL", "EXTRA"})


def _synchronous() -> str:
    """How hard SQLite works to survive a power cut. FULL unless told otherwise.

    **FULL in production and that is not negotiable**: it is what makes a commit
    survive the machine losing power, and this database is somebody's only copy
    of a hand-built catalogue.

    **OFF in the test suite**, set by `tests/conftest.py`, and the reason is
    measurable rather than stylistic. A run performs tens of thousands of
    inserts, each fsynced, into a database deleted at the end of it. The suite
    was measured at 0.68 cores across two workers: it was not computing, it was
    waiting for a disk to acknowledge writes nobody would ever read.

    Durability is meaningless for a database thrown away at the end of the run,
    so this is one of the rare cases where the unsafe setting is the correct
    one, and it is scoped so it cannot leak: an unknown value falls back to
    FULL rather than being passed to SQLite.
    """
    mode = os.getenv("SQLITE_SYNCHRONOUS", "FULL").strip().upper()
    return mode if mode in _SYNCHRONOUS_MODES else "FULL"


# ── Where a query's two dialects differ ──────────────────────────────────────
#
# **Expressions only.** A query module names a concept and the arm for each
# engine lives here, so a second dialect is a list in one file rather than a
# hunt for dialect specific calls across every module that queries.
#
# **The schema's dialect differences are not here and do not belong here**:
# they are the CHECK constraints and partial index clauses in `models.py`, and
# the DDL a deployment actually runs is `migrations/`. Claiming this file as the
# only home for both halves sends a reader to one file and past the half where
# both of this rule's bugs lived.


class MonthBucket(FunctionElement[str]):
    """A "YYYY-MM" label for a timestamp column. The stats group on it.

    `func.strftime` stood at both call sites and is SQLite only, so any other
    engine would raise on the two endpoints that used it. One construct rather
    than a branch at each call site, because the month bucket is one concept
    and both callers group and order by its label.

    An unsupported dialect fails when the query is compiled, by the default
    arm below, rather than emitting a call to a `month_bucket` function no
    database has. `backend/tests/test_dialect_portability.py` pins all three
    arms and the two endpoints.
    """

    inherit_cache = True
    name = "month_bucket"
    type = String()


@compiles(MonthBucket, "sqlite")
def _month_bucket_sqlite(element: MonthBucket, compiler: Any, **kw: Any) -> str:
    # The `%` needs no doubling because SQLite's DBAPI takes qmark parameters.
    # Under a `%` paramstyle it would read as a bind placeholder and the driver
    # would fail on the statement, which is why the Postgres arm below reaches
    # for `to_char`, whose pattern has no `%` in it at all.
    return f"strftime('%Y-%m', {compiler.process(element.clauses, **kw)})"


@compiles(MonthBucket, "postgresql")
def _month_bucket_postgresql(element: MonthBucket, compiler: Any, **kw: Any) -> str:
    return f"to_char({compiler.process(element.clauses, **kw)}, 'YYYY-MM')"


@compiles(MonthBucket)
def _month_bucket_unsupported(element: MonthBucket, compiler: Any, **kw: Any) -> str:
    """Every dialect with no arm above, refused loudly.

    Without this, SQLAlchemy compiles a `FunctionElement` generically and emits
    `month_bucket(...)`, which no database defines: the failure then arrives
    from the server as an unknown function, naming nothing about this app.
    """
    raise exc.CompileError(
        f"MonthBucket has no spelling for the {compiler.dialect.name} dialect. "
        "SQLite and Postgres are the two spelled here; add an arm in "
        "database.py rather than a dialect specific function at a call site."
    )


class Base(DeclarativeBase):
    pass


def get_db() -> Generator[Session]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
