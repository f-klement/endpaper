"""A blank text column is null.

Revision ID: d3f8a1c6b250
Revises: c7b41e92f80a
Create Date: 2026-10-14

**Five columns of `books` held two spellings of "nothing here"**: null, and a
string that is empty or whitespace only. `subtitle`, `author`, `publisher`,
`description` and `series_name`. A clear was designed as null, but the scan
form's manual author box sent `""` once typed in and emptied, and both request
bodies accepted a blank for all five. From this revision both bodies store a
blank as null (`models.blank_as_none`), and this turns the rows already
holding one into null, so a clear and a field never set are one value.

**Only an all whitespace value changes.** A value with text in it keeps its
surrounding spaces, the rule the request bodies follow.

**Whitespace is what `str.strip` removes on the Python running this**, passed to
`trim` as its character set, so the database tests the same characters the
request bodies do rather than SQL's default of the space alone. Both engines
take `trim(value, characters)`: SQLite natively, and PostgreSQL as its
`btrim`. A null stays null, because `trim` of a null is null and so never equals
`''`.

**The downgrade does nothing**, on purpose. The distinction it would restore
carried no meaning: nothing ever read a blank differently from a null, and
nothing records which rows held which.
"""

import sys
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "d3f8a1c6b250"
down_revision: str | None = "c7b41e92f80a"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None

#: Spelled out rather than imported from `models.BLANK_IS_NULL`, because
#: a revision describes the schema on the day it was written: a column joining
#: that tuple later is a later revision's data step, not this one's.
_COLUMNS: tuple[str, ...] = (
    "subtitle", "author", "publisher", "description", "series_name",
)

#: Every character `str.isspace` admits, which is the set `str.strip` removes.
_WHITESPACE: str = "".join(
    character for character in map(chr, range(sys.maxunicode + 1)) if character.isspace()
)


def upgrade() -> None:
    books = sa.table("books", *(sa.column(name, sa.Text) for name in _COLUMNS))
    for name in _COLUMNS:
        column = books.c[name]
        op.execute(
            sa.update(books)
            .where(sa.func.trim(column, _WHITESPACE) == "")
            .values({name: None})
        )


def downgrade() -> None:
    """Nothing to undo. See the module docstring."""
