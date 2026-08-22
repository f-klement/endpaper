"""Remember that an overdue reminder went out.

Revision ID: a3e94c0d15f8
Revises: f7c2a1e50b93

One nullable column. Without it the overdue digest has only two behaviours,
and both are wrong: send once and forget a loan that is still out, or repeat
the same list into the household's channel on every run.

**The partial unique index is dropped and recreated around the batch block**,
exactly as `d5c31b7a09fe` does and for the same reason: batch mode rewrites the
table by reflecting it, and `uq_loans_one_open_per_book` returning as a plain
unique index would forbid ever lending a book twice. Adding a nullable column
does not trigger a rewrite today, but the downgrade's `drop_column` does, and a
downgrade that quietly breaks lending is worse than one that fails.

Existing rows get NULL, which reads as "never notified". That is the honest
value: nothing has been sent for them, and the first run after this migration
should chase every loan already overdue.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "a3e94c0d15f8"
down_revision: str | Sequence[str] | None = "f7c2a1e50b93"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_OPEN_LOAN_INDEX = "uq_loans_one_open_per_book"


def _drop_open_loan_index() -> None:
    op.drop_index(_OPEN_LOAN_INDEX, table_name="loans", if_exists=True)


def _create_open_loan_index() -> None:
    op.create_index(
        _OPEN_LOAN_INDEX,
        "loans",
        ["book_id"],
        unique=True,
        sqlite_where=sa.text("returned_at IS NULL"),
        if_not_exists=True,
    )


def upgrade() -> None:
    _drop_open_loan_index()

    with op.batch_alter_table("loans") as batch_op:
        batch_op.add_column(sa.Column("notified_at", sa.DateTime(), nullable=True))

    _create_open_loan_index()


def downgrade() -> None:
    _drop_open_loan_index()

    with op.batch_alter_table("loans") as batch_op:
        batch_op.drop_column("notified_at")

    _create_open_loan_index()
