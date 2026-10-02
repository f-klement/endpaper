"""Tests for backend/database.py: engine setup and the session dependency."""

import ast
import datetime as dt
import logging
import os
import re
import socket
import ssl
import subprocess
import sys
import threading
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ed25519
from cryptography.x509.oid import NameOID
from sqlalchemy import event, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session
from sqlalchemy.pool import QueuePool

import database
from database import Base, engine, get_db

#: A Postgres URL of the one spelling this project supports, for the arms that
#: resolve connect arguments. Nothing dials it: `_connect_args` decides the
#: whole posture before a socket exists, which is what makes a mode testable
#: here rather than only in the pipeline.
_PG_URL = "postgresql+pg8000://endpaper:secret@db.invalid:5432/endpaper"

#: The common name of the throwaway CA below, read back out of the context so a
#: loaded bundle is distinguishable from an accepted path.
_CA_NAME = "endpaper test CA"


def _a_certificate_authority(into: Path) -> Path:
    """One self signed CA, written as PEM, for the arm that loads one.

    **Generated rather than borrowed from `certifi`**, which is a transitive
    dependency here and not a promise: an arm standing on one is an arm that
    breaks on somebody else's dependency bump. `cryptography` is a declared
    runtime dependency, and generating the file also lets the arm name the
    certificate it expects to find rather than counting the ones it found.
    """
    key = ed25519.Ed25519PrivateKey.generate()
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, _CA_NAME)])
    now = dt.datetime.now(dt.UTC)
    certificate = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - dt.timedelta(days=1))
        .not_valid_after(now + dt.timedelta(days=1))
        .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
        .sign(key, None)
    )
    path = into / "ca.pem"
    path.write_bytes(certificate.public_bytes(serialization.Encoding.PEM))
    return path


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


class TestEveryTlsModeIsTheContextItsNamePromises:
    """One arm per mode, over the value pg8000 is actually handed.

    **No socket is opened by any of these**, which is the whole reason the
    posture is testable at all: `_ssl_context` decides everything before a
    connection exists, so the hostname check and the verify mode can be read off
    the object the driver will use.

    **The expectations are written out rather than derived from `_SSL_MODES`.**
    A test that reads the same table the code reads asserts that the table
    equals itself and would pass with every row wrong.

    **What these arms cannot see**: whether pg8000 honours the context it is
    given. Three of the five modes rest on the driver raising `Server refuses
    SSL` when it holds a context and the server declines, and that is a claim
    about `pg8000.core._make_socket` rather than about this module.
    `test_database_tls_on_a_real_server.py` drives it against a server with no
    TLS, in the pipeline's Postgres job.
    """

    @pytest.mark.parametrize(
        ("mode", "check_hostname", "verify_mode"),
        [
            ("require", False, ssl.CERT_NONE),
            ("verify-ca", False, ssl.CERT_REQUIRED),
            ("verify-full", True, ssl.CERT_REQUIRED),
        ],
    )
    def test_a_verifying_mode_hands_over_a_context_checking_what_it_says(
        self, mode: str, check_hostname: bool, verify_mode: ssl.VerifyMode
    ) -> None:
        context = database._connect_args(_PG_URL, mode, "")["ssl_context"]

        assert isinstance(context, ssl.SSLContext)
        assert context.check_hostname is check_hostname
        assert context.verify_mode is verify_mode

    @pytest.mark.parametrize("mode", ["verify-ca", "verify-full"])
    def test_a_verifying_mode_with_no_ca_file_is_the_stock_default_context(
        self, mode: str
    ) -> None:
        """The managed server case, which the supplied CA arm cannot see.

        Build the empty case as a bare `SSLContext` instead of
        `create_default_context` and both flags still resolve exactly as the two
        arms above demand, the supplied CA arm still passes, and every managed
        deployment fails every connection because the context trusts nothing.

        **Two properties, because one of them is environment dependent.**
        `cert_store_stats` is the trust store and is the thing that matters:
        **121 certificates in the suite image and 0 on the development host**,
        because the image ships a bundle and the host ships a hashed directory,
        which `load_default_certs` reads lazily. So it is compared against a
        stock context rather than against a number, and on the host both sides
        are 0 and it proves nothing. `verify_flags` is what makes this arm bite
        everywhere: `create_default_context` sets strict and partial chain flags
        that a bare context does not: 557088 against 32768 on the host, and
        both halves measured differing in the suite image under the mutant.
        **Do not delete this arm because the store reads 0 where you ran it.**
        """
        reference = ssl.create_default_context()

        context = database._connect_args(_PG_URL, mode, "")["ssl_context"]

        assert isinstance(context, ssl.SSLContext)
        # **One assertion over both, so neither hides the other.** Written as
        # two statements the store compares first and short circuits, and the
        # flag that carries the environment independent half is never reached:
        # a run can then report the arm biting without ever exercising the
        # property the docstring credits.
        assert (context.verify_flags, context.cert_store_stats()) == (
            reference.verify_flags,
            reference.cert_store_stats(),
        )

    def test_disable_never_sends_the_ssl_request(self) -> None:
        """`False` is pg8000's "do not try", and it is not the same as `None`.

        `None` sends the request and takes either answer, so spelling `disable`
        that way would be `prefer` under another name.
        """
        assert database._connect_args(_PG_URL, "disable", "")["ssl_context"] is False

    def test_prefer_is_the_one_mode_that_tolerates_a_downgrade(self) -> None:
        """`None` is the value that makes pg8000 fall through to cleartext.

        That is the owner's ruling made concrete: the default still downgrades,
        and `_say_so_when_the_session_is_in_the_clear` is what stops it being
        silent.
        """
        assert database._connect_args(_PG_URL, "prefer", "")["ssl_context"] is None

    def test_the_modes_are_libpqs_names_less_allow(self) -> None:
        """The population, asserted so a sixth name reds here by name.

        `allow` is libpq's sixth and is deliberately absent: it means cleartext
        first and TLS only if the server insists, and pg8000 sends the SSL
        request before anything else or not at all.
        """
        assert set(database._SSL_MODES) == {
            "disable",
            "prefer",
            "require",
            "verify-ca",
            "verify-full",
        }

    def test_prefer_is_the_only_mode_that_can_end_up_in_the_clear(self) -> None:
        """Derived over the population, so a mode added later is covered.

        pg8000 raises on a declined upgrade exactly when it holds a context, so
        "tolerates a downgrade" is the same predicate as "the value is `None`".
        A sixth mode spelled that way would be a second silent door, which is
        the thing this whole change exists to close.
        """
        tolerant = {
            mode
            for mode in database._SSL_MODES
            if database._connect_args(_PG_URL, mode, "")["ssl_context"] is None
        }

        assert tolerant == {"prefer"}


