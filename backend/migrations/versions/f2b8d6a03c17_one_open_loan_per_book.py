"""One open loan per book.

Revision ID: f2b8d6a03c17
Revises: a17c5b2e94d0

Three code paths had to agree that a book is in one person's hands at a time,
and one of them did not: merging two records left both open loans open, so the
merged book was out with two people and the UI showed whichever row came back
first.

A partial unique index rather than application code in a fourth place. Partial
because a book returned and lent again is two rows with the same `book_id`, and
only the open ones are exclusive.

Existing duplicates are closed before the index is created, oldest kept: the
earliest open loan is the one that actually happened, and the later rows are
the artefacts of the merge that should have closed them. Creating the index
without this step fails on any database that hit the bug.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "f2b8d6a03c17"
down_revision: str | None = "a17c5b2e94d0"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None

_INDEX = "uq_loans_one_open_per_book"


def upgrade() -> None:
    op.execute(
        sa.text(
            """
            UPDATE loans SET returned_at = CURRENT_TIMESTAMP
            WHERE returned_at IS NULL
              AND id NOT IN (
                  SELECT MIN(id) FROM loans WHERE returned_at IS NULL GROUP BY book_id
              )
            """
        )
    )
    op.create_index(
        _INDEX,
        "loans",
        ["book_id"],
        unique=True,
        sqlite_where=sa.text("returned_at IS NULL"),
        if_not_exists=True,
    )


def downgrade() -> None:
    op.drop_index(_INDEX, table_name="loans", if_exists=True)
