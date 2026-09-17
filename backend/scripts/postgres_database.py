"""Making and checking the Postgres databases this project's tests run against.

**One home for two callers**, and the reason is a defect this file was written
to close: the pipeline created its databases with the locale spelled out and the
suite created its per worker ones with a bare `CREATE DATABASE`, so the job
asserted a collation on a database nothing ran against and the suite ran on
whatever `template1` carried. Two spellings of one operation, disagreeing on the
dimension one of them documented as load bearing.

**Why a collation is a correctness question and not a preference.** The charset
rules in `models.py` are POSIX bracket expressions, `[^A-Za-z0-9._]` and
`[^a-z0-9_-]`, and a range inside a bracket expression is interpreted against the
operand's collation. Those rules spell `COLLATE "C"` at their own site so they do
not depend on the database's, and this holds the database to one anyway: the
constraint's `COLLATE` is what protects a deployment, and this is what keeps the
measurement honest.

**`TEMPLATE template0` with the locale spelled out**, rather than inheriting
whatever `template1` on that server happens to carry.

Run as a script for the pipeline, with `DATABASE_URL` naming a database on the
server in question:

    python scripts/postgres_database.py --assert-locale
    python scripts/postgres_database.py --create endpaper_partial
"""

import os
import sys
from typing import Final

from sqlalchemy import create_engine, text

#: The collation and encoding every figure in the dialect branches was measured
#: against, and the two this refuses to run without.
WANTED_COLLATE: Final = "C"
WANTED_ENCODING: Final = "UTF8"

#: `CREATE DATABASE` cannot take a bind parameter, so the name is quoted into the
#: statement and held to a shape that cannot carry a quote or a backslash out of
#: it. See `_safe_name`.
_CREATE = (
    'CREATE DATABASE "{name}" TEMPLATE template0 '
    f"ENCODING '{WANTED_ENCODING}' LC_COLLATE '{WANTED_COLLATE}' "
    f"LC_CTYPE '{WANTED_COLLATE}'"
)

_LOCALE = text(
    "SELECT datcollate, pg_encoding_to_char(encoding) "
    "FROM pg_database WHERE datname = current_database()"
)

_EXISTS = text("SELECT 1 FROM pg_database WHERE datname = :name")


def _safe_name(name: str) -> str:
    """The shape a name must have to be quoted into DDL that takes no parameter.

    **`isascii()` beside `isalnum()`, on the same receiver and under one `and`.**
    `isalnum()` is true of every letter in Unicode, so without it a name is held
    to "letters, digits and underscores" in a repertoire nobody chose.
    `tests/test_house_rules.py::TestAnAlphanumericPredicateIsAlwaysNarrowedToAscii`
    is what refuses the pair coming apart again, and it reads the receiver rather
    than looking for an `isascii` call nearby, so the two must be spelled over
    `stripped` and not one over `name` and one over `name.replace(...)`.
    """
    stripped = name.replace("_", "")
    if not (name and stripped.isascii() and stripped.isalnum()):
        raise ValueError(f"refusing a database name of {name!r}")
    return name


def create_if_absent(admin_url: str, name: str) -> None:
    """Create one database, unless the server already has it.

    `admin_url` names any database on the same server. AUTOCOMMIT because
    `CREATE DATABASE` cannot run inside a transaction block.
    """
    engine = create_engine(admin_url, isolation_level="AUTOCOMMIT")
    with engine.connect() as connection:
        if connection.execute(_EXISTS, {"name": name}).scalar():
            return
        connection.execute(text(_CREATE.format(name=_safe_name(name))))


def wrong_locale(url: str) -> str | None:
    """What is wrong with this database's collation or encoding, or None.

    A string rather than a raise, so a caller inside the suite can put it in an
    assertion message and a caller in a pipeline can print it and exit.
    """
    with create_engine(url).connect() as connection:
        collate, encoding = connection.execute(_LOCALE).one()
    wrong = []
    if collate != WANTED_COLLATE:
        wrong.append(f"datcollate is {collate!r}, wanted {WANTED_COLLATE!r}")
    if encoding != WANTED_ENCODING:
        wrong.append(f"encoding is {encoding!r}, wanted {WANTED_ENCODING!r}")
    return "; ".join(wrong) or None


def main(argv: list[str]) -> int:
    url = os.environ["DATABASE_URL"]
    if argv[:1] == ["--assert-locale"]:
        wrong = wrong_locale(url)
        if wrong:
            print(f"REFUSED: {wrong}", file=sys.stderr)
            return 1
        print(f"collate={WANTED_COLLATE} encoding={WANTED_ENCODING}")
        return 0
    if argv[:1] == ["--create"]:
        create_if_absent(url, argv[1])
        print(f"{argv[1]} is there")
        return 0
    print(__doc__, file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
