"""Where a member is in a book, recorded as a log.

Revision ID: f7c2a1e50b93
Revises: e6f1a94b2d73

`user_books` carried `started_at` and `finished_at` and nothing between them,
so the only reading question this app could answer was "did you finish it".

A table rather than a `current_page` column, because the questions the feature
exists for ("how much did I read in March", "how long did that one take") are
about the history, and a column overwrites the history on every save.

Two CHECK constraints, in the database rather than only in the schema, for the
same reason `ck_loans_one_borrower` is: a restore inserts through Core and
never sees a Pydantic model.

* `ck_reading_progress_one_unit` admits a page **or** a percent, never both and
  never neither. Carrying both would need a rule for which one wins; carrying
  one needs no such rule.
* `ck_reading_progress_bounds` refuses page 0 and percent 140, both of which
  are storable otherwise and both of which make the derived percent nonsense.

One composite index. `(user_id, book_id, recorded_at)` is the whole access
pattern: this member, this book, in order. `recorded_at` deliberately carries
no index of its own, because nothing filters or orders on it alone, and an
unread index on an append-only table is a write cost and nothing else.

`book_id` carries one too, and it is not decoration. It is the foreign key to a
parent that gets deleted: SQLite checks the child side once per deleted parent
row, so without it purging books from the trash is quadratic, which is the
lesson `a17c5b2e94d0` exists to record.

No downgrade data step. The table is new, so dropping it loses only what this
revision made possible to record, and there is nowhere older to put it.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "f7c2a1e50b93"
down_revision: str | Sequence[str] | None = "e6f1a94b2d73"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "reading_progress",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("book_id", sa.Integer(), nullable=False),
        sa.Column(
            "recorded_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("page", sa.Integer(), nullable=True),
        sa.Column("percent", sa.Integer(), nullable=True),
        sa.Column("minutes", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["book_id"], ["books.id"]),
        sa.PrimaryKeyConstraint("id"),
        # Kept character for character identical to models.py. Two spellings of
        # one rule drift, and the database's is the one that is enforced.
        sa.CheckConstraint(
            "(page IS NULL) <> (percent IS NULL)",
            name="ck_reading_progress_one_unit",
        ),
        sa.CheckConstraint(
            "(page IS NULL OR page > 0) "
            "AND (percent IS NULL OR (percent >= 0 AND percent <= 100)) "
            "AND (minutes IS NULL OR minutes > 0)",
            name="ck_reading_progress_bounds",
        ),
    )
    op.create_index("ix_reading_progress_id", "reading_progress", ["id"])
    op.create_index("ix_reading_progress_book_id", "reading_progress", ["book_id"])
    op.create_index(
        "ix_reading_progress_user_book_time",
        "reading_progress",
        ["user_id", "book_id", "recorded_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_reading_progress_user_book_time", table_name="reading_progress")
    op.drop_index("ix_reading_progress_book_id", table_name="reading_progress")
    op.drop_index("ix_reading_progress_id", table_name="reading_progress")
    op.drop_table("reading_progress")
