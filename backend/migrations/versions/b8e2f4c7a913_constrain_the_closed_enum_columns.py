"""Constrain the two closed enum columns

Revision ID: b8e2f4c7a913
Revises: f4a10c92b7d6
Create Date: 2026-08-27

`backup.restore` inserts through Core, where neither a Pydantic model nor a
`@validates` hook fires, so an archive decides these values. A value outside the
enum then raises inside `OwnershipStatus(...)` or `CustomFieldKind(...)` at read
time, which 500s every request that touches the row rather than failing at the
write that caused it.

`custom_fields.kind` already carries its constraint, added with the feature.
This adds the matching one to `books.ownership`, which is the only other
**closed** enum column: owned, not owned, unknown is the whole of the question
and will not grow.

**The three that are deliberately not constrained** are `user_books.status`,
`classifications.scheme` and `tags.category`, and the reason is that SQLite
cannot ALTER a CHECK: adding an enum member to a constrained column means a
batch table rebuild, every time. `ReadStatus` has already grown once
(`WANT_TO_READ` was added later and kept distinct from `UNREAD`), and
`ClassificationScheme` grows whenever a catalogue source is added, which two
open issues propose doing. Those degrade at the read end instead, in the shape
`custom_fields._kind_of` uses, and `test_house_rules.py` holds the split.

**No refusal check runs here**, so nothing has to precede the DDL. That is worth
saying rather than leaving to be noticed: on SQLite a failed revision does not
reliably roll back, because pysqlite opens a transaction for DML only and DDL
executed while none is open is durable immediately. Where a revision refuses, the
check has to run before its first DDL statement. This one refuses nothing.

A row already outside the enum would fail the rebuild. That is the correct
outcome and is why this is a rebuild rather than a silent widening: such a row
cannot have been written by this application.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "b8e2f4c7a913"
down_revision: str | None = "f4a10c92b7d6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("books") as batch:
        batch.create_check_constraint(
            "ck_books_ownership",
            sa.text("ownership IN ('owned', 'not_owned', 'unknown')"),
        )


def downgrade() -> None:
    with op.batch_alter_table("books") as batch:
        batch.drop_constraint("ck_books_ownership", type_="check")
