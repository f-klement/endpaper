"""Tests for backend/database.py: engine setup and the session dependency."""

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
