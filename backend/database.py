import logging
import os
import ssl
from collections.abc import Generator, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

from sqlalchemy import String, create_engine, event, exc
from sqlalchemy.engine import make_url
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker
from sqlalchemy.sql.functions import FunctionElement

from config import database_ssl_mode, database_ssl_root_cert, database_url

logger = logging.getLogger("endpaper.database")

DATABASE_URL = database_url()


# ── How much this deployment insists on TLS to the database ──────────────────
#
# **This is weaker than the standard this repository holds itself to on its
# other credentialed outbound connection, and the gap is deliberate.**
# `mailer.send` builds `ssl.create_default_context()` itself, takes no context
# from a caller, has no setting that relaxes it, and fails on a server that will
# not upgrade. Here the default tolerates a server that will not upgrade. The
# owner ruled it: a self hosted Postgres is overwhelmingly a container on the
# same compose network with no certificate at all, so the mail module's posture
# as a default would refuse the ordinary deployment on an upgrade nobody asked
# for. What the ruling does close is the *silence*: the downgrade is logged, and
# an operator who wants the mail module's posture can have it by name.
#
# **The vocabulary is libpq's**, because an operator reaching for this has met it
# in `psql`, in a connection string and in every managed Postgres' documentation,
# and inventing a second spelling for a decision they have already made once is
# how a setting gets set wrong.
#
# **`allow` is the one libpq name absent, and absent rather than approximated.**
# It means "cleartext first, TLS only if the server insists", and pg8000 has no
# spelling for it: `_make_socket` sends the SSLRequest before anything else or
# not at all. A name accepted here that did something else would be worse than
# a name that is refused.


@dataclass(frozen=True)
class _Posture:
    """What one mode name promises, in the only terms pg8000 acts on.

    **`refuse_downgrade` is also "hand pg8000 a context", and that is one fact
    rather than two.** `pg8000.core._make_socket` raises `Server refuses SSL`
    exactly when the server declined the upgrade **and** `orig_ssl_context is not
    None`; with `None` it falls through and the session continues in the clear.
    So a context is not only what verification is carried in, it is the whole of
    what makes a refusal loud. Read against pg8000 1.31.5's source.

    `verify_mode` and `check_hostname` describe the context that gets built, so
    they are read only when one is.
    """

    #: Whether the SSLRequest is sent at all.
    attempt: bool
    #: Whether a server that declines the upgrade is a failure.
    refuse_downgrade: bool
    #: What the context checks. `prefer` leaves pg8000 to build its own, which
    #: is `CERT_NONE` with `check_hostname` off; these two say so rather than
    #: leaving a reader to go and look.
    verify_mode: ssl.VerifyMode
    check_hostname: bool


#: What `DATABASE_SSL_MODE` may be set to, and what each name buys.
#:
#: **The population is derived from this table and asserted in
#: `tests/test_database.py`**, so a sixth name reds there by name rather than
#: arriving with no arm of its own.
_SSL_MODES: Final[Mapping[str, _Posture]] = {
    "disable": _Posture(False, False, ssl.CERT_NONE, False),
    "prefer": _Posture(True, False, ssl.CERT_NONE, False),
    "require": _Posture(True, True, ssl.CERT_NONE, False),
    "verify-ca": _Posture(True, True, ssl.CERT_REQUIRED, False),
    "verify-full": _Posture(True, True, ssl.CERT_REQUIRED, True),
}

#: Applied when the environment says nothing.
#:
#: **`prefer` is exactly what this engine did before the setting existed**, so no
#: deployment's behaviour changes on the upgrade that adds it: `ssl_context=None`
#: is pg8000's own default and is what `connect_args={}` left it at. The one
#: visible difference is the warning below.
DEFAULT_SSL_MODE: Final = "prefer"

#: The only driver any of this reaches. `ssl_context` is pg8000's connect
#: argument and nothing else's, so handing it to another driver would be a
#: `TypeError` at the first connection rather than a posture.
_PG8000: Final = "postgresql+pg8000"


