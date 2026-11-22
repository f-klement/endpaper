"""A harvested Book keeps its record's OAI identifier

Revision ID: 6dac941f868b
Revises: 4121a6f9c8d7
Create Date: 2026-11-21

`books` gains `harvested_identifier`, the OAI identifier of the record a
harvest created the row from, so a second run matches it before the ISBN
ladder. `models.Book` says why.

**No backfill.** Every existing row has a null identifier: no harvested Book
exists before the harvester, which arrives in the revision before this one.

**The batch keeps `AUTOINCREMENT`** through `table_kwargs`, for the reason
`0850786d1753` gives: the downgrade's drop rebuilds the table on SQLite.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "6dac941f868b"
down_revision: str | Sequence[str] | None = "4121a6f9c8d7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_INDEX = "ix_books_harvested_identifier"


def upgrade() -> None:
    with op.batch_alter_table("books", table_kwargs={"sqlite_autoincrement": True}) as batch:
        batch.add_column(sa.Column("harvested_identifier", sa.String(length=255), nullable=True))
    op.create_index(_INDEX, "books", ["harvested_identifier"])


def downgrade() -> None:
    op.drop_index(_INDEX, table_name="books")
    with op.batch_alter_table("books", table_kwargs={"sqlite_autoincrement": True}) as batch:
        batch.drop_column("harvested_identifier")
