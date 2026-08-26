"""Multiple copies of one title.

Revision ID: b1e7c94a2d05
Revises: d1a7f36b9c58
Create Date: 2026-08-23

A library that holds two paperbacks of one title had no way to say so:
`books.isbn` was UNIQUE, and every per-object fact in that table (location,
condition, what was paid, who has it) is already written per row. So a copy is
a second row, and the constraint is what stood in the way.

Two steps, and the second is the point.

`ix_books_isbn` is rebuilt **non-unique**: it is still the lookup index for the
scan flow, it is just no longer the rule. The rule moves to
`uq_books_isbn_single_copy`, a partial unique index over the rows whose
`copy_group` is null. Those are the rows nobody has declared a copy, so a
re-scan of a book already on the shelf still collides and still answers 409,
which is the mistake this constraint has always been catching. Dropping it
outright would have made a double-scan a silent second row.

No backfill. Every existing row keeps `copy_group` NULL, which means "one of
it", so the partial index covers exactly the set the old UNIQUE covered and an
upgrade changes nothing anybody can observe.

Downgrade re-imposes the old UNIQUE, which **fails if the database holds any
copies**. That is deliberate: the alternative is choosing a row to destroy, and
a migration is not the place to decide which of somebody's two paperbacks stops
existing.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "b1e7c94a2d05"
down_revision: str | Sequence[str] | None = "d1a7f36b9c58"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_PARTIAL_INDEX = "uq_books_isbn_single_copy"


def upgrade() -> None:
    # batch_alter_table because SQLite rebuilds the table rather than altering
    # it. See the note in e814968f7930.
    with op.batch_alter_table("books") as batch:
        batch.add_column(sa.Column("copy_group", sa.String(32), nullable=True))

    op.create_index("ix_books_copy_group", "books", ["copy_group"])

    # The old index was UNIQUE. Rebuilt plain, because the scan flow still
    # looks an ISBN up on every add and that is now all this index is for.
    op.drop_index("ix_books_isbn", table_name="books")
    op.create_index("ix_books_isbn", "books", ["isbn"])

    op.create_index(
        _PARTIAL_INDEX,
        "books",
        ["isbn"],
        unique=True,
        sqlite_where=sa.text("copy_group IS NULL"),
    )


def downgrade() -> None:
    op.drop_index(_PARTIAL_INDEX, table_name="books")
    op.drop_index("ix_books_isbn", table_name="books")
    # Fails on a database holding copies, and see the module docstring for why
    # that is the right outcome rather than a bug in this function.
    op.create_index("ix_books_isbn", "books", ["isbn"], unique=True)
    op.drop_index("ix_books_copy_group", table_name="books")
    with op.batch_alter_table("books") as batch:
        batch.drop_column("copy_group")
