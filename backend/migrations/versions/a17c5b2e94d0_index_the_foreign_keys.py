"""Index the foreign keys.

Revision ID: a17c5b2e94d0
Revises: d4a91f3c72e8

Not one foreign key column carried an index, so every lookup by it was a full
table scan: the notes and loans of one book, one member's shelf, everything
tagged Fantasy.

Enabling `PRAGMA foreign_keys` in the same release makes this urgent rather
than merely wasteful. SQLite checks the child side on every parent delete, and
with no index that check is a scan per deleted row, which turns emptying the
trash into quadratic work.

`loaned_by_user_id` is deliberately left alone: nothing queries by it, it is
carried for the record of who lent the book out.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "a17c5b2e94d0"
down_revision: str | None = "d4a91f3c72e8"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None

_INDEXES: Sequence[tuple[str, str, str]] = (
    ("ix_books_added_by_user_id", "books", "added_by_user_id"),
    ("ix_user_books_book_id", "user_books", "book_id"),
    ("ix_loans_book_id", "loans", "book_id"),
    ("ix_loans_loaned_to_user_id", "loans", "loaned_to_user_id"),
    ("ix_notes_book_id", "notes", "book_id"),
    ("ix_book_tags_tag_id", "book_tags", "tag_id"),
)


def upgrade() -> None:
    for name, table, column in _INDEXES:
        op.create_index(name, table, [column], if_not_exists=True)


def downgrade() -> None:
    for name, table, _column in _INDEXES:
        op.drop_index(name, table_name=table, if_exists=True)
