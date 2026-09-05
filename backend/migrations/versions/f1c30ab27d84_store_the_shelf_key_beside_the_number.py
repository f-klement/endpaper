"""The shelf key is stored beside the call number instead of built per request.

Revision ID: f1c30ab27d84
Revises: b7d4e6f01a95
Create Date: 2026-09-05

A shelf order is `min(key)` over a book's classifications, and the key was a SQL
expression: twelve `CASE` arms padding class letters, class integer and class
decimal so that a shorter class files before a longer one. It was evaluated per
classification row on every listing, and it was seconds per request at the
worst case a member can construct. `filing.py` carries the figures, beside the
constants they were measured against.

`classifications.sort_key` now holds what the scheme's filing rule returned, and
the order reads the column. Koha does the same thing under the name `cn_sort`.

**The rule is copied into this file rather than imported from `filing.py`**,
which is what `a4c73e0b19d5`, `c9a5f27b3e41`, `c1f8a7e3d240` and `b7d4e6f01a95`
each state in their own words: a revision describes the data as it was on the
day it ran. Importing today's `filing` would make a library upgrading in a year
backfill under a rule this revision never saw, which is the one thing a
historical record must not do.

The cost of the copy is a second statement of one rule, and it is paid for by
`tests/test_schema.py::TestTheStoredShelfKey`, which holds `_sort_key` below to
`filing.sort_key_for` over the corpus in `tests/test_filing.py` **today**. That
is the arrangement `TestTheSeededCatalogueTargetsMatchTheCode` already uses for
the identical tension. The corpus reaches all twelve class shapes, twice each,
so a copy that got one of them wrong is caught rather than assumed.

**Changing a filing rule from here on is a data change.** Nothing recomputes
this column on read, so an edit to `filing.py` needs its own revision
recomputing it, or the library stays filed by the rule it was written under with
no error anywhere.

## Why the ordering dance in `e7b3d02a5c94` is not needed here

That revision records the trap: Alembic's SQLite implementation is not
transactional for DDL, and pysqlite opens a transaction for DML only, so DDL run
before any DML is durable the moment it runs. `op.add_column` below is the first
statement, so a failure after it would leave a column added, the backfill
undone, and `alembic_version` still naming the previous revision, which no rerun
can apply twice.

It cannot fail. `_sort_key` takes two strings and returns one: `re.fullmatch`,
`str.replace`, `str.ljust` and `str.rjust` raise on nothing a `TEXT NOT NULL`
column can hold, and a scheme this app has never published falls to the generic
answer rather than raising. So there is no failure to order around, which is
stated rather than left as an assumption a later edit could quietly break.

The downgrade drops the column. Nothing is lost: every value in it is derived
from the two columns beside it.
"""

import re
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "f1c30ab27d84"
down_revision: str | Sequence[str] | None = "b7d4e6f01a95"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

#: The filing rule as it stood on the day this ran. See the module docstring for
#: why these are literals here and not imports.
_LETTERS_WIDTH = 3
_INTEGER_WIDTH = 4
_DECIMAL_WIDTH = 6
_LETTER_PAD = " "
_SEGMENTATION_PRIME = "/"

#: `CLASSIFICATION_NUMBER_MAX` plus the most a rule can add to a value: the
#: three widths above emit 13 characters in place of the shortest prefix the
#: expression below matches, which is one letter and one digit.
_SORT_KEY_MAX = 120 + (_LETTERS_WIDTH + _INTEGER_WIDTH + _DECIMAL_WIDTH - 2)

_LCC = re.compile(
    rf"([A-Za-z]{{1,{_LETTERS_WIDTH}}})"
    rf"([0-9]{{1,{_INTEGER_WIDTH}}})"
    rf"(?:\.([0-9]{{1,{_DECIMAL_WIDTH}}}))?"
    r"(.*)",
    re.DOTALL,
)


def _sort_key(scheme: str, number: str) -> str:
    """Where one number stands on a shelf, under the rule its scheme files by.

    Three rules over four schemes, which is what `filing.FILING_RULES` held on
    this date: Dewey drops MARC's segmentation prime and otherwise files as its
    own text, the Library of Congress pads its three parts, and everything else,
    the two subject vocabularies and any scheme this app has never published,
    files as the text it is.
    """
    if scheme == "ddc":
        return number.replace(_SEGMENTATION_PRIME, "")
    if scheme != "lcc":
        return number
    match = _LCC.fullmatch(number)
    if match is None:
        return number
    letters, integer, decimal, rest = match.groups()
    return (
        letters.upper().ljust(_LETTERS_WIDTH, _LETTER_PAD)
        + integer.rjust(_INTEGER_WIDTH, "0")
        + (decimal or "").ljust(_DECIMAL_WIDTH, "0")
        + rest
    )


def upgrade() -> None:
    connection = op.get_bind()

    op.add_column(
        "classifications",
        sa.Column("sort_key", sa.String(length=_SORT_KEY_MAX), nullable=True),
    )

    # Backfilled rather than left null. A null files last under `nullslast`, so
    # a row this missed would sit at the end of every shelf order with nothing
    # to see: no error, no empty cell, just a book in the wrong place.
    rows = connection.execute(
        sa.text("SELECT id, scheme, number FROM classifications")
    ).all()
    if rows:
        connection.execute(
            sa.text("UPDATE classifications SET sort_key = :key WHERE id = :row_id"),
            [
                {"row_id": row_id, "key": _sort_key(scheme, number)}
                for row_id, scheme, number in rows
            ],
        )

    # SQLite cannot ALTER a column to NOT NULL, so this rebuilds the table.
    # `render_as_batch=True` in `migrations/env.py` is what makes it do so, and
    # the rebuild carries `uq_classifications_book_scheme_number` with it: that
    # index is what stops enrichment depositing a second copy of every heading,
    # and `b7d41f0a2c95` already lost a wave to proving a batch rewrite keeps
    # it.
    with op.batch_alter_table("classifications") as batch:
        batch.alter_column(
            "sort_key",
            existing_type=sa.String(length=_SORT_KEY_MAX),
            nullable=False,
        )


def downgrade() -> None:
    with op.batch_alter_table("classifications") as batch:
        batch.drop_column("sort_key")
