"""Format, condition and the purchase details.

Six nullable columns and one index, no backfill. Nothing here can be inferred
from an existing row: a book already in the catalogue was scanned or imported,
and neither says whether it is a hardback or what it cost. Defaulting `format`
to paperback would be a guess written into every row at once, and a wrong guess
is worse than a blank because nobody re-checks a field that looks filled in.

`purchase_price_minor` counts cents rather than holding a decimal. SQLite has
no decimal type and SQLAlchemy's Numeric round-trips through a float over it,
which turns 12.99 into 12.989999999999999 on the way back out.

Revision ID: b3d71c0a5e42
Revises: e814968f7930
Create Date: 2026-08-19
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "b3d71c0a5e42"
down_revision: str | Sequence[str] | None = "e814968f7930"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # batch_alter_table because SQLite rebuilds the table rather than altering
    # it. See the note in e814968f7930.
    with op.batch_alter_table("books") as batch:
        batch.add_column(sa.Column("format", sa.String(20), nullable=True))
        batch.add_column(sa.Column("condition", sa.String(20), nullable=True))
        batch.add_column(sa.Column("purchase_price_minor", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("purchase_currency", sa.String(3), nullable=True))
        batch.add_column(sa.Column("purchased_at", sa.Date(), nullable=True))
        batch.add_column(sa.Column("purchase_source", sa.String(120), nullable=True))

    # "Have we got this on audio" is a filter over the whole catalogue, so it
    # is a browse action rather than a search and wants an index.
    op.create_index("ix_books_format", "books", ["format"])


def downgrade() -> None:
    op.drop_index("ix_books_format", table_name="books")
    with op.batch_alter_table("books") as batch:
        batch.drop_column("purchase_source")
        batch.drop_column("purchased_at")
        batch.drop_column("purchase_currency")
        batch.drop_column("purchase_price_minor")
        batch.drop_column("condition")
        batch.drop_column("format")
