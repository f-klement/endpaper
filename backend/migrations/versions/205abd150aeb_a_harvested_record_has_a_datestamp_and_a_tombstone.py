"""A harvested record has a datestamp, and a record that left has a tombstone.

Revision ID: 205abd150aeb
Revises: f73ebc9f0436
Create Date: 2026-11-19

OAI-PMH (ticket 176) needs both. `books.oai_datestamp` is when what a harvester
reads of a record last changed, which selective harvesting filters on;
`oai_tombstones` holds one row per record that left the public shelf, its id and
when, because `Identify` advertises `deletedRecord` as `persistent`.

**Every existing Book gets one datestamp, the moment of this upgrade**, and
never its `added_at`: the public catalogue withholds when a household acquired
a book (`schemas.public.PublicBookSort`), and a header carrying `added_at`
would publish it for every Book at once. One instant costs nothing, since no
harvester has ever been told a datestamp and the first harvest takes everything.

**No tombstone is backfilled.** A tombstone answers a harvester that could have
seen the record, and none could: nothing was served over OAI-PMH before this.

Three steps on SQLite, because `ADD COLUMN` refuses a default that is not a
constant: the column goes in nullable, is filled, and the second batch rebuilds
the table with the default and `NOT NULL`. That rebuild is why both batches pass
`sqlite_autoincrement`: without it SQLite would reuse deleted Book ids, and a
reused id would inherit another Book's tombstone.
"""

from collections.abc import Sequence
from datetime import UTC, datetime

import sqlalchemy as sa
from alembic import op

revision: str = "205abd150aeb"
down_revision: str | Sequence[str] | None = "f73ebc9f0436"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_BOOKS = sa.table("books", sa.column("oai_datestamp", sa.DateTime()))


def upgrade() -> None:
    with op.batch_alter_table("books", table_kwargs={"sqlite_autoincrement": True}) as batch:
        batch.add_column(sa.Column("oai_datestamp", sa.DateTime(), nullable=True))
    # Naive UTC to the second, as `models.datestamp_now` writes it, but
    # computed here rather than by calling it, so the revision stays frozen.
    upgraded = datetime.now(UTC).replace(tzinfo=None, microsecond=0)
    op.execute(_BOOKS.update().values(oai_datestamp=upgraded))
    with op.batch_alter_table("books", table_kwargs={"sqlite_autoincrement": True}) as batch:
        batch.alter_column(
            "oai_datestamp",
            existing_type=sa.DateTime(),
            nullable=False,
            server_default=sa.func.now(),
        )
        batch.create_index(batch.f("ix_books_oai_datestamp"), ["oai_datestamp"], unique=False)

    op.create_table(
        "oai_tombstones",
        sa.Column("book_id", sa.Integer(), autoincrement=False, nullable=False),
        sa.Column("datestamp", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("book_id"),
    )
    with op.batch_alter_table("oai_tombstones") as batch:
        batch.create_index(batch.f("ix_oai_tombstones_datestamp"), ["datestamp"], unique=False)


def downgrade() -> None:
    with op.batch_alter_table("oai_tombstones") as batch:
        batch.drop_index(batch.f("ix_oai_tombstones_datestamp"))
    op.drop_table("oai_tombstones")
    with op.batch_alter_table("books", table_kwargs={"sqlite_autoincrement": True}) as batch:
        batch.drop_index(batch.f("ix_books_oai_datestamp"))
        batch.drop_column("oai_datestamp")