def _ssl_context(mode: str, ca_file: str) -> bool | ssl.SSLContext | None:
    """The `ssl_context` connect argument one mode name resolves to.

    Three of pg8000's four accepted values are reached from here, and each means
    something a context cannot say: `False` is "never send the SSLRequest",
    `None` is "send it and accept either answer". Anything else is a context,
    and handing one over is what turns a declined upgrade into a raise.

    **No socket is opened and none can be**, which is what makes the per mode
    arms in `tests/test_database.py` able to read the hostname check and the
    verify mode off the thing the driver will actually use.
    """
    posture = _SSL_MODES[mode]
    if not posture.attempt:
        return False
    if not posture.refuse_downgrade:
        return None
    # `cafile=` **replaces** the default store rather than adding to it, which is
    # `create_default_context`'s own documented behaviour and libpq's for
    # `sslrootcert`. `config.database_ssl_root_cert` is where that is stated for
    # an operator.
    context = ssl.create_default_context(cafile=ca_file or None)
    # Hostname first, in this order, for every mode. `check_hostname` cannot be
    # true while `verify_mode` is `CERT_NONE`, and `create_default_context`
    # hands back both set, so clearing the flag before relaxing the mode is the
    # one ordering that raises on none of the modes that reach here.
    context.check_hostname = posture.check_hostname
    context.verify_mode = posture.verify_mode
    return context


def _ssl_connect_args(url: str, mode: str, ca_file: str) -> dict[str, Any]:
    """The TLS half of `connect_args`, with every refusal this setting has.

    **A TLS setting the connection cannot honour is refused, never ignored.**
    Both refusals below are one rule: a deployment that set something and got
    nothing reads its own compose file afterwards and believes the connection is
    protected. An ignored setting is how that belief survives.
    """
    if make_url(url).drivername != _PG8000:
        if mode or ca_file:
            raise RuntimeError(
                "DATABASE_SSL_MODE and DATABASE_SSL_ROOT_CERT are read only for a "
                f"`{_PG8000}://` URL, and this deployment's DATABASE_URL is not one. "
                "Unset them, or point DATABASE_URL at the server you meant."
            )
        return {}

    chosen = mode or DEFAULT_SSL_MODE
    if chosen not in _SSL_MODES:
        raise RuntimeError(
            f"DATABASE_SSL_MODE={chosen!r} is not one of: {', '.join(_SSL_MODES)}. "
            "These are libpq's own names less `allow`, which this driver cannot "
            "spell."
        )

    if ca_file:
        if _SSL_MODES[chosen].verify_mode is not ssl.CERT_REQUIRED:
            raise RuntimeError(
                f"DATABASE_SSL_ROOT_CERT is set and DATABASE_SSL_MODE={chosen} checks "
                "no certificate, so the file would never be read. Set "
                "DATABASE_SSL_MODE=verify-ca or verify-full, or unset the CA file."
            )
        # **Read it here rather than letting the context raise.** This runs in
        # the container, and the overwhelmingly likely failure is a path that
        # exists on the host and was never mounted, which `ssl` reports as a
        # bare `FileNotFoundError` naming neither the variable nor the reason.
        if not Path(ca_file).is_file():
            raise RuntimeError(
                f"DATABASE_SSL_ROOT_CERT={ca_file!r} is not a file this process can "
                "see. In a container the CA has to be mounted in, and the path is the "
                "one inside the container rather than the one on the host."
            )

    return {"ssl_context": _ssl_context(chosen, ca_file)}


def _connect_args(url: str, mode: str, ca_file: str) -> dict[str, Any]:
    """Everything handed to the driver that the URL cannot carry."""
    args: dict[str, Any] = {}
    if "sqlite" in url:
        # SQLite guards connections against cross-thread use; FastAPI hands the
        # session to worker threads, so that guard has to be lifted.
        args["check_same_thread"] = False
    args.update(_ssl_connect_args(url, mode, ca_file))
    return args


#: **Read once, beside the engine they configure.** A connection argument is
#: baked into a built engine, so a later environment change cannot move it and a
#: per connection read would report a mode the pool is not using. The raw value
#: is kept too, because empty and `prefer` mean different things to the refusal
#: above: one is a deployment that said nothing, the other one that chose.
_SSL_MODE_AS_SET: Final = database_ssl_mode()
_SSL_ROOT_CERT: Final = database_ssl_root_cert()
SSL_MODE: Final = _SSL_MODE_AS_SET or DEFAULT_SSL_MODE

