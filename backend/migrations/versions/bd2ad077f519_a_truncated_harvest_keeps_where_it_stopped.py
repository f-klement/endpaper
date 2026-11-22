"""A truncated harvest keeps where it stopped, and the format it read

Revision ID: bd2ad077f519
Revises: b7d4e2a9c615
Create Date: 2026-11-22

Four nullable columns on `harvests`: `metadata_format`, the serialisation the
run read; `resume_token` and `resume_skip`, where a run cut short stopped; and
`continues_harvest_id`, the run a continued one carried on from.
`models.Harvest` says what each holds and why the last has no foreign key.

**No backfill.** No run recorded where it stopped before this revision, so no
existing row can be continued, and none needs its format. Reading a format back
out of `metadata_prefix` would be a guess: a repository names its own formats.

`metadata_format` is a plain `String(20)` behind `models.DegradingEnum`, for the
reason `f4a9c2e17b30` gives for `books.record_origin`.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "bd2ad077f519"
down_revision: str | Sequence[str] | None = "b7d4e2a9c615"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("harvests") as batch:
        batch.add_column(sa.Column("metadata_format", sa.String(20), nullable=True))
        batch.add_column(sa.Column("resume_token", sa.String(2000), nullable=True))
        batch.add_column(sa.Column("resume_skip", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("continues_harvest_id", sa.Integer(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("harvests") as batch:
        batch.drop_column("continues_harvest_id")
        batch.drop_column("resume_skip")
        batch.drop_column("resume_token")
        batch.drop_column("metadata_format")
