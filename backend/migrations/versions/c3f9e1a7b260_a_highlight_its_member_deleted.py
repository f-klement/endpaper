"""A highlight its member deleted, remembered so an import leaves it deleted.

Revision ID: c3f9e1a7b260
Revises: b4e7a1c9d352
Create Date: 2026-10-15

One table, `deleted_highlights`: the identity `highlights` is unique on, and
when. `models.DeletedHighlight` says why it holds nothing of the passage and
why it does not hang off a Book.

No backfill: no path deleted a highlight by hand before this.

Downgrade drops the table, so the next import brings back every highlight a
member deleted.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from dialect import DialectSQL

revision: str = "c3f9e1a7b260"
down_revision: str | Sequence[str] | None = "b4e7a1c9d352"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

#: `models.HIGHLIGHT_SOURCE_KEY_MAX` as it stood on the day this ran, written
#: out for the reason `e5b2c8f14a37` gives.
_KEY_MAX = 64

#: The source list as it stood on the day this ran, for the reason
#: `c7b0a3e5d281` gives.
_SOURCES = ("koreader", "readwise")


def upgrade() -> None:
    sources = ", ".join(f"'{source}'" for source in _SOURCES)
    op.create_table(
        "deleted_highlights",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("source", sa.String(length=16), nullable=False),
        sa.Column("source_key", sa.String(length=_KEY_MAX), nullable=False),
        sa.Column("deleted_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint(f"source IN ({sources})", name="ck_deleted_highlights_source"),
        sa.CheckConstraint(
            DialectSQL(
                sqlite=(
                    "length(source_key) > 0 "
                    f"AND length(source_key) <= {_KEY_MAX} "
                    "AND instr(source_key, char(0)) = 0 "
                    f"AND length(CAST(source_key AS BLOB)) <= {4 * _KEY_MAX}"
                ),
                postgresql=(
                    "length(source_key) > 0 "
                    f"AND length(source_key) <= {_KEY_MAX} "
                    f"AND octet_length(source_key) <= {4 * _KEY_MAX}"
                ),
            ),
            name="ck_deleted_highlights_bounds",
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_deleted_highlights_id"), "deleted_highlights", ["id"])
    op.create_index(
        "uq_deleted_highlights_member_source_key",
        "deleted_highlights",
        ["user_id", "source", "source_key"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("uq_deleted_highlights_member_source_key", table_name="deleted_highlights")
    op.drop_index(op.f("ix_deleted_highlights_id"), table_name="deleted_highlights")
    op.drop_table("deleted_highlights")
