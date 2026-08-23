"""Quotes from a book.

Revision ID: d3f6b81c9a27
Revises: a9c4e7b21d03
Create Date: 2026-08-23

A passage a member copied out, the page it is on, and optionally a remark
about it. One table hanging off a book and a user, shaped after `notes`.

**Its own table rather than columns on `notes`.** BookLogr, the Apache-2.0
reference, adds `quote_page` to its notes table and stops there, which leaves
nothing able to tell a quote from a note that happened to remember a page. The
excerpt is also the one string in this app that is supposed to be a faithful
transcription of somebody else's words, and a column shared with commentary is
the column where that stops being true.

**`text` is `String(2000)`, not `Text`.** Shorter than `notes.content`, which
takes 10,000, and deliberately: this is an excerpt of a copyrighted work, and
2,000 characters is about one printed page.

**The width is not what enforces it.** SQLite ignores VARCHAR width, so a Core
insert of 50,000 characters into a `String(2000)` column stores 50,000;
measured, not assumed. `ck_quotes_text_bounds` is therefore what makes the
ceiling real, and it covers `note` too.

Both CHECKs repeat what `QuoteCreate` already validates, for the same reason
`ck_reading_progress_bounds` does: a restore inserts through Core and never
sees a Pydantic model. That is the only path that reaches this table without
one today, and it is admin-only, so this closes a false claim rather than a
live hole.

No backfill: nothing in an existing database is a quote, and inventing one
from a note would guess at which notes were transcriptions.

Downgrade drops the table, which destroys every quote. Nothing else can
happen: the table is the only place they live. Honest rather than clever, and
the same shape as `c2f95a80d417`'s.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "d3f6b81c9a27"
down_revision: str | Sequence[str] | None = "a9c4e7b21d03"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

#: Kept in step with `models.MAX_PAGE_NUMBER_IN_A_BOOK`, and written out here
#: rather than imported: a migration describes the schema at one point in time
#: and must not change meaning when a constant is later retuned.
_MAX_PAGE = 100_000

#: Kept in step with `models.QUOTE_TEXT_MAX` and `models.QUOTE_NOTE_MAX`, and
#: written out for the same reason as the page ceiling above.
_TEXT_MAX = 2_000
_NOTE_MAX = 1_000


def upgrade() -> None:
    op.create_table(
        "quotes",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("book_id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("text", sa.String(length=2000), nullable=False),
        sa.Column("page", sa.Integer(), nullable=True),
        sa.Column("note", sa.String(length=1000), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint(
            f"page IS NULL OR (page > 0 AND page <= {_MAX_PAGE})",
            name="ck_quotes_page_bounds",
        ),
        sa.CheckConstraint(
            f"length(text) <= {_TEXT_MAX} "
            f"AND (note IS NULL OR length(note) <= {_NOTE_MAX})",
            name="ck_quotes_text_bounds",
        ),
        sa.ForeignKeyConstraint(["book_id"], ["books.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_quotes_id", "quotes", ["id"])
    # The book page reads a book's quotes in reading order, and the cross-book
    # listing joins on `book_id`. Both use this prefix, so there is **no**
    # standalone `ix_quotes_book_id` beside it: a composite leading with the
    # same column serves every lookup one would, and the second B-tree would be
    # written on every insert for nothing.
    op.create_index("ix_quotes_book_page", "quotes", ["book_id", "page"])
    # `user_id` is deliberately not indexed on its own: nothing lists a
    # member's quotes across the shelf by owner, and no path deletes a user, so
    # there is no child check to speed up. The same reasoning `c2f95a80d417`
    # applied to `collections.created_by_user_id`.


def downgrade() -> None:
    op.drop_index("ix_quotes_book_page", table_name="quotes")
    op.drop_index("ix_quotes_id", table_name="quotes")
    op.drop_table("quotes")
