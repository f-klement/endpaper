"""A highlight marked on a reading device.

Revision ID: e5b2c8f14a37
Revises: c4e8a2f61d93
Create Date: 2026-10-15

One table hanging off a book and a member, shaped after `notes` and `quotes`.
`models.Highlight` says why it is neither of them: private by default, shared
per row, and identified at its source so every import re-runs safely.

**The unique index is the import's whole idempotence.** `(user_id, source,
source_key)`, not keyed on the Book, so a merge moves rows without a collision.

No backfill: nothing in an existing database is a highlight.

Downgrade drops the table and every highlight with it, which is the only place
they live.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from dialect import DialectSQL

revision: str = "e5b2c8f14a37"
down_revision: str | Sequence[str] | None = "c4e8a2f61d93"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

#: Kept in step with the constants in `models.py` beside `Highlight`, and
#: written out rather than imported: a migration describes the schema at one
#: moment and must not move when a constant does.
_MAX_PAGE = 100_000
_TEXT_MAX = 10_000
_NOTE_MAX = 10_000
_CHAPTER_MAX = 1_000
_KEY_MAX = 64

#: The source list as it stood on the day this ran, spelled out rather than
#: derived from `enums.HighlightSource`, for the reason `c7b0a3e5d281` gives.
_SOURCES = ("koreader", "readwise")


def upgrade() -> None:
    sources = ", ".join(f"'{source}'" for source in _SOURCES)
    op.create_table(
        "highlights",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("book_id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("source", sa.String(length=16), nullable=False),
        sa.Column("source_key", sa.String(length=_KEY_MAX), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("chapter", sa.String(length=_CHAPTER_MAX), nullable=True),
        sa.Column("page", sa.Integer(), nullable=True),
        sa.Column("highlighted_at", sa.DateTime(), nullable=True),
        sa.Column("is_shared", sa.Boolean(), server_default="0", nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint(f"source IN ({sources})", name="ck_highlights_source"),
        sa.CheckConstraint(
            f"page IS NULL OR (page > 0 AND page <= {_MAX_PAGE})",
            name="ck_highlights_page_bounds",
        ),
        sa.CheckConstraint(
            DialectSQL(
                sqlite=(
                    f"length(text) > 0 AND length(text) <= {_TEXT_MAX} "
                    f"AND length(CAST(text AS BLOB)) <= {4 * _TEXT_MAX} "
                    f"AND (note IS NULL OR (length(note) <= {_NOTE_MAX} "
                    f"AND length(CAST(note AS BLOB)) <= {4 * _NOTE_MAX})) "
                    f"AND (chapter IS NULL OR (length(chapter) <= {_CHAPTER_MAX} "
                    f"AND length(CAST(chapter AS BLOB)) <= {4 * _CHAPTER_MAX})) "
                    f"AND length(source_key) > 0 "
                    f"AND length(source_key) <= {_KEY_MAX} "
                    "AND instr(source_key, char(0)) = 0 "
                    f"AND length(CAST(source_key AS BLOB)) <= {4 * _KEY_MAX}"
                ),
                postgresql=(
                    f"length(text) > 0 AND length(text) <= {_TEXT_MAX} "
                    f"AND octet_length(text) <= {4 * _TEXT_MAX} "
                    f"AND (note IS NULL OR (length(note) <= {_NOTE_MAX} "
                    f"AND octet_length(note) <= {4 * _NOTE_MAX})) "
                    f"AND (chapter IS NULL OR (length(chapter) <= {_CHAPTER_MAX} "
                    f"AND octet_length(chapter) <= {4 * _CHAPTER_MAX})) "
                    f"AND length(source_key) > 0 "
                    f"AND length(source_key) <= {_KEY_MAX} "
                    f"AND octet_length(source_key) <= {4 * _KEY_MAX}"
                ),
            ),
            name="ck_highlights_bounds",
        ),
        sa.ForeignKeyConstraint(["book_id"], ["books.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_highlights_id"), "highlights", ["id"])
    op.create_index("ix_highlights_book_page", "highlights", ["book_id", "page"])
    op.create_index(
        "uq_highlights_member_source_key",
        "highlights",
        ["user_id", "source", "source_key"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("uq_highlights_member_source_key", table_name="highlights")
    op.drop_index("ix_highlights_book_page", table_name="highlights")
    op.drop_index(op.f("ix_highlights_id"), table_name="highlights")
    op.drop_table("highlights")
