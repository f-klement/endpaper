"""The patron's own overdue notice keeps its own stamp

Revision ID: 3091190ff9ad
Revises: bd2ad077f519
Create Date: 2026-11-22

One nullable column, `loans.patron_notified_at`: when a mail about the loan
last reached the patron holding it (#24). `notified_at` stays the household
digest's, and each selection reads its own, so a failure on one audience never
silences the other (owner's decision on #24). `models.Loan` says what each holds.

**Existing stamps stay where they are, and the new column starts null.** Every
`notified_at` written before this revision records the digest, because the
patron notice arrives with it, so none of them is moved or copied. Null reads as
"this patron was never mailed about it", which is true. The patron notice is
off on an upgrade, so nobody is mailed until an admin switches it on; the first
run after that mails each patron once about what they hold overdue.

**The partial unique index is dropped and recreated around the batch block**,
for the reason `a3e94c0d15f8` gives: adding a nullable column does not rewrite
the table, but the downgrade's `drop_column` does, and `uq_loans_one_open_per_book`
reflected back as a plain unique index would forbid lending a book twice.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "3091190ff9ad"
down_revision: str | Sequence[str] | None = "bd2ad077f519"
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
        # Both dialects. `f2b8d6a03c17` carries what a `sqlite_where` alone does
        # to this index on Postgres.
        postgresql_where=sa.text("returned_at IS NULL"),
        if_not_exists=True,
    )


def upgrade() -> None:
    _drop_open_loan_index()

    with op.batch_alter_table("loans") as batch_op:
        batch_op.add_column(sa.Column("patron_notified_at", sa.DateTime(), nullable=True))

    _create_open_loan_index()


def downgrade() -> None:
    _drop_open_loan_index()

    with op.batch_alter_table("loans") as batch_op:
        batch_op.drop_column("patron_notified_at")

    _create_open_loan_index()
