"""One spelling of a name means one person, when a member says so.

Revision ID: a9c4e7b21d03
Revises: c2f95a80d417
Create Date: 2026-08-23

Author pages are derived from `books.author`, the way series pages are derived
from `series_name`. This adds the one thing derivation cannot hold: a member's
decision that two spellings are the same person.

**Nothing in `books` is read or written by this migration**, which is the whole
reason the design was chosen. The alternative was to make merging rewrite every
matching `books.author` string, and that migration would have had to be safe on
a column that is NULL, empty, whitespace only, or a comma with no second name
beside it, and would still have been unable to say what the shelf looked like
before it ran. There is no such exposure here: the table starts empty and the
books are untouched.

No `batch_alter_table` either, because no existing table is altered. That also
means the `uq_books_isbn_single_copy` reflection hazard c2f95a80d417 measured
does not arise: nothing reflects and rebuilds `books`.

`alias_key` is unique. A spelling means one person, so re-merging it somewhere
else replaces the row rather than adding a second one for a reader to choose
between.

**The downgrade is exact.** It drops the table, which loses which spellings a
library had folded together, and it can do nothing else: no book row carries
a trace of a merge. What it cannot do is corrupt anything, because the merges
never wrote to `books` in the first place. After a downgrade the shelf shows
every spelling as its own author again, which is precisely the state before the
first merge.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "a9c4e7b21d03"
down_revision: str | Sequence[str] | None = "c2f95a80d417"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "author_aliases",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("alias_key", sa.String(length=500), nullable=False),
        sa.Column("canonical_name", sa.String(length=300), nullable=False),
        sa.Column("created_by_user_id", sa.Integer(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("alias_key"),
    )
    op.create_index("ix_author_aliases_id", "author_aliases", ["id"])


def downgrade() -> None:
    op.drop_index("ix_author_aliases_id", table_name="author_aliases")
    op.drop_table("author_aliases")
