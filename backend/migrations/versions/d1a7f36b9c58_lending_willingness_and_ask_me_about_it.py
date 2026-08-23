"""Lending willingness on a book, and "ask me about it" per member.

Two columns, no backfill, and they differ on nullability for a reason.

`books.lending` is nullable, like `format` and `condition`: nobody has been
asked yet, and writing a guess into every existing row would produce a field
that looks answered and never gets re-checked.

`user_books.wants_to_discuss` is NOT NULL with a server default of 0, because
there is nothing between yes and no. Absence of a `user_books` row already
means "has not said" for every member who never touched the book, so a
nullable column would carry a second, weaker spelling of the same thing.

Revision ID: d1a7f36b9c58
Revises: a3e94c0d15f8
Create Date: 2026-08-22
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "d1a7f36b9c58"
down_revision: str | Sequence[str] | None = "a3e94c0d15f8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # batch_alter_table because SQLite rebuilds the table rather than altering
    # it. See the note in e814968f7930.
    with op.batch_alter_table("books") as batch:
        batch.add_column(sa.Column("lending", sa.String(20), nullable=True))

    # "What could we lend the book club" is a filter over the whole catalogue,
    # so it is a browse action rather than a search and wants an index, exactly
    # as `format` does.
    op.create_index("ix_books_lending", "books", ["lending"])

    # `server_default` is not decoration on a NOT NULL column added to a table
    # with rows in it: without it SQLite has nothing to put in the existing
    # ones and the ALTER fails. It stays on the column afterwards so a restore,
    # which inserts through Core, does not have to name the field either.
    with op.batch_alter_table("user_books") as batch:
        batch.add_column(
            sa.Column(
                "wants_to_discuss",
                sa.Boolean(),
                nullable=False,
                server_default="0",
            )
        )


def downgrade() -> None:
    with op.batch_alter_table("user_books") as batch:
        batch.drop_column("wants_to_discuss")

    op.drop_index("ix_books_lending", table_name="books")
    with op.batch_alter_table("books") as batch:
        batch.drop_column("lending")
