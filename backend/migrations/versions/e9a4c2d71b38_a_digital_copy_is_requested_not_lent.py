"""A digital copy is requested and granted, not lent.

Revision ID: e9a4c2d71b38
Revises: d3f8a1c6b250
Create Date: 2026-10-15

One table hanging off a book: a member asking the holder of a digital copy
for access, and the holder's answer. The holder is stored on the row when the
request is made. `models.AccessRequest` says why
it is a table of its own rather than a kind of loan.

No backfill. An open loan already recorded on a digital row stays exactly as it
is and can still be returned; only a new loan on one is refused.

Downgrade drops the table and every request with it, which is the only place
they live.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "e9a4c2d71b38"
down_revision: str | None = "d3f8a1c6b250"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "access_requests",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("book_id", sa.Integer(), nullable=False),
        sa.Column("requested_by_user_id", sa.Integer(), nullable=False),
        sa.Column("holder_user_id", sa.Integer(), nullable=False),
        sa.Column(
            "requested_at", sa.DateTime(), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("granted", sa.Boolean(), nullable=True),
        sa.Column("decided_by_user_id", sa.Integer(), nullable=True),
        sa.Column("decided_at", sa.DateTime(), nullable=True),
        sa.CheckConstraint(
            "(granted IS NULL) = (decided_at IS NULL) "
            "AND (granted IS NULL) = (decided_by_user_id IS NULL)",
            name="ck_access_requests_decision",
        ),
        sa.CheckConstraint(
            "holder_user_id <> requested_by_user_id",
            name="ck_access_requests_two_parties",
        ),
        sa.ForeignKeyConstraint(["book_id"], ["books.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["requested_by_user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["holder_user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["decided_by_user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_access_requests_id"), "access_requests", ["id"])
    op.create_index(op.f("ix_access_requests_book_id"), "access_requests", ["book_id"])
    op.create_index(
        op.f("ix_access_requests_requested_by_user_id"),
        "access_requests",
        ["requested_by_user_id"],
    )
    op.create_index(
        op.f("ix_access_requests_holder_user_id"),
        "access_requests",
        ["holder_user_id"],
    )
    op.create_index(
        op.f("ix_access_requests_decided_by_user_id"),
        "access_requests",
        ["decided_by_user_id"],
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_access_requests_decided_by_user_id"), table_name="access_requests")
    op.drop_index(op.f("ix_access_requests_holder_user_id"), table_name="access_requests")
    op.drop_index(
        op.f("ix_access_requests_requested_by_user_id"), table_name="access_requests"
    )
    op.drop_index(op.f("ix_access_requests_book_id"), table_name="access_requests")
    op.drop_index(op.f("ix_access_requests_id"), table_name="access_requests")
    op.drop_table("access_requests")
