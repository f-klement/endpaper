"""A database error from a live Postgres is logged without the row it quotes.

`test_errors.py` builds the error from pg8000's own exception class, because the
suite runs on SQLite. That pins what `errors.database_error_summary` does with
the fields; it cannot pin that a live server puts the value where the fake does.
This drives the real thing: a unique violation on a marker value, through a
route, into the log the 500 handler writes.

**The first assertion is the witness, not the subject.** Without it, a server
that stopped quoting the value would leave the absence green for no reason.

**Skipped, at runtime, when the suite is on SQLite**, as
`test_database_tls_on_a_real_server.py` is and for the same reason.
"""

from __future__ import annotations

import logging

import pytest
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import IntegrityError

import database
from errors import UNHANDLED

if make_url(database.DATABASE_URL).drivername != "postgresql+pg8000":
    pytest.skip(
        "A live server's error detail is a property of Postgres, and this run is "
        "on SQLite. The pipeline's test:postgres job is where this file runs.",
        allow_module_level=True,
    )

MARKER = "LIVE-DETAIL-MARKER"
PATH = "/live-unique-violation-test"


@pytest.fixture
def duplicate_route():
    """A route inserting one settings key twice, removed again in a `finally`."""
    import main

    @main.app.get(PATH, include_in_schema=False)
    def duplicate() -> None:
        with database.engine.begin() as connection:
            for _ in range(2):
                connection.execute(
                    text("INSERT INTO settings (key, value) VALUES (:key, 'x')"),
                    {"key": MARKER},
                )

    try:
        yield
    finally:
        main.app.routes[:] = [
            route for route in main.app.routes if getattr(route, "path", None) != PATH
        ]


@pytest.mark.answers_500(raises=(IntegrityError,))
def test_a_unique_violation_logs_the_constraint_and_not_the_value(
    client, duplicate_route, caplog
) -> None:
    with caplog.at_level(logging.DEBUG):
        res = client.get(PATH, headers={"Accept": "application/json"})

    assert res.status_code == 500
    [line] = [r for r in caplog.records if r.getMessage().startswith("Unhandled error")]
    assert MARKER in str(getattr(line, UNHANDLED).orig)
    assert "on settings_pkey" in line.getMessage()
    assert MARKER not in caplog.text
