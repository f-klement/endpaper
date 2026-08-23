import os
from collections.abc import Generator
from typing import Any, Final

from sqlalchemy import create_engine, event
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

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


class Base(DeclarativeBase):
    pass


def get_db() -> Generator[Session]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
