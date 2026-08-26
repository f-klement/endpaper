"""Tags a library can invent for itself.

One column. Every tag that exists when this runs was put there by
`seed_tags()`, because until now there was no other way for one to appear, so
the backfill is unconditional and exact rather than a guess.

The flag has to be stored rather than derived from the seed list. Testing "is
this name in PREDEFINED_TAGS" would silently reclassify a tag the moment
somebody renamed one there, and renaming a seeded tag has already happened once
in this repository (see 95b6a61d6668).

Revision ID: d4a91f3c72e8
Revises: c9f2a8e41b06
Create Date: 2026-08-19
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "d4a91f3c72e8"
down_revision: str | Sequence[str] | None = "c9f2a8e41b06"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("tags") as batch:
        batch.add_column(
            sa.Column(
                "is_predefined",
                sa.Boolean(),
                nullable=False,
                server_default="0",
            )
        )

    # Everything already here came from the seed list.
    op.execute(sa.text("UPDATE tags SET is_predefined = 1"))


def downgrade() -> None:
    # A tag the library invented has no meaning without the flag, and leaving
    # it behind would put "Holiday reads" into the curated genre list.
    #
    # **The association rows go first, and that ordering is not cosmetic.**
    # `book_tags` declares ON DELETE CASCADE, but SQLite only enforces foreign
    # keys when `PRAGMA foreign_keys` is on, which it is not here. Deleting the
    # tags alone leaves rows pointing at ids that no longer exist, SQLite hands
    # the freed id to the next tag created, and a book that carried "Holiday
    # reads" silently carries whatever took its place. Demonstrated on a
    # downgrade followed by an upgrade.
    op.execute(
        sa.text(
            "DELETE FROM book_tags WHERE tag_id IN "
            "(SELECT id FROM tags WHERE is_predefined = 0)"
        )
    )
    op.execute(sa.text("DELETE FROM tags WHERE is_predefined = 0"))

    with op.batch_alter_table("tags") as batch:
        batch.drop_column("is_predefined")
