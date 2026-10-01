"""What `DATABASE_SSL_MODE` does against a server, which no fake can answer.

`test_database.py` reads the hostname check and the verify mode off the context
before any socket exists, and that is everything this module decides. **Three
of the five modes then rest on a claim about somebody else's code**: that
`pg8000.core._make_socket` raises `Server refuses SSL` when it holds a context
and the server declines. A reading of that source is how the silent downgrade
was found in the first place, and a reading is also how it sat unnoticed.

So this drives it. The pipeline's `test:postgres` service is `postgres:18-alpine`
with no certificate and no `ssl = on`, which makes it exactly the server every
one of these modes is about: the one that declines the upgrade.

**It also pins the premise under the cleartext warning.** `database._is_encrypted`
reads pg8000's private `_usock`, and a rename there would turn the warning into
"cannot tell" on every connection. Only a real connection can distinguish those
two, which is why that arm asserts `False` rather than `not True`.

**Skipped, at runtime, when the suite is on SQLite**, which is every run but one.
Everything else in this tree asserts SQLite outright rather than skipping, which
is why the Postgres job names the files it runs instead of running the suite.
"""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine, exc, text
from sqlalchemy.engine import make_url

import database

if make_url(database.DATABASE_URL).drivername != "postgresql+pg8000":
    pytest.skip(
        "DATABASE_SSL_MODE is a property of the Postgres connection, and this run "
        "is on SQLite. The pipeline's test:postgres job is where this file runs.",
        allow_module_level=True,
    )


def _connect(mode: str) -> None:
    """Open and close one connection under `mode`, raising what the driver raises."""
    engine = create_engine(
        database.DATABASE_URL,
        connect_args=database._connect_args(database.DATABASE_URL, mode, ""),
    )
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
    finally:
        engine.dispose()


class TestAModeThatRefusesADowngradeRefusesThisServer:
    """This server offers no TLS, so every insisting mode has to fail here.

    **Not an error message check dressed up as a posture check.** The three
    modes differ in what they verify and agree in refusing a server that will
    not upgrade at all, which is the half pg8000 decides and the half a context
    cannot be read for.

    The class and the wording were driven before being asserted, 2026-10-01,
    against a socket that answers the SSL request with `N`: all three arrive as
    `sqlalchemy.exc.InterfaceError` wrapping `Server refuses SSL`. Asserting a
    message somebody guessed is how an arm comes to pass on the wrong failure.
    """

    @pytest.mark.parametrize("mode", ["require", "verify-ca", "verify-full"])
    def test_the_connection_is_refused_rather_than_made_in_the_clear(self, mode: str) -> None:
        with pytest.raises(exc.InterfaceError, match="refuses SSL"):
            _connect(mode)


class TestTheTolerantModesReachTheServer:
    """The other side, and without it every arm above passes on a broken URL.

    A database nobody can reach refuses `require` for the wrong reason, and the
    message match would not notice.
    """

    @pytest.mark.parametrize("mode", ["disable", "prefer"])
    def test_the_connection_is_made(self, mode: str) -> None:
        _connect(mode)


class TestTheCleartextProbeCanStillSeeTheSocket:
    """The premise under the warning, driven rather than read.

    `_is_encrypted` returns `None` when pg8000 no longer exposes `_usock`, and
    `False` when the socket is there and is not wrapped. Against this server the
    answer must be `False`: a `None` here is a driver that moved, and it is the
    only signal there will ever be that the warning has gone deaf.
    """

    def test_it_reports_cleartext_rather_than_reporting_that_it_cannot_tell(self) -> None:
        engine = create_engine(
            database.DATABASE_URL,
            connect_args=database._connect_args(database.DATABASE_URL, "prefer", ""),
        )
        try:
            with engine.connect() as connection:
                raw = connection.connection.dbapi_connection

                assert database._is_encrypted(raw) is False
        finally:
            engine.dispose()
