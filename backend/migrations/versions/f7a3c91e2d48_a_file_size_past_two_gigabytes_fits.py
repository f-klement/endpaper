"""A file size past two gigabytes fits its column on Postgres.

Revision ID: f7a3c91e2d48
Revises: 0850786d1753
Create Date: 2026-11-04

`digital_references.size_bytes` was `Integer`, which is four bytes on Postgres,
while the API accepts any size up to `Number.MAX_SAFE_INTEGER`: a reference to a
file of 2 GiB or more answered 500 there. SQLite's INTEGER already holds eight
bytes, so on SQLite this changes the declared type and nothing a row can hold.

**A batch rebuild on SQLite**, which cannot change a column's type in place.
Batch mode reflects the table and keeps its CHECK and its indexes, as
`0850786d1753` records for the same rebuild of `books`. On Postgres the same
call is one `ALTER COLUMN ... TYPE BIGINT`, which widens every stored value.

Downgrade narrows it back, and on Postgres refuses while a stored size is past
the four byte ceiling rather than losing it.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "f7a3c91e2d48"
down_revision: str | Sequence[str] | None = "0850786d1753"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _retype(to: sa.types.TypeEngine[int], was: sa.types.TypeEngine[int]) -> None:
    with op.batch_alter_table("digital_references") as batch:
        batch.alter_column("size_bytes", type_=to, existing_type=was, existing_nullable=True)


def upgrade() -> None:
    _retype(sa.BigInteger(), sa.Integer())


def downgrade() -> None:
    _retype(sa.Integer(), sa.BigInteger())
