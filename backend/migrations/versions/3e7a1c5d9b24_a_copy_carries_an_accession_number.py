"""A copy carries an accession number

Revision ID: 3e7a1c5d9b24
Revises: bb6650065133
Create Date: 2026-11-22

`books` gains `accession`, the code on a copy's label, and a unique index over
every row. `models.Book` and `accession.py` say why each.

**No backfill** (owner, 2026-11-22). Every existing row reads null until a member
asks for numbers through the bulk action: a number on a book with no label on
it says something untrue, and a household never needs one.

**The batch keeps `AUTOINCREMENT`** through `table_kwargs`, for the reason
`0850786d1753` gives: on SQLite each batch rebuilds the table.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "3e7a1c5d9b24"
down_revision: str | Sequence[str] | None = "bb6650065133"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_INDEX = "uq_books_accession"


def upgrade() -> None:
    with op.batch_alter_table("books", table_kwargs={"sqlite_autoincrement": True}) as batch:
        batch.add_column(sa.Column("accession", sa.String(length=9), nullable=True))
    op.create_index(_INDEX, "books", ["accession"], unique=True)


def downgrade() -> None:
    op.drop_index(_INDEX, table_name="books")
    with op.batch_alter_table("books", table_kwargs={"sqlite_autoincrement": True}) as batch:
        batch.drop_column("accession")