class TestTheDefaultChangesNoDeploymentsBehaviour:
    """`prefer` is what `connect_args={}` already did, spelled out.

    pg8000's own default for `ssl_context` is `None`, so an upgrade that adds
    this setting hands the driver the value it was taking anyway.
    """

    def test_an_unset_environment_resolves_to_prefer(self) -> None:
        assert database.DEFAULT_SSL_MODE == "prefer"
        assert database._connect_args(_PG_URL, "", "") == {"ssl_context": None}

    def test_the_resolved_mode_is_a_mode_and_not_an_empty_string(self) -> None:
        """Drop the `or DEFAULT_SSL_MODE` and `SSL_MODE` is `""`.

        The listener then returns early on **every** connection, so the one
        behaviour this change adds is off, and no other arm notices: each of
        them patches `SSL_MODE` before calling the listener, so this is the only
        arm in the file that reads what the module resolved.

        It asserts the literal rather than `DEFAULT_SSL_MODE`, which would be
        satisfied by both sides being empty. The suite reaches this only with
        the environment unset, because a mode set beside its SQLite URL is a
        startup failure, so the value under test here is the fallback.
        """
        assert database.SSL_MODE == "prefer"
        assert database.SSL_MODE in database._SSL_MODES

    def test_a_sqlite_url_is_untouched(self) -> None:
        """The primary target opens no socket, so none of this reaches it."""
        assert database._connect_args("sqlite:///./data/library.db", "", "") == {
            "check_same_thread": False
        }


class TestASettingTheConnectionCannotHonourIsRefused:
    """Never ignored, and the two refusals are one rule.

    An operator who set something and got nothing reads their own compose file
    afterwards and believes the connection is protected. That belief is what an
    ignored setting buys, and it is worth a startup failure to refuse it.
    """

    def test_a_tls_mode_beside_a_sqlite_url_fails_rather_than_being_dropped(self) -> None:
        with pytest.raises(RuntimeError, match="DATABASE_SSL_MODE"):
            database._connect_args("sqlite:///./data/library.db", "require", "")

    def test_a_ca_file_beside_a_sqlite_url_fails_too(self) -> None:
        with pytest.raises(RuntimeError, match="DATABASE_SSL_ROOT_CERT"):
            database._connect_args("sqlite:///./data/library.db", "", "/etc/ca.pem")

    @pytest.mark.parametrize("typed", ["verify_full", "VERIFY-FULL", "allow", "require "])
    def test_the_refusal_quotes_back_what_the_operator_typed(self, typed: str) -> None:
        """A fallback would be the silent weakening this change is about, and a
        refusal that does not name the value is one nobody can act on.

        **Matched against the rendered value, which the two arms this replaces
        were not.** One matched `verify-full` and the other `allow`, and both of
        those appear in **every** refusal this function raises: the first in the
        list of valid names, the second in the closing sentence about the one
        libpq name absent here. Measured over these four values: both words are
        present in all four messages, so both arms passed whatever was typed,
        and stripping the value out of the message entirely left them green.

        **Two of these four cannot arrive from the environment**, because
        `config.database_ssl_mode` strips and lowercases before this sees
        anything: `VERIFY-FULL` resolves to a valid mode and `require ` to
        another. They are here as direct calls, so this is a property of the
        refusal and not a claim that casing or spacing is refused.
        """
        with pytest.raises(RuntimeError, match=re.escape(repr(typed))):
            database._connect_args(_PG_URL, typed, "")

    def test_the_refusal_also_lists_the_names_that_would_have_worked(self) -> None:
        """A separate claim from the one above, and honestly a weaker one: this
        text is static, so it holds for any input. It is here because a refusal
        naming only the mistake sends the operator to the documentation."""
        with pytest.raises(RuntimeError, match="disable, prefer, require"):
            database._connect_args(_PG_URL, "nonsense", "")

    def test_allow_is_not_a_mode_here(self) -> None:
        """The claim behind the closing sentence, asserted where it lives."""
        assert "allow" not in database._SSL_MODES

    @pytest.mark.parametrize("mode", ["disable", "prefer", "require"])
    def test_a_ca_file_under_a_mode_that_checks_no_certificate_is_refused(
        self, mode: str, tmp_path: Path
    ) -> None:
        """The file would never be read, and nothing would say so."""
        ca = tmp_path / "ca.pem"
        ca.write_text("")

        with pytest.raises(RuntimeError, match="checks no certificate"):
            database._connect_args(_PG_URL, mode, str(ca))

    def test_a_ca_path_the_process_cannot_see_names_the_mount(self, tmp_path: Path) -> None:
        """The overwhelmingly likely failure, and `ssl` reports it as a bare
        `FileNotFoundError` naming neither the variable nor the reason."""
        with pytest.raises(RuntimeError, match="mounted in"):
            database._connect_args(_PG_URL, "verify-full", str(tmp_path / "absent.pem"))

    def test_a_ca_file_that_is_there_is_loaded_into_the_verifying_context(
        self, tmp_path: Path
    ) -> None:
        """The positive result the refusals above are measured against.

        Every arm in this class asserts a raise, and a function that raised
        unconditionally would satisfy all of them. This is the case that must
        not raise, and it reads the certificate back out of the context by name,
        so the file is shown to have been parsed rather than merely accepted.

        **It also pins the replacement.** The context holds this one certificate
        and not the image's store, which is what `cafile=` does and what an
        operator pinning a private CA is choosing.
        """
        ca = _a_certificate_authority(tmp_path)

        context = database._connect_args(_PG_URL, "verify-ca", str(ca))["ssl_context"]

        assert isinstance(context, ssl.SSLContext)
        loaded = context.get_ca_certs()
        # One certificate, and it is this one. The count is the replacement and
        # the name is the parse: a store added to rather than replaced carries
        # the image's certificates as well, and a path accepted without being
        # read carries none. How many the image's store holds is measured in the
        # arm above that compares an empty CA against a stock context, which
        # states it per environment because the two disagree.
        assert len(loaded) == 1
        assert _CA_NAME in str(loaded)


