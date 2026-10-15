"""The fingerprint KOReader names a file by, on the reference to it.

Revision ID: c4e8a2f61d93
Revises: e9a4c2d71b38
Create Date: 2026-10-15

One nullable column on `digital_references`, its index and its CHECK.
`models.DigitalReference.partial_md5` says what the digest samples and why it
is this digest rather than a full one.

**Nullable, and no backfill is possible.** The digest is computed in the
member's browser while the file is in hand, and this server never holds the
file, so a reference written before this revision gains one only when a client
reports that file again.

**Batch mode for the CHECK**, because SQLite cannot add one to an existing
table: the table is rebuilt and reflection carries
`uq_digital_references_location` and `ck_digital_references_bounds` across.

Downgrade drops the column and every digest with it, which is the only place
they live.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from dialect import DialectSQL

revision: str = "c4e8a2f61d93"
down_revision: str | Sequence[str] | None = "e9a4c2d71b38"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

#: Kept in step with `models.PARTIAL_MD5_HEX` and written out rather than
#: imported, for the reason every revision here gives: a migration describes the
#: schema at one moment and must not move when a constant does.
_HEX = 32


def upgrade() -> None:
    op.add_column(
        "digital_references",
        sa.Column("partial_md5", sa.String(length=_HEX), nullable=True),
    )
    op.create_index(
        op.f("ix_digital_references_partial_md5"),
        "digital_references",
        ["partial_md5"],
    )
    with op.batch_alter_table("digital_references") as batch:
        batch.create_check_constraint(
            "ck_digital_references_partial_md5",
            DialectSQL(
                sqlite=(
                    "instr(partial_md5, char(0)) = 0 "
                    f"AND partial_md5 GLOB '{'[0-9a-f]' * _HEX}'"
                ),
                postgresql=f"(partial_md5 COLLATE \"C\") ~ '^[0-9a-f]{{{_HEX}}}$'",
            ),
        )


def downgrade() -> None:
    with op.batch_alter_table("digital_references") as batch:
        batch.drop_constraint("ck_digital_references_partial_md5", type_="check")
    op.drop_index(
        op.f("ix_digital_references_partial_md5"), table_name="digital_references"
    )
    with op.batch_alter_table("digital_references") as batch:
        batch.drop_column("partial_md5")
