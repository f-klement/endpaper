"""An author identifier records which file supplied it and which checked it.

Revision ID: bb6650065133
Revises: 3091190ff9ad
Create Date: 2026-11-22

Two columns on `author_identifiers`: `asserted_by`, the file the value came
from, and `checked_by`, the second file that named the same value, or null.
`enums.AuthoritySupplier` says what each member means.

**Existing rows are backfilled `unrecorded`, never guessed.** A `member` row
under `lcnaf` is either a Library of Congress confirmation or a cross reference
read off a GND record, and the row cannot say which. A `catalogue` row could be
read back as `catalogue`, and is not: the owner ruled every row stored before
this revision `unrecorded`, so one word means one thing across the table.

**The server default exists only for the backfill** and is dropped in the same
revision, so every writer must name its supplier and a writer that forgets fails
at the insert. `checked_by` stays null on every existing row: nothing recorded a
check before this.

Downgrade drops the four constraints and both columns. Nothing else read them.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "bb6650065133"
down_revision: str | Sequence[str] | None = "3091190ff9ad"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

#: Written out rather than imported from `models` or `enums`, for the reason
#: `a4c73e0b19d5` gives: a migration describes the schema at one point in time.
_CHECKS = {
    "ck_author_identifiers_asserted_by": (
        "asserted_by IN ('catalogue', 'member', 'lobid', 'wikidata', 'viaf', 'loc', 'orcid', 'bnp',"
        " 'unrecorded')"
    ),
    "ck_author_identifiers_checked_by": (
        "checked_by IS NULL OR checked_by IN"
        " ('catalogue', 'lobid', 'wikidata', 'viaf', 'loc', 'orcid', 'bnp')"
    ),
    "ck_author_identifiers_second_file": "checked_by IS NULL OR checked_by <> asserted_by",
    "ck_author_identifiers_supplier": (
        "asserted_by = 'unrecorded'"
        " OR (provenance = 'catalogue' AND asserted_by = 'catalogue')"
        " OR (provenance <> 'catalogue' AND asserted_by <> 'catalogue')"
    ),
}


def upgrade() -> None:
    with op.batch_alter_table("author_identifiers") as batch:
        batch.add_column(
            sa.Column("asserted_by", sa.String(length=20), nullable=False, server_default="unrecorded")
        )
        batch.add_column(sa.Column("checked_by", sa.String(length=20), nullable=True))
    with op.batch_alter_table("author_identifiers") as batch:
        batch.alter_column("asserted_by", existing_type=sa.String(length=20), server_default=None)
        for name, expression in _CHECKS.items():
            batch.create_check_constraint(name, expression)


def downgrade() -> None:
    with op.batch_alter_table("author_identifiers") as batch:
        for name in _CHECKS:
            batch.drop_constraint(name, type_="check")
        batch.drop_column("checked_by")
        batch.drop_column("asserted_by")