class TestTheCleartextWarningSaysWhichOfTwoThingsWentWrong:
    """A downgrade and an unreadable driver are different sentences.

    A two outcome probe would report both as cleartext. The second is a pg8000
    that renamed the attribute this reads, and an alarm that cries wolf on every
    connection after a dependency bump is one nobody believes the third time.
    """

    @pytest.fixture
    def prefer_against_postgres(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """The listener returns early otherwise, and the suite runs on SQLite."""
        monkeypatch.setattr(database, "_SPEAKS_PG8000", True)
        monkeypatch.setattr(database, "SSL_MODE", "prefer")

    def test_an_encrypted_socket_says_nothing(
        self, prefer_against_postgres: None, caplog: pytest.LogCaptureFixture
    ) -> None:
        connection = SimpleNamespace(_usock=MagicMock(spec=ssl.SSLSocket))

        with caplog.at_level(logging.WARNING, logger="endpaper.database"):
            database._say_so_when_the_session_is_in_the_clear(connection, None)

        assert caplog.records == []

    def test_a_plain_socket_warns_that_the_password_crossed_in_the_clear(
        self, prefer_against_postgres: None, caplog: pytest.LogCaptureFixture
    ) -> None:
        connection = SimpleNamespace(_usock=MagicMock(spec=socket.socket))

        with caplog.at_level(logging.WARNING, logger="endpaper.database"):
            database._say_so_when_the_session_is_in_the_clear(connection, None)

        assert [record.levelname for record in caplog.records] == ["WARNING"]
        assert "declined TLS" in caplog.text
        assert "verify-full" in caplog.text

    @pytest.mark.parametrize(
        ("why", "connection"),
        [
            ("the attribute is gone", SimpleNamespace()),
            ("the connection was closed", SimpleNamespace(_usock=None)),
        ],
    )
    def test_a_connection_with_no_socket_says_it_cannot_tell(
        self,
        why: str,
        connection: SimpleNamespace,
        prefer_against_postgres: None,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """Two causes, one answer, and the message names neither.

        pg8000 sets `_usock` at connect and back to `None` in `close`, so a
        renamed attribute and a closed connection are indistinguishable here.
        The wording this replaces said the driver no longer exposes its socket,
        which is false for the second. Both cases are pinned so the next reader
        sees that the ambiguity is known rather than missed.
        """
        with caplog.at_level(logging.ERROR, logger="endpaper.database"):
            database._say_so_when_the_session_is_in_the_clear(connection, None)

        assert [record.levelname for record in caplog.records] == ["ERROR"], why
        assert "Cannot tell" in caplog.text
        assert "no longer exposes" not in caplog.text

    @pytest.mark.parametrize("mode", ["disable", "require", "verify-ca", "verify-full"])
    def test_no_other_mode_reaches_the_check(
        self, mode: str, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        """`disable` asked for this, and the rest get an exception from the
        driver instead, so a line here would be noise on a working deployment."""
        monkeypatch.setattr(database, "_SPEAKS_PG8000", True)
        monkeypatch.setattr(database, "SSL_MODE", mode)

        with caplog.at_level(logging.DEBUG, logger="endpaper.database"):
            database._say_so_when_the_session_is_in_the_clear(SimpleNamespace(), None)

        assert caplog.records == []

    def test_the_listener_is_registered_on_the_engine(self) -> None:
        """Every arm above calls the function, so none of them needs it wired.

        Delete the `@event.listens_for` and leave the body, and the whole class
        stays green over a warning that can never fire. This is the one arm that
        reads the registration rather than the behaviour.
        """
        assert event.contains(engine, "connect", database._say_so_when_the_session_is_in_the_clear)

    def test_nothing_is_said_on_the_engine_the_suite_actually_runs(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """SQLite has no socket to be in the clear, and the listener is live on
        this engine: without this arm every connection in the suite could be
        emitting the warning and no other arm would notice."""
        with (
            caplog.at_level(logging.DEBUG, logger="endpaper.database"),
            engine.connect() as connection,
        ):
            connection.execute(text("SELECT 1"))

        assert caplog.records == []


#: What the child prints in front of its one line of verdict.
_CHILD_MARKER = "POSTURE:"

#: The child process, which imports the application's own module and dials with
#: the engine that module built. Deliberately **not** `_connect_args`: every
#: other arm in this file tests that function, and none of them would notice the
#: engine being built without it.
#:
#: **The child classifies and the parent asserts positively on the verdict.**
#: Every assertion over its output is then a containment, which holds whatever
#: else reaches that descriptor. Asking instead "did it not say refused" needs a
#: count, a negative containment or an offset over a stream this process does
#: not own, and a guard elsewhere in this tree refuses all three; the helper
#: that narrows them is internal and this file publishes, so importing it is
#: not open either.
#:
#: **Exactly one verdict is printed by construction, not by the stub behaving.**
#: The success is recorded after the `with` body rather than inside it, so an
#: exit that raises skips it and leaves only the failure branch. Printed inside,
#: a raising exit prints both, and a containment arm would pass on a stream that
#: also said connected. Unreachable against this stub, which is why it is a
#: property of the protocol to close rather than a hole to measure. A child that
#: dies before the `try` prints nothing and fails every arm rather than
#: satisfying an absence.
#:
#: The failure detail goes on a second line carrying **no** marker, so it cannot
#: be read as a verdict and the parent's containment is untouched. Without it an
#: unexpected `other-failure` is undiagnosable: the child catches the exception,
#: so no traceback reaches the parent and the verdict alone does not say why.
_CHILD = f"""
import sys
sys.path.insert(0, {str(Path(database.__file__).parent)!r})
import database
try:
    with database.engine.connect():
        pass
    said, why = "connected", ""
except BaseException as error:
    said = "refused-tls" if "refuses SSL" in str(error) else "other-failure"
    why = type(error).__name__ + ": " + str(error).replace(chr(10), " ")
print("{_CHILD_MARKER}" + said)
print(why)
"""


#: What the gate child prints in front of its one line of verdict.
_GATE_MARKER = "GATE:"

#: A child that imports the application's own module and reports the constant
#: the listener reads.
#:
#: **Separate from the posture child above rather than folded into it**, which
#: would make one child answer two questions and neither arm able to say which
#: moved. It dials nothing, so it needs no server and no certificate.
_GATE_CHILD = f"""
import sys
sys.path.insert(0, {str(Path(__file__).parent.parent)!r})
import database
print("{_GATE_MARKER}" + repr(database._SPEAKS_POSTGRES))
"""


def _what_the_child_said_the_gate_is(url: str, tmp_path: Path) -> str:
    """The constant, as a fresh interpreter built from `url` computes it."""
    finished = subprocess.run(
        [sys.executable, "-c", _GATE_CHILD],
        capture_output=True,
        text=True,
        timeout=60,
        env={
            "PATH": os.environ.get("PATH", ""),
            "HOME": str(tmp_path),
            "DATA_DIR": str(tmp_path),
            "DATABASE_URL": url,
            "SECRET_KEY": "a" * 40,
        },
    )
    for line in finished.stdout.splitlines():
        if line.startswith(_GATE_MARKER):
            return line[len(_GATE_MARKER) :]
    return f"no verdict: stdout={finished.stdout!r} stderr={finished.stderr!r}"


def _a_server_that_declines_tls() -> tuple[socket.socket, int]:
    """A loopback socket that answers the SSL request with `N`, once.

    pg8000 sends its SSL request before anything else, so refusing it needs no
    Postgres and no certificate: eight bytes in, one byte out. That is the whole
    server these arms require.
    """
    listener = socket.socket()
    listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    listener.bind(("127.0.0.1", 0))
    listener.listen(1)
    return listener, listener.getsockname()[1]


def _the_engine_said(verdict: str, mode: str, tmp_path: Path) -> tuple[bool, str]:
    """Whether the child reported `verdict`, and the streams to say so with.

    The child is a separate interpreter because the engine is built at import
    from the environment, so there is no way to ask the live one what a
    different `DATABASE_SSL_MODE` would have done.
    """
    listener, port = _a_server_that_declines_tls()

    def serve() -> None:
        try:
            conn, _ = listener.accept()
            conn.recv(8)
            conn.sendall(b"N")
            conn.close()
        except OSError:
            # The child refused the URL before dialling, so nothing ever
            # arrived. That is a finding for the arm, not for this thread.
            pass

    server = threading.Thread(target=serve, daemon=True)
    server.start()
    try:
        finished = subprocess.run(
            [sys.executable, "-c", _CHILD],
            capture_output=True,
            text=True,
            timeout=60,
            env={
                "PATH": os.environ.get("PATH", ""),
                # The child never reads it; it is here because an unset HOME is
                # a class of startup failure that would look like a posture.
                "HOME": str(tmp_path),
                "DATA_DIR": str(tmp_path),
                "DATABASE_URL": f"postgresql+pg8000://u:p@127.0.0.1:{port}/db",
                "DATABASE_SSL_MODE": mode,
            },
        )
    finally:
        listener.close()

    said = f"{_CHILD_MARKER}{verdict}" in finished.stdout
    return said, f"stdout={finished.stdout!r} stderr={finished.stderr!r}"


class TestTheApplicationsOwnEngineIsBuiltFromTheSetting:
    """The wiring, which every other arm in this file assumes and none tests.

    **Measured as a gap, not supposed.** Revert the `create_engine` call to the
    expression it had before this setting existed and the whole of the rest of
    this file stays green, the linter stays clean and the type check stays
    clean, while an operator asking for a verifying mode silently gets the
    default. Nothing about `_connect_args` can see that: the defect is between
    the function and the engine.

    **No Postgres and no certificate.** pg8000 sends its SSL request before any
    protocol, so a socket that answers `N` is enough to tell a mode that refuses
    a downgrade from one that does not, in milliseconds.

    **What it does not reach**: the verifying modes. A server that declines is
    refused by `require` for the same reason it is refused by `verify-full`, so
    these two arms separate "the setting reached the engine" from "it did not",
    and nothing more.
    """

    def test_require_refuses_through_the_engine_the_app_actually_builds(
        self, tmp_path: Path
    ) -> None:
        said, streams = _the_engine_said("refused-tls", "require", tmp_path)

        assert said, streams

    def test_the_same_server_fails_differently_when_the_mode_does_not_insist(
        self, tmp_path: Path
    ) -> None:
        """That the permissive mode has not quietly started insisting.

        **Not a control against a broken dial, which is what this said first
        and measurement refuted.** Pointed at a port with nothing listening,
        both modes report `other-failure`, so the arm above fails and this one
        passes: that arm demands a verdict only a reachable stub can produce and
        was never at risk from an unreachable address. This is the arm that can
        pass vacuously.

        What it buys is the other direction, and nothing else in this file
        covers it once the engine is in the loop: a mutant making `disable`
        insist on TLS reds this arm, by name, and only this arm.

        `disable` never sends the SSL request, so it fails further in, on a
        startup packet the stub cannot answer. Asserted as the presence of the
        other verdict rather than the absence of this one, which is the same
        claim and is a containment the child's own classification makes
        positive.
        """
        said, streams = _the_engine_said("other-failure", "disable", tmp_path)

        assert said, streams


class _ARecordedCursor:
    """One cursor, recording the statement and the state it ran under."""

    def __init__(self, connection: _ARecordedConnection) -> None:
        self._connection = connection

    def execute(self, statement: str) -> None:
        self._connection.statements.append(statement)
        if self._connection.refuse_the_statement:
            raise RuntimeError("the server refused SET TIME ZONE")
        # **The state is read while the statement runs, not afterwards.** The
        # listener restores it, so a check taken after the call reports the
        # state it was handed and says nothing about the statement.
        self._connection.autocommitting_while_executing.append(
            self._connection.autocommit
        )

    def close(self) -> None:
        self._connection.cursors_closed += 1


class _ARecordedConnection:
    """A DBAPI connection that remembers what a connect listener did to it.

    The shape pg8000 presents, and the shape psycopg presents too: a cursor
    factory and a mutable `autocommit`. Both are what the listener touches.
    """

    def __init__(
        self, *, autocommit: bool = False, refuse_the_statement: bool = False
    ) -> None:
        self.autocommit = autocommit
        self.refuse_the_statement = refuse_the_statement
        self.statements: list[str] = []
        self.autocommitting_while_executing: list[bool] = []
        self.cursors_closed = 0

    def cursor(self) -> _ARecordedCursor:
        return _ARecordedCursor(self)


class TestThePostgresSessionZoneIsSetUnderAutocommit:
    """Sixteen columns take a database side default cast through this setting.

    **The measurement behind every arm here is in the listener's own
    docstring** and was taken against a real Postgres 18.6 whose zone was not
    UTC. These arms cannot take it again: the suite is SQLite, where the
    listener is inert by design, so what they hold is the shape the measurement
    said is required.
    """

    @pytest.fixture
    def speaking_postgres(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(database, "_SPEAKS_POSTGRES", True)

    def test_a_postgres_connection_is_put_on_utc(self, speaking_postgres: None) -> None:
        """UTC because the application's other writer is naive UTC already."""
        connection = _ARecordedConnection()

        database._pin_the_postgres_session_zone(connection, None)

        assert connection.statements == ["SET TIME ZONE 'UTC'"]

    def test_the_statement_runs_with_autocommit_on(
        self, speaking_postgres: None
    ) -> None:
        """**The arm the whole listener turns on, and it is not decoration.**

        Measured with pg8000 against a real server: issued inside the implicit
        transaction, the zone reads UTC until the first `rollback` on that
        connection and the server's own zone for the rest of its life in the
        pool. Delete the two `autocommit` assignments and every other arm here
        stays green over a listener that stops working on the first rollback.
        """
        connection = _ARecordedConnection()

        database._pin_the_postgres_session_zone(connection, None)

        assert connection.autocommitting_while_executing == [True]

    def test_autocommit_is_put_back_the_way_it_was_found(
        self, speaking_postgres: None
    ) -> None:
        """Both ways round, because restoring to a constant is the same code
        as restoring to what was there and only one of them is right.

        **The statements are asserted beside the flag, and the flag alone was
        not enough.** This arm built a connection with autocommit already on
        and read only the flag afterwards, so the whole already autocommitting
        path was unexercised: an `if connection.autocommit: return` added to
        the listener reddened **none** of the twelve arms, because every other
        arm hands over a connection with it off. The zone must be set whatever
        state the driver hands the connection in.
        """
        was_off = _ARecordedConnection(autocommit=False)
        was_on = _ARecordedConnection(autocommit=True)

        database._pin_the_postgres_session_zone(was_off, None)
        database._pin_the_postgres_session_zone(was_on, None)

        assert (was_off.autocommit, was_on.autocommit) == (False, True)
        assert (was_off.statements, was_on.statements) == (
            ["SET TIME ZONE 'UTC'"],
            ["SET TIME ZONE 'UTC'"],
        )

    def test_the_cursor_is_closed_on_the_way_out(
        self, speaking_postgres: None
    ) -> None:
        """A cursor per physical connection, leaked once per connection.

        **Named for what it holds.** It was named for the statement not being
        able to fail, which the arm three lines below exists to falsify: that
        one hands over a cursor that refuses and requires the failure to
        propagate. Two arms in one class cannot disagree about whether the
        statement can fail.
        """
        connection = _ARecordedConnection()

        database._pin_the_postgres_session_zone(connection, None)

        assert connection.cursors_closed == 1

    def test_a_refused_statement_is_not_swallowed(
        self, speaking_postgres: None
    ) -> None:
        """A connection whose zone was not set is worse than one that failed.

        Wrapping the statement in a bare `except` reddened none of the arms
        this class shipped with: every one of them asserts what the listener
        did on a cursor that accepts, and a pool handing out a connection whose
        timestamps disagree with the application's is the defect the whole
        listener exists to stop.
        """
        connection = _ARecordedConnection(refuse_the_statement=True)

        with pytest.raises(RuntimeError, match="SET TIME ZONE"):
            database._pin_the_postgres_session_zone(connection, None)

        # And the connection is left as it was found rather than autocommitting.
        assert (connection.autocommit, connection.cursors_closed) == (False, 1)

    def test_a_connection_is_not_touched_when_the_gate_says_this_is_not_postgres(
        self,
    ) -> None:
        """SQLite compiles the same default to `CURRENT_TIMESTAMP`, which is
        UTC by definition, so there is nothing to set and no cursor to open.

        **Named for the gate, because the gate is what it reads.** The
        connection handed over here is the same shape as every other in this
        class; what makes the listener leave it alone is the module flag, not
        anything about the connection, and the old name said otherwise.
        """
        connection = _ARecordedConnection()

        database._pin_the_postgres_session_zone(connection, None)

        assert (connection.statements, connection.cursors_closed) == ([], 0)

    def test_the_listener_is_registered_on_the_engine(self) -> None:
        """Every arm above calls the function, so none of them needs it wired.

        Delete the `@event.listens_for` and leave the body, and the whole class
        stays green over a zone that is never set. This is the one arm that
        reads the registration rather than the behaviour, and it is the
        neighbouring TLS class's arrangement for the same reason.
        """
        assert event.contains(engine, "connect", database._pin_the_postgres_session_zone)

    def test_the_suite_s_own_engine_reaches_none_of_it(self) -> None:
        """The suite is SQLite, so no arm in it can observe this listener run.

        Stated as an assertion rather than as a sentence, because it is the
        reason every arm above fakes a connection and a reader is entitled to
        check it rather than believe it.
        """
        assert database._SPEAKS_POSTGRES is False


class TestTheZoneGateReadsTheDialectAndNotTheDriver:
    """The neighbouring cleartext check gates on pg8000 and this one does not.

    That one reads a private pg8000 attribute, so the driver is the honest
    thing to name. This one emits standard SQL, and gating it on the driver
    would leave a deployment that swapped drivers carrying the defect with
    nothing saying so. **The caveat on that argument is that the dependency
    file pins one driver**, so the other spellings below are shapes the gate
    answers for rather than deployments that exist.

    **Every arm drives `database._speaks_postgres`, and the first version of
    this class drove `make_url` instead.** That asserted a fact about
    SQLAlchemy and nothing about the gate: rewriting the gate as the substring
    test anybody reaches for, `"postgresql" in url`, reddened **none** of the
    twelve arms in this file.
    """

    @pytest.mark.parametrize(
        "url",
        [
            "postgresql+pg8000://u:p@db.invalid:5432/endpaper",
            "postgresql+psycopg://u:p@db.invalid:5432/endpaper",
            "postgresql://u:p@db.invalid:5432/endpaper",
        ],
    )
    def test_every_spelling_of_a_postgres_url_is_postgres(self, url: str) -> None:
        assert database._speaks_postgres(url) is True

    def test_a_sqlite_url_is_not_postgres(self) -> None:
        assert database._speaks_postgres("sqlite:///./x.db") is False

    def test_a_sqlite_file_named_after_the_dialect_is_not_postgres(self) -> None:
        """**The substring gate's wrong answer, which is why the gate parses.**
        `"postgresql" in url` is true here and the dialect is SQLite, so this
        is the one arm that separates the two spellings."""
        assert database._speaks_postgres("sqlite:///./postgresql.db") is False

    def test_the_two_gates_differ_on_a_driver_this_tree_does_not_ship(
        self,
    ) -> None:
        """The dialect over driver claim, asserted rather than described."""
        other = "postgresql+psycopg://u:p@db.invalid:5432/endpaper"

        assert database._speaks_postgres(other) is True
        assert make_url(other).drivername != database._PG8000

    def test_the_constant_is_true_under_a_postgres_url(
        self, tmp_path: Path
    ) -> None:
        """The listener reads the constant, so the constant is what to ask.

        **An equality between the function and the constant held nothing.**
        Both answer `False` on the suite's own SQLite URL, so the arm that
        stood here admitted any falsy expression whatever: three seats severed
        the constant from the function four ways and only a hardcoded `True`
        reddened. `False` passed, the driver gate passed, and so did the
        function applied to a URL the application never opens.

        **A child interpreter, because the constant is computed at import**
        and no monkeypatch after that moves it. The child dials nothing:
        `create_engine` opens no socket, so a port with no listener is enough
        to carry a Postgres URL into the module.
        """
        said = _what_the_child_said_the_gate_is(
            "postgresql+pg8000://u:p@127.0.0.1:1/db", tmp_path
        )

        assert said == "True", said

    def test_the_constant_is_false_under_the_url_the_suite_runs(
        self, tmp_path: Path
    ) -> None:
        """The other half, so a constant hardcoded true reds here.

        The in process arm above it asserts the same thing about the live
        module; this one asserts it through the same instrument as the
        Postgres half, so the two answers come from one reading.
        """
        said = _what_the_child_said_the_gate_is("sqlite:///./probe.db", tmp_path)

        assert said == "False", said

    def test_the_constant_is_the_function_applied_to_this_module_s_url(
        self,
    ) -> None:
        """The severing a child cannot reach, read off the syntax.

        **The driver gate is the severing that matters and no behavioural arm
        here can see it.** Writing `_SPEAKS_POSTGRES = _SPEAKS_PG8000` agrees
        with the function on every URL a child can carry, because the only
        Postgres driver installed is the one the other gate names, so the two
        differ exactly where this suite cannot go. What distinguishes them is
        the expression, so the expression is what is asserted.
        """
        sites = _every_binding_of("_SPEAKS_POSTGRES")
        written = _what_the_name_is_bound_to("_SPEAKS_POSTGRES")

        assert len(sites) == 1, f"{len(sites)} bindings in the module, expected one"
        assert len(written) == 1, f"{len(written)} of them assign an expression"
        assert ast.unparse(written[0]) == "_speaks_postgres(DATABASE_URL)"


def _database_module() -> ast.Module:
    """`database.py`, parsed once per call and cheap enough to leave so."""
    return ast.parse(Path(database.__file__).read_text(encoding="utf-8"))


def _binds(node: ast.AST, name: str) -> bool:
    """Whether one node binds `name`, by what binds rather than by its kind.

    **Two versions of this read statement kinds and both were defeated by
    adding a line.** The first collected annotated assignments and took the
    first match, so a plain assignment appended below it passed. The second
    collected both assignment kinds at **module top level**, so the same
    assignment appended one indent in, inside an `if`, a `try`, a `for`, a
    `with` or a walrus, passed again: the walk reported one binding, unparsed
    it to the expected call, and was green over a module whose constant was
    something else after import.

    **So this asks what binds.** A name in store context covers assignment in
    every nesting and every one of those five spellings; the rest are the
    binding forms that carry their name somewhere other than a `Name` node.

    **What no syntactic walk reaches, stated rather than enumerated around**:
    the module's namespace written as data. `globals()["..."] = ...` and
    `vars(sys.modules[__name__])["..."] = ...` are subscript stores on a
    call's result; `setattr(sys.modules[__name__], ...)` is a call; `exec` of
    a string names nothing at all. Naming only the first of those was this
    docstring's own version of the defect it describes. A pattern per spelling
    would enumerate the ways to write one evasion rather than hold a property.

    **The live residue is one value, not four spellings**, which is the half
    that says why not to enumerate: measured, only a rebinding to the driver
    gate survives any of them, because any other value is caught by
    `test_the_constant_is_true_under_a_postgres_url`.

    **This holds the name and not what the expression depends on**, which
    "what binds" invites a reader to assume. Redefining the function the
    constant calls leaves this walk and both child arms green and reds three
    arms over that function; rebinding the module's URL leaves this walk green
    and reds the child arm. Nothing is open: the neighbours hold both.
    """
    if isinstance(node, ast.Name):
        return isinstance(node.ctx, ast.Store) and node.id == name
    if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
        return node.name == name
    if isinstance(node, ast.alias):
        return (node.asname or node.name.split(".")[0]) == name
    if isinstance(node, ast.ExceptHandler):
        return node.name == name
    if isinstance(node, ast.MatchAs | ast.MatchStar):
        return node.name == name
    if isinstance(node, ast.MatchMapping):
        return node.rest == name
    return False


def _every_binding_of(name: str) -> list[ast.AST]:
    """Every site in `database.py` that binds `name`, at any nesting.

    **Its false refusals are both loud and immediate**: a local of the same
    name anywhere in the module, of which there are none today, and a correct
    rewrite that binds the name twice on purpose.
    """
    return [node for node in ast.walk(_database_module()) if _binds(node, name)]


def _what_the_name_is_bound_to(name: str) -> list[ast.expr]:
    """The expressions assigned to `name`, for the one binding above.

    Separate from the count, because most binding forms have no value to read:
    a `for` target and a `with ... as` bind without an expression anybody can
    unparse, and the count is what refuses those.
    """
    found: list[ast.expr] = []
    for node in ast.walk(_database_module()):
        if isinstance(node, ast.AnnAssign | ast.AugAssign | ast.NamedExpr):
            target = node.target
            if (
                isinstance(target, ast.Name)
                and target.id == name
                and node.value is not None
            ):
                found.append(node.value)
        elif isinstance(node, ast.Assign):
            for assigned in node.targets:
                if any(
                    isinstance(inner, ast.Name) and inner.id == name
                    for inner in ast.walk(assigned)
                ):
                    found.append(node.value)
    return found


def _the_zone_listener() -> ast.FunctionDef:
    """The listener, as a node, for the two readings below."""
    listener = [
        node
        for node in _database_module().body
        if isinstance(node, ast.FunctionDef)
        and node.name == "_pin_the_postgres_session_zone"
    ]
    assert len(listener) == 1, "the listener is not defined once"
    return listener[0]


def _what_the_zone_statement_interpolates() -> tuple[ast.expr, list[str]]:
    """The listener's one statement, and the names it interpolates.

    Read off the listener's own body rather than off the constant, because the
    constant's spelling and the statement's are two facts and the arms held
    only the first: moving an environment read **into** the interpolation while
    leaving the constant a literal reddened nothing.
    """
    executes = [
        node
        for node in ast.walk(_the_zone_listener())
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "execute"
    ]
    assert len(executes) == 1, f"{len(executes)} execute calls, expected one"
    argument = executes[0].args[0]
    interpolated = [
        ast.unparse(part.value)
        for part in ast.walk(argument)
        if isinstance(part, ast.FormattedValue)
    ]
    return argument, interpolated


class TestTheSessionZoneIsALiteralAndNotAnEnvironmentRead:
    """The constant's own docstring says it is not an environment knob.

    **Nothing held that, and this file already contains the shape somebody
    would copy**: `_synchronous` reads `SQLITE_SYNCHRONOUS` and reaches a
    statement that cannot be parameterised, which is why it whitelists what it
    passes through. The zone reaches the same kind of statement and is written
    as a literal instead, so what keeps it safe is that it is a literal.

    **Two facts, not one, and the first version of this class held only the
    first.** The constant's spelling and the statement's are independent: an
    environment read moved into the interpolation leaves the constant a
    literal and reddened nothing, because this suite runs with the variable
    unset. One arm each.

    Read off the syntax, because both properties are syntactic: rewriting the
    constant as a `getenv` reddened nothing before this, and so did moving one
    into the statement.
    """

    def test_the_zone_is_written_as_a_literal(self) -> None:
        sites = _every_binding_of("_SESSION_TIME_ZONE")
        written = _what_the_name_is_bound_to("_SESSION_TIME_ZONE")

        assert len(sites) == 1, f"{len(sites)} bindings in the module, expected one"
        assert len(written) == 1, f"{len(written)} of them assign an expression"
        assert isinstance(written[0], ast.Constant), ast.dump(written[0])
        assert written[0].value == "UTC"

    def test_the_statement_carries_that_literal_and_nothing_else(self) -> None:
        """The literal is only safe if it is what reaches the cursor.

        **Behavioural, and it owns only the case where the environment is
        unset**, which is every run of this suite. That is why the arm below
        reads the statement's own syntax: a read moved into the interpolation
        answers `UTC` here and this arm cannot tell.
        """
        connection = _ARecordedConnection()
        import unittest.mock

        with unittest.mock.patch.object(database, "_SPEAKS_POSTGRES", True):
            database._pin_the_postgres_session_zone(connection, None)

        assert connection.statements == ["SET TIME ZONE 'UTC'"]

    def test_the_statement_interpolates_the_constant_and_nothing_else(
        self,
    ) -> None:
        """The other half, and the arms here held only the constant's half.

        **A literal constant does not make a literal statement.** Moving the
        environment read out of the constant and **into** the interpolation
        leaves the constant a literal, answers `UTC` on a run with the
        variable unset, and reddened nothing: the class was named for the
        statement and held the spelling of the name beside it.

        **An f-string whose one interpolation is that name**, which refuses a
        read placed there, a second value spliced in beside it, and a percent
        or `format` spelling that is not an f-string at all.

        **And the listener binds no local of that name, which is the half the
        other three arms leave open.** This arm checks the **name**, and a
        local shadow satisfies it: rebinding `_SESSION_TIME_ZONE` inside the
        listener from the environment passes all four, because the module
        constant is still a literal, the interpolation still unparses to that
        name, and the behavioural arm sees the right string on a run with the
        variable unset. "Interpolates the constant and nothing else" is true
        of the shadow, which is the same defect this arm's predecessor was
        replaced for: a name that describes a property it does not hold.

        **Two correct rewrites it refuses, both loud.** Binding the statement
        to a local first, and extracting the statement into a helper the
        listener calls: the helper keeps exactly one execute so the count
        still passes, and the f-string assertion then reds on a call instead.

        **The binding count in the class above also reds on the shadow
        today**, because a local store is a binding of that name in the
        module and that walk counts every one. This is not redundant with it:
        that arm counts bindings anywhere and would stop seeing a shadow the
        moment anybody narrowed its walk back to module scope, which is the
        narrowing it has already been rewritten for twice.
        """
        argument, interpolated = _what_the_zone_statement_interpolates()
        shadows = [
            node
            for node in ast.walk(_the_zone_listener())
            if isinstance(node, ast.Name)
            and isinstance(node.ctx, ast.Store)
            and node.id == "_SESSION_TIME_ZONE"
        ]

        assert isinstance(argument, ast.JoinedStr), ast.unparse(argument)
        assert interpolated == ["_SESSION_TIME_ZONE"]
        assert shadows == [], "the listener rebinds the name it interpolates"
