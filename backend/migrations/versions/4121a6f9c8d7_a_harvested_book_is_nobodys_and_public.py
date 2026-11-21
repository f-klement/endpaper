"""A harvested Book is nobody's, and public

Revision ID: 4121a6f9c8d7
Revises: f009f139047c
Create Date: 2026-11-20

`harvests` holds one row per run of the OAI-PMH harvester, and `books` gains
`harvest_id`, the run a row came from. `ck_books_harvested_is_nobodys_and_public`
lets a row name a run only while it has no adder and is not private.
`models.Harvest` says why a run stands where an owner would.

**No backfill and no data step.** Every existing row has a null `harvest_id`,
which satisfies the new constraint whatever its adder and privacy, and
`added_by_user_id` was nullable from the baseline.

**The rebuild keeps `AUTOINCREMENT`** through `table_kwargs`, for the reason
`0850786d1753` gives, and keeps the partial ISBN index, which `c2f95a80d417`
measured surviving the same rebuild.

The downgrade leaves a harvested row as an ownerless public one, which the
older schema already holds and which an admin may purge.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "4121a6f9c8d7"
down_revision: str | Sequence[str] | None = "f009f139047c"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_CHECK = "ck_books_harvested_is_nobodys_and_public"
_FK = "fk_books_harvest_id"
_INDEX = "ix_books_harvest_id"

# A copy, not an import of `models.HARVESTED_IS_NOBODYS_AND_PUBLIC_SQL`, for the
# reason `d5c31b7a09fe` gives: a revision records what was applied on a day.
_NOBODYS_AND_PUBLIC = "harvest_id IS NULL OR (added_by_user_id IS NULL AND NOT is_private)"


def upgrade() -> None:
    op.create_table(
        "harvests",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("base_url", sa.String(length=255), nullable=False),
        sa.Column("set_spec", sa.String(length=255), nullable=True),
        sa.Column("metadata_prefix", sa.String(length=32), nullable=False),
        sa.Column("run_by_user_id", sa.Integer(), nullable=True),
        sa.Column("started_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("finished_at", sa.DateTime(), nullable=True),
        sa.Column("records_seen", sa.Integer(), server_default="0", nullable=False),
        sa.Column("records_added", sa.Integer(), server_default="0", nullable=False),
        sa.ForeignKeyConstraint(["run_by_user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_harvests_id", "harvests", ["id"])

    with op.batch_alter_table("books", table_kwargs={"sqlite_autoincrement": True}) as batch:
        batch.add_column(sa.Column("harvest_id", sa.Integer(), nullable=True))
        batch.create_foreign_key(_FK, "harvests", ["harvest_id"], ["id"])
        batch.create_check_constraint(_CHECK, _NOBODYS_AND_PUBLIC)
    op.create_index(_INDEX, "books", ["harvest_id"])


def downgrade() -> None:
    op.drop_index(_INDEX, table_name="books")
    with op.batch_alter_table("books", table_kwargs={"sqlite_autoincrement": True}) as batch:
        batch.drop_constraint(_CHECK, type_="check")
        batch.drop_constraint(_FK, type_="foreignkey")
        batch.drop_column("harvest_id")

    op.drop_index("ix_harvests_id", table_name="harvests")
    op.drop_table("harvests")
