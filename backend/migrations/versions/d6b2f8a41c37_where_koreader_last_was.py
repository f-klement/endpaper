"""Where a member's KOReader last was, and the sync password it signs in with.

Revision ID: d6b2f8a41c37
Revises: e5b2c8f14a37
Create Date: 2026-10-15

Two nullable columns on `users`, the member's sync password as a digest and
when it was minted, and one table, `kosync_documents`, holding the latest
position a device pushed for each document. `models.KosyncDocument` says what
each column is for and `kosync.py` what a push does with it.

**No backfill.** Nobody has a sync password until they mint one, and no device
has pushed anything yet.

Downgrade drops the table and the two columns, and every position with them:
they live nowhere else, though each device still holds its own and pushes it
again on its next sync.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from dialect import DialectSQL

revision: str = "d6b2f8a41c37"
down_revision: str | Sequence[str] | None = "e5b2c8f14a37"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

#: Kept in step with the constants in `models.py` and written out rather than
#: imported, for the reason every revision here gives: a migration describes the
#: schema at one moment and must not move when a constant does.
_DIGEST_HEX = 64
_DOCUMENT = 64
_PROGRESS = 2048
_DEVICE = 255
_TITLE = 500
_AUTHORS = 500
_FILENAME = 255


def _bounded(column: str, ceiling: int, blob: str, *, nullable: bool) -> str:
    rule = f"length({column}) <= {ceiling} AND {blob.format(column)} <= {4 * ceiling}"
    return f"({column} IS NULL OR ({rule}))" if nullable else rule


def _bounds(blob: str) -> str:
    return " AND ".join(
        [
            _bounded("progress", _PROGRESS, blob, nullable=False),
            _bounded("device", _DEVICE, blob, nullable=False),
            _bounded("device_id", _DEVICE, blob, nullable=True),
            _bounded("title", _TITLE, blob, nullable=True),
            _bounded("authors", _AUTHORS, blob, nullable=True),
            _bounded("filename", _FILENAME, blob, nullable=True),
            "timestamp >= 0",
        ]
    )


def upgrade() -> None:
    with op.batch_alter_table("users") as batch:
        batch.add_column(
            sa.Column("kosync_key_digest", sa.String(length=_DIGEST_HEX), nullable=True)
        )
        batch.add_column(sa.Column("kosync_key_set_at", sa.DateTime(), nullable=True))

    op.create_table(
        "kosync_documents",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("document", sa.String(length=_DOCUMENT), nullable=False),
        sa.Column("progress", sa.String(length=_PROGRESS), nullable=False),
        sa.Column("percentage", sa.Float(), nullable=False),
        sa.Column("device", sa.String(length=_DEVICE), nullable=False),
        sa.Column("device_id", sa.String(length=_DEVICE), nullable=True),
        sa.Column("timestamp", sa.BigInteger(), nullable=False),
        sa.Column("title", sa.String(length=_TITLE), nullable=True),
        sa.Column("authors", sa.String(length=_AUTHORS), nullable=True),
        sa.Column("filename", sa.String(length=_FILENAME), nullable=True),
        sa.Column("book_id", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["book_id"], ["books.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint(
            DialectSQL(
                sqlite=(
                    f"length(document) BETWEEN 1 AND {_DOCUMENT} "
                    "AND instr(document, char(0)) = 0 "
                    "AND document NOT GLOB '*[^A-Za-z0-9_]*'"
                ),
                postgresql=(
                    f"length(document) BETWEEN 1 AND {_DOCUMENT} "
                    "AND (document COLLATE \"C\") !~ '[^A-Za-z0-9_]'"
                ),
            ),
            name="ck_kosync_documents_document",
        ),
        sa.CheckConstraint(
            DialectSQL(
                sqlite=_bounds("length(CAST({} AS BLOB))"),
                postgresql=_bounds("octet_length({})"),
            ),
            name="ck_kosync_documents_bounds",
        ),
    )
    op.create_index(op.f("ix_kosync_documents_id"), "kosync_documents", ["id"])
    op.create_index(op.f("ix_kosync_documents_book_id"), "kosync_documents", ["book_id"])
    op.create_index(
        "uq_kosync_documents_user_document",
        "kosync_documents",
        ["user_id", "document"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("uq_kosync_documents_user_document", table_name="kosync_documents")
    op.drop_index(op.f("ix_kosync_documents_book_id"), table_name="kosync_documents")
    op.drop_index(op.f("ix_kosync_documents_id"), table_name="kosync_documents")
    op.drop_table("kosync_documents")
    with op.batch_alter_table("users") as batch:
        batch.drop_column("kosync_key_set_at")
        batch.drop_column("kosync_key_digest")
