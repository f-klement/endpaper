"""A Book records where its record came from, and whether it was changed here.

Revision ID: f4a9c2e17b30
Revises: a3e81c5d7f20
Create Date: 2026-11-14

Two nullable columns on `books`, `record_origin` and `record_modified_here`.
Why they are two rather than one is on `models.Book`.

**No backfill.** Nothing recorded either fact before this revision, so every
existing row has neither and reads as unknown. Guessing an origin from the
columns a row happens to carry would write a claim nobody made.

`record_origin` is a plain `String(20)` with no check constraint, behind
`models.DegradingEnum`, for the reason `enums.BookFormat` gives: a new origin
then costs no table rebuild.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "f4a9c2e17b30"
down_revision: str | Sequence[str] | None = "a3e81c5d7f20"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # An added nullable column is a plain ALTER on SQLite and rebuilds nothing.
    # The keyword is passed anyway, because a batch that did rebuild `books`
    # without it would drop AUTOINCREMENT and reuse deleted Book ids.
    with op.batch_alter_table("books", table_kwargs={"sqlite_autoincrement": True}) as batch:
        batch.add_column(sa.Column("record_origin", sa.String(20), nullable=True))
        batch.add_column(sa.Column("record_modified_here", sa.Boolean(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("books", table_kwargs={"sqlite_autoincrement": True}) as batch:
        batch.drop_column("record_modified_here")
        batch.drop_column("record_origin")
