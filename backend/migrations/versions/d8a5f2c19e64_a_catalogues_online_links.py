"""A catalogue record's online links, MARC 856, kept on the Book.

Revision ID: d8a5f2c19e64
Revises: c3f9e1a7b260
Create Date: 2026-10-15

One table, `online_links`: a URL, its link text and what it is to the Book.
`models.OnlineLink` says why it is not a file reference and why it is a table
rather than a column on `books` (856 repeats).

No backfill: no importer read 856 before this.

Downgrade drops the table and every link with it; the table is the only place
they live.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from dialect import DialectSQL

revision: str = "d8a5f2c19e64"
down_revision: str | Sequence[str] | None = "c3f9e1a7b260"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

#: `models.ONLINE_LINK_URL_MAX_BYTES` and `ONLINE_LINK_LABEL_MAX` as they stood
#: on the day this ran, written out for the reason `e5b2c8f14a37` gives.
_URL_MAX_BYTES = 2048
_LABEL_MAX = 200

#: The URL as a MARCXML record writes it, escaped, as `models._URL_AS_WRITTEN`
#: stood on the day this ran: the cap is on these bytes.
_URL_AS_WRITTEN = "replace(replace(replace(url, '&', '&amp;'), '<', '&lt;'), '>', '&gt;')"

#: The relation list as it stood on the day this ran, for the reason
#: `c7b0a3e5d281` gives.
_RELATIONS = ("resource", "version", "related")


def upgrade() -> None:
    relations = ", ".join(f"'{relation}'" for relation in _RELATIONS)
    op.create_table(
        "online_links",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("book_id", sa.Integer(), nullable=False),
        sa.Column("url", sa.String(length=_URL_MAX_BYTES), nullable=False),
        sa.Column("label", sa.String(length=_LABEL_MAX), nullable=True),
        sa.Column("relation", sa.String(length=10), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint(
            "url LIKE 'http://%' OR url LIKE 'https://%'",
            name="ck_online_links_scheme",
        ),
        sa.CheckConstraint(
            f"relation IS NULL OR relation IN ({relations})",
            name="ck_online_links_relation",
        ),
        sa.CheckConstraint(
            DialectSQL(
                sqlite=(
                    f"length(CAST({_URL_AS_WRITTEN} AS BLOB)) <= {_URL_MAX_BYTES} "
                    f"AND (label IS NULL OR (length(label) <= {_LABEL_MAX} "
                    f"AND length(CAST(label AS BLOB)) <= {4 * _LABEL_MAX}))"
                ),
                postgresql=(
                    f"octet_length({_URL_AS_WRITTEN}) <= {_URL_MAX_BYTES} "
                    f"AND (label IS NULL OR (length(label) <= {_LABEL_MAX} "
                    f"AND octet_length(label) <= {4 * _LABEL_MAX}))"
                ),
            ),
            name="ck_online_links_bounds",
        ),
        sa.ForeignKeyConstraint(["book_id"], ["books.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_online_links_id"), "online_links", ["id"])
    op.create_index("uq_online_links_book_url", "online_links", ["book_id", "url"], unique=True)


def downgrade() -> None:
    op.drop_index("uq_online_links_book_url", table_name="online_links")
    op.drop_index(op.f("ix_online_links_id"), table_name="online_links")
    op.drop_table("online_links")
