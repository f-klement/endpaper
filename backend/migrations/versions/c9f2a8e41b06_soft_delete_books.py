"""Trash a book instead of dropping it.

One nullable column and one index. Existing rows are correct as they stand: a
book in the catalogue has not been deleted, which is what NULL says.

`visible_to()` gains the `deleted_at IS NULL` check in the same change, so
every listing, search, export and statistic excludes a trashed book without any
of them being edited. That is the whole reason the predicate exists in one
place, and it is why this migration has no data half: nothing needs
backfilling, and nothing outside `models.py` needs to learn a new rule.

Revision ID: c9f2a8e41b06
Revises: b3d71c0a5e42
Create Date: 2026-08-19
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "c9f2a8e41b06"
down_revision: str | Sequence[str] | None = "b3d71c0a5e42"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # batch_alter_table because SQLite rebuilds the table rather than altering
    # it. See the note in e814968f7930.
    with op.batch_alter_table("books") as batch:
        batch.add_column(sa.Column("deleted_at", sa.DateTime(), nullable=True))

    # Every book query in the app now filters on this column, so it is the one
    # index that is read on literally every request.
    op.create_index("ix_books_deleted_at", "books", ["deleted_at"])


def downgrade() -> None:
    # Downgrading discards the trash. There is nowhere else to put it: the rows
    # are only distinguishable from live books by the column being dropped.
    op.execute(sa.text("DELETE FROM books WHERE deleted_at IS NOT NULL"))

    op.drop_index("ix_books_deleted_at", table_name="books")
    with op.batch_alter_table("books") as batch:
        batch.drop_column("deleted_at")
