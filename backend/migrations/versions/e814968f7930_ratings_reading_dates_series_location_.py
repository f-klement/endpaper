"""Ratings, reading dates, series, location, loan due date.

Six columns and four indexes, all nullable, no backfill. Existing rows are
correct as they stand: a book with no series is not in one, and a status set
before this migration genuinely has no recorded date. Inventing a
`finished_at` from `added_at` would be fabricating history.

Revision ID: e814968f7930
Revises: 95b6a61d6668
Create Date: 2026-08-18
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "e814968f7930"
down_revision: str | Sequence[str] | None = "95b6a61d6668"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # batch_alter_table throughout: SQLite rebuilds the table rather than
    # altering it, and plain op.add_column works only for the simplest cases.
    with op.batch_alter_table("books") as batch:
        batch.add_column(sa.Column("series_name", sa.String(255), nullable=True))
        batch.add_column(sa.Column("series_index", sa.Float(), nullable=True))
        batch.add_column(sa.Column("location", sa.String(120), nullable=True))
    op.create_index("ix_books_series_name", "books", ["series_name"])
    op.create_index("ix_books_location", "books", ["location"])

    with op.batch_alter_table("user_books") as batch:
        batch.add_column(sa.Column("rating", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("started_at", sa.DateTime(), nullable=True))
        batch.add_column(sa.Column("finished_at", sa.DateTime(), nullable=True))
    op.create_index("ix_user_books_finished_at", "user_books", ["finished_at"])

    with op.batch_alter_table("loans") as batch:
        batch.add_column(sa.Column("due_at", sa.DateTime(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("loans") as batch:
        batch.drop_column("due_at")

    op.drop_index("ix_user_books_finished_at", table_name="user_books")
    with op.batch_alter_table("user_books") as batch:
        batch.drop_column("finished_at")
        batch.drop_column("started_at")
        batch.drop_column("rating")

    op.drop_index("ix_books_location", table_name="books")
    op.drop_index("ix_books_series_name", table_name="books")
    with op.batch_alter_table("books") as batch:
        batch.drop_column("location")
        batch.drop_column("series_index")
        batch.drop_column("series_name")
