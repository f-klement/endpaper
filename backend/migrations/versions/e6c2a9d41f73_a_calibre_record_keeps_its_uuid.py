"""Widen ck_book_identifiers_scheme for Calibre's own record key.

Revision ID: e6c2a9d41f73
Revises: d8a5f2c19e64
Create Date: 2026-10-15

`c7b0a3e5d281` wrote `scheme IN ('asin', 'google_books')`. A Calibre library's
`books.uuid` is now stored under `calibre_uuid`, because a record with no file and no
ISBN has nothing else that recognises it when the library is imported again:
`enums.BookIdentifierScheme.CALIBRE_UUID` says what the value is.

**And an index on the scheme and the value**, because something now looks a
Book up by them: `routers/books._calibre_holder` asks before every add, and an
import is one add per book. The unique index leads with `book_id`, so it serves
none of those lookups.

Batch mode reflects the table and keeps its other CHECK and both indexes,
which `d5e1b93a7c62` measured for the same operation on `author_identifiers`.

**No backfill.** Nothing could have written a `calibre_uuid` row before this.

Downgrade deletes every `calibre_uuid` row before narrowing the list, `d5e1b93a7c62`'s
call and its reason: a row the schema says cannot exist is worse than a row
that is gone.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "e6c2a9d41f73"
down_revision: str | Sequence[str] | None = "d8a5f2c19e64"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

#: Written out rather than derived from `enums`, for `c7b0a3e5d281`'s reason: a
#: revision says what it did on the day it ran.
_SCHEMES_BEFORE = "scheme IN ('asin', 'google_books')"
_SCHEMES_AFTER = "scheme IN ('asin', 'google_books', 'calibre_uuid')"

_CONSTRAINT = "ck_book_identifiers_scheme"
_INDEX = "ix_book_identifiers_scheme_value"


def _swap(wanted: str) -> None:
    with op.batch_alter_table("book_identifiers") as batch:
        batch.drop_constraint(_CONSTRAINT, type_="check")
        batch.create_check_constraint(_CONSTRAINT, wanted)


def upgrade() -> None:
    _swap(_SCHEMES_AFTER)
    op.create_index(_INDEX, "book_identifiers", ["scheme", "value"])


def downgrade() -> None:
    op.drop_index(_INDEX, table_name="book_identifiers")
    op.execute(sa.text("DELETE FROM book_identifiers WHERE scheme = 'calibre_uuid'"))
    _swap(_SCHEMES_BEFORE)
