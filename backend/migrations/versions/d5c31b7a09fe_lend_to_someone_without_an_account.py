"""Lend to someone without an account.

Revision ID: d5c31b7a09fe
Revises: f2b8d6a03c17

`loans.loaned_to_user_id` was NOT NULL with a foreign key to `users.id`, so the
only borrower this app could record was a member. The people most likely to
keep a book are exactly the ones who will never have an account here.

So the column becomes nullable and `loaned_to_name` sits beside it, with a
CHECK constraint saying **exactly one** of them is set. In the database rather
than only in `LoanCreate`, for the same reason the open-loan rule is an index:
the schema guards one writer, and a restore or the next endpoint added does not
go through it.

Two ordering details this migration depends on.

The partial unique index is dropped first and recreated afterwards. Batch mode
rewrites the table by reflecting it, and a partial index that came back as a
plain unique one would forbid lending a book that had already been returned
once. Dropping it removes the question.

Existing rows all name a member, so the constraint holds over them without any
data step.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "d5c31b7a09fe"
down_revision: str | None = "f2b8d6a03c17"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None

_OPEN_LOAN_INDEX = "uq_loans_one_open_per_book"
_BORROWER_CHECK = "ck_loans_one_borrower"


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
        batch_op.add_column(sa.Column("loaned_to_name", sa.String(length=120), nullable=True))
        batch_op.alter_column(
            "loaned_to_user_id", existing_type=sa.Integer(), nullable=True
        )
        batch_op.create_check_constraint(
            _BORROWER_CHECK,
            # The trim clause matters: '' and '   ' both satisfy IS NOT NULL,
            # so without it the constraint admits a loan whose borrower is a
            # run of spaces. Kept identical to models.py.
            "(loaned_to_user_id IS NULL) <> (loaned_to_name IS NULL) "
            "AND (loaned_to_name IS NULL OR length(trim(loaned_to_name)) > 0)",
        )

    _create_open_loan_index()


def downgrade() -> None:
    # A loan to somebody with no account has no member to point at, so it
    # cannot be represented by the older schema. Dropping those rows is the
    # honest reversal: keeping them would need an invented user.
    op.execute(sa.text("DELETE FROM loans WHERE loaned_to_user_id IS NULL"))

    _drop_open_loan_index()

    with op.batch_alter_table("loans") as batch_op:
        batch_op.drop_constraint(_BORROWER_CHECK, type_="check")
        batch_op.alter_column(
            "loaned_to_user_id", existing_type=sa.Integer(), nullable=False
        )
        batch_op.drop_column("loaned_to_name")

    _create_open_loan_index()
