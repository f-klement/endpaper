"""A harvest's headings wait as suggestions

Revision ID: b7d4e2a9c615
Revises: 6dac941f868b
Create Date: 2026-11-21

One table, `pending_headings`: a heading a harvested record carries, kept on the
Book until an admin confirms or discards the Book's set. `models.PendingHeading`
says why it is not a `classifications` row and why a settled row stays.

No backfill: no harvest kept a heading before this.

Downgrade drops the table and every suggestion with it, confirmed headings
excepted, which are `classifications` rows.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "b7d4e2a9c615"
down_revision: str | Sequence[str] | None = "6dac941f868b"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_UNIQUE = "uq_pending_headings_book_scheme_number"


def upgrade() -> None:
    op.create_table(
        "pending_headings",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("book_id", sa.Integer(), nullable=False),
        sa.Column("harvest_id", sa.Integer(), nullable=False),
        sa.Column("scheme", sa.String(length=20), nullable=False),
        sa.Column("number", sa.String(length=120), nullable=False),
        sa.Column("label", sa.String(length=200), nullable=True),
        sa.Column("kind", sa.String(length=20), nullable=True),
        sa.Column("settled_at", sa.DateTime(), nullable=True),
        # A copy of what `ck_classifications_kind` renders, not a derivation,
        # for the reason `d5c31b7a09fe` gives: a revision records a day.
        sa.CheckConstraint(
            sa.text("kind IS NULL OR kind IN ('content', 'carrier')"),
            name="ck_pending_headings_kind",
        ),
        sa.ForeignKeyConstraint(["book_id"], ["books.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["harvest_id"], ["harvests.id"], name="fk_pending_headings_harvest_id"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_pending_headings_id"), "pending_headings", ["id"])
    op.create_index(_UNIQUE, "pending_headings", ["book_id", "scheme", "number"], unique=True)


def downgrade() -> None:
    op.drop_index(_UNIQUE, table_name="pending_headings")
    op.drop_index(op.f("ix_pending_headings_id"), table_name="pending_headings")
    op.drop_table("pending_headings")