engine = create_engine(
    DATABASE_URL,
    connect_args=_connect_args(DATABASE_URL, _SSL_MODE_AS_SET, _SSL_ROOT_CERT),
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

#: Whether the downgrade check below has anything to look at. Derived once: the
#: listener runs per physical connection and re parsing the URL there would be a
#: parse per connection to answer a question the URL settles at import.
_SPEAKS_PG8000: Final = make_url(DATABASE_URL).drivername == _PG8000

def _speaks_postgres(url: str) -> bool:
    """Whether a URL names the Postgres dialect, whatever drives it.

    **The dialect, where the check above takes the driver, and the difference
    is deliberate.** That one reads a private pg8000 attribute, so naming the
    driver is what makes it honest. This one emits standard SQL every Postgres
    driver carries, and gating it on pg8000 would leave a deployment that
    swapped the driver carrying the defect with nothing saying so. The caveat
    on that argument is that the dependency file pins one driver, so the other
    spellings are a shape this answers for rather than a deployment that
    exists.

    **A function rather than an inline expression, because a gate written as a
    substring test is a mutation nothing could see.** `"postgresql" in url` is
    the spelling somebody reaches for and it answers `True` for
    `sqlite:///./postgresql.db`. Parsing the URL is what refuses that, and
    `TestTheZoneGateReadsTheDialectAndNotTheDriver` drives this rather than
    re-deriving the same expression beside the rule, which is what the first
    version of those arms did: they asserted a fact about SQLAlchemy and
    nothing about this gate.
    """
    return make_url(url).get_backend_name() == "postgresql"


#: Whether the session zone listener below has anything to set. Derived once,
#: for the reason the check above is.
_SPEAKS_POSTGRES: Final = _speaks_postgres(DATABASE_URL)


def _is_encrypted(dbapi_connection: Any) -> bool | None:
    """Whether this connection's socket is wrapped, or `None` for "no answer".

    **Three outcomes rather than two, and the third is the point.** The socket
    is read off pg8000's own `_usock`, a private attribute, because the driver
    publishes nothing else that distinguishes an upgraded connection from one
    that fell back. A two outcome probe would report "cleartext" whenever it
    could not read the socket at all, which is an alarm nobody believes twice.

    **`None` has two causes and this does not claim to tell them apart.** pg8000
    sets `_usock` at connect and sets it back to `None` in `close`, so a renamed
    attribute and an already closed connection arrive here identically. Naming
    one of them in the message would be a guess: the earlier wording blamed the
    driver for moving, which is false on a closed connection.

    **The listener below can only ever meet the first**, because it runs on the
    `connect` event, where the socket has just been made. The ambiguity is
    reachable only by calling this directly, which the real server arms do.
    That the attribute is there at all is not left to a reading: the pipeline's
    Postgres job asserts this answers `False` rather than `None` against a
    server with no TLS.
    """
    socket = getattr(dbapi_connection, "_usock", None)
    if socket is None:
        return None
    return isinstance(socket, ssl.SSLSocket)


@event.listens_for(engine, "connect")
def _say_so_when_the_session_is_in_the_clear(connection: Any, _record: Any) -> None:
    """The half of the owner's ruling that `prefer` carries: never silently.

    Only `prefer` can get here and be surprised. `disable` asked for cleartext,
    and every other mode hands pg8000 a context, which makes a declined upgrade
    an exception from the driver rather than a session to report on.

    **Per physical connection, not per request.** SQLAlchemy fires `connect`
    when the pool opens a socket, so a cleartext server costs one line per
    connection the pool opens and not one per query.
    """
    if SSL_MODE != "prefer" or not _SPEAKS_PG8000:
        return
    encrypted = _is_encrypted(connection)
    if encrypted is None:
        logger.error(
            "Cannot tell whether the database connection is encrypted: the driver "
            "handed back no socket to read. Set DATABASE_SSL_MODE=require or stronger "
            "to have the driver refuse a downgrade instead of relying on this check."
        )
    elif not encrypted:
        logger.warning(
            "The database server declined TLS, so this connection carries the password "
            "and every row in the clear. DATABASE_SSL_MODE is prefer, which tolerates "
            "that; set it to require, verify-ca or verify-full to refuse it."
        )


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



#: The session setting every naive timestamp column on Postgres is cast
#: through, and the one value that makes the two writers of those columns
#: agree.
#:
#: Not an environment knob. A deployment that wants local wall clock in the
#: database has to change the columns, not this: the application's own writes
#: are naive UTC and would not move with it.
#:
#: **That sentence is held by two arms rather than stated**, because the
#: neighbour three screens up does read the environment and reaches a
#: statement that cannot be parameterised, so this file already contains the
#: shape somebody would copy. `TestTheSessionZoneIsALiteralAndNotAnEnvironmentRead`
#: holds both halves: that this value is a literal, and that the statement
#: below interpolates this name and nothing else. **One arm held only the
#: first**, and a read moved into the interpolation passed it.
_SESSION_TIME_ZONE: Final = "UTC"


@event.listens_for(engine, "connect")
def _pin_the_postgres_session_zone(connection: Any, _record: Any) -> None:
    """Pin the session zone, because every naive timestamp is cast through it.

    **Measured against a real Postgres 18.6 whose own zone is
    America/New_York**, rather than inferred from compiling the metadata. The
    thirty one `DateTime` columns in `models.py` are declared without
    `timezone=True`, and sixteen of them carry `server_default=func.now()`,
    which compiles to `now()`: a `timestamptz` implicitly cast into `TIMESTAMP
    WITHOUT TIME ZONE`, and **that cast reads the session `TimeZone`**. On that
    server one row took the database side default and the application's own
    value in the same statement, and they landed four hours apart. With this
    set they land equal.

    **UTC and not the server's zone, because the other writer is already
    fixed.** The application writes `datetime.now(UTC).replace(tzinfo=None)`.
    So this is what makes two writers of one column agree, not a preference
    about how to store time.

    **Per physical connection, like the pragmas above, because the setting is
    session scoped.** Measured on the same server: `RESET TIME ZONE` puts a
    session back on the server's own, so nothing inherits this from elsewhere.

    **Autocommit around the statement, and it is the whole of why this works.**
    Measured with pg8000 over three connections: issued plainly, the zone reads
    `UTC` until the first `rollback` on that connection and `America/New_York`
    for the rest of its life in the pool, which is **every** session the pool
    hands out after the first transaction that rolls back. With autocommit on
    for the statement it survives a rollback, a commit and the connection being
    handed out again. Remove the two assignments and the listener still sets
    the zone, still passes an arm that reads it on a fresh connection, and
    stops working in production, which is what
    `backend/tests/test_database.py::test_the_statement_runs_with_autocommit_on`
    holds.

    **Rows written before this landed keep the zone they were written in.**
    A Postgres deployment away from UTC has database side timestamps in local
    wall clock and application side ones in UTC, in the same columns, and
    nothing here moves them: this stops the divergence growing and does not
    repair it.

    **A repair needs the writer per row as well as the offset, and the writer
    is not recorded either.** A column carrying a database side default also
    takes application writes, and those rows are already in the target zone,
    so a blanket shift corrupts exactly the rows that were right. Both facts
    are absent from the rows, which is why this is a migration somebody has to
    decide about rather than something this listener can do.

    **SQLite reaches none of this and that is not an oversight.** There,
    `func.now()` compiles to `CURRENT_TIMESTAMP`, which is UTC by definition,
    so the column already agrees with the application. It also means **no arm
    in the suite can observe this listener running**, since the suite is
    SQLite: the arms below call it directly and the pipeline's Postgres job is
    where it meets a server.
    """
    if not _SPEAKS_POSTGRES:
        return
    # **No early return on a connection that is already autocommitting.** The
    # statement has to run on every physical connection whatever state the
    # driver hands it in, and an `if connection.autocommit: return` added here
    # reddened none of the twelve arms until one of them asserted the
    # statements as well as the flag.
    was_autocommitting = connection.autocommit
    connection.autocommit = True
    cursor = connection.cursor()
    try:
        # **Nothing catches this.** A `SET TIME ZONE` that fails is a
        # connection whose timestamps will disagree with the application's, so
        # the pool handing it out is worse than the connection failing.
        cursor.execute(f"SET TIME ZONE '{_SESSION_TIME_ZONE}'")
    finally:
        # **The order of these two is not load bearing and no arm holds it.**
        # Said here because every other line in this block is: closing a
        # cursor runs no statement, so swapping them changes nothing, and a
        # reader looking for the reason would otherwise invent one.
        cursor.close()
        connection.autocommit = was_autocommitting

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
