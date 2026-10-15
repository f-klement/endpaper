"""A member's own login elsewhere, and the Readwise books it pulls from.

Revision ID: b4e7a1c9d352
Revises: d6b2f8a41c37
Create Date: 2026-10-15

Two tables. `member_logins` is the third kind of secret `credentials.py`
names, a member's own login at a service elsewhere, sealed and owned by one
member, with the Readwise pull's cursor and last outcome beside it.
`readwise_books` records which Book each of a member's Readwise books is, or
that none is yet. `models.MemberLogin` and `models.ReadwiseBook` say why.

**Both cascade from the member**, which is the rule that a member's own login
is deleted with them.

No backfill: nobody has saved a token yet.

Downgrade drops both tables, and every saved token with them; the highlights
already pulled stay in `highlights`.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from dialect import DialectSQL

revision: str = "b4e7a1c9d352"
down_revision: str | Sequence[str] | None = "d6b2f8a41c37"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

#: Kept in step with the constants in `models.py` and written out rather than
#: imported, for the reason every revision here gives: a migration describes the
#: schema at one moment and must not move when a constant does.
_ENVELOPE_MAX_BYTES = 317
_TITLE = 500
_AUTHOR = 500
_ASIN = 60
_CURSOR = 512

#: The enum lists as they stood on the day this ran, spelled out for the
#: reason `c7b0a3e5d281` gives.
_SERVICES = ("readwise",)
_OUTCOMES = (
    "synced",
    "incomplete",
    "token_refused",
    "rate_limited",
    "unavailable",
    "unreadable",
)


def _listed(column: str, values: Sequence[str]) -> str:
    return f"{column} IN (" + ", ".join(f"'{value}'" for value in values) + ")"


def _bounded(column: str, ceiling: int, blob: str, *, nullable: bool) -> str:
    rule = f"length({column}) <= {ceiling} AND {blob.format(column)} <= {4 * ceiling}"
    return f"({column} IS NULL OR ({rule}))" if nullable else rule


def _book_bounds(blob: str) -> str:
    return " AND ".join(
        [
            "user_book_id > 0",
            _bounded("title", _TITLE, blob, nullable=False),
            _bounded("author", _AUTHOR, blob, nullable=True),
            _bounded("asin", _ASIN, blob, nullable=True),
        ]
    )


def upgrade() -> None:
    op.create_table(
        "member_logins",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("service", sa.String(length=16), nullable=False),
        sa.Column("envelope", sa.Text(), nullable=False),
        sa.Column("set_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("synced_through", sa.DateTime(), nullable=True),
        sa.Column("last_run_at", sa.DateTime(), nullable=True),
        sa.Column("last_outcome", sa.String(length=16), nullable=True),
        sa.Column("resume_cursor", sa.String(length=_CURSOR), nullable=True),
        sa.Column("walk_started_at", sa.DateTime(), nullable=True),
        sa.CheckConstraint(_listed("service", _SERVICES), name="ck_member_logins_service"),
        sa.CheckConstraint(
            "last_outcome IS NULL OR " + _listed("last_outcome", _OUTCOMES),
            name="ck_member_logins_last_outcome",
        ),
        sa.CheckConstraint(
            DialectSQL(
                sqlite=(
                    "substr(envelope, 1, 3) = 'v2.' AND length(envelope) >= 40 "
                    f"AND length(CAST(envelope AS BLOB)) <= {_ENVELOPE_MAX_BYTES}"
                ),
                postgresql=(
                    "substr(envelope, 1, 3) = 'v2.' AND length(envelope) >= 40 "
                    f"AND octet_length(envelope) <= {_ENVELOPE_MAX_BYTES}"
                ),
            ),
            name="ck_member_logins_envelope",
        ),
        sa.CheckConstraint(
            DialectSQL(
                sqlite=(
                    f"length(resume_cursor) <= {_CURSOR} "
                    f"AND length(CAST(resume_cursor AS BLOB)) <= {4 * _CURSOR}"
                ),
                postgresql=(
                    f"length(resume_cursor) <= {_CURSOR} "
                    f"AND octet_length(resume_cursor) <= {4 * _CURSOR}"
                ),
            ),
            name="ck_member_logins_resume_cursor",
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "uq_member_logins_user_service",
        "member_logins",
        ["user_id", "service"],
        unique=True,
    )

    op.create_table(
        "readwise_books",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("user_book_id", sa.BigInteger(), nullable=False),
        sa.Column("title", sa.String(length=_TITLE), nullable=False),
        sa.Column("author", sa.String(length=_AUTHOR), nullable=True),
        sa.Column("asin", sa.String(length=_ASIN), nullable=True),
        sa.Column("book_id", sa.Integer(), nullable=True),
        sa.Column("whole_pending", sa.Boolean(), server_default="0", nullable=False),
        sa.CheckConstraint(
            DialectSQL(
                sqlite=_book_bounds("length(CAST({} AS BLOB))"),
                postgresql=_book_bounds("octet_length({})"),
            ),
            name="ck_readwise_books_bounds",
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["book_id"], ["books.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_readwise_books_book_id"), "readwise_books", ["book_id"])
    op.create_index(
        "uq_readwise_books_user_book",
        "readwise_books",
        ["user_id", "user_book_id"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("uq_readwise_books_user_book", table_name="readwise_books")
    op.drop_index(op.f("ix_readwise_books_book_id"), table_name="readwise_books")
    op.drop_table("readwise_books")
    op.drop_index("uq_member_logins_user_service", table_name="member_logins")
    op.drop_table("member_logins")
