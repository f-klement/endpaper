"""Further images of a Book, kept beside the shelf cover.

Revision ID: 8a7989a3fab0
Revises: 5c3e9a1d7b20
Create Date: 2026-11-19

One table, `cover_images`: a row per image, its file named by the row's id.
`models.CoverImage` says why the shelf cover stays `books.cover_url`.

**`sqlite_autoincrement`**, because the id is the file's name: see the model.

No backfill: nothing kept a second image before this.

Downgrade drops the table. The files stay on disk with no row naming them; a
backup taken after the downgrade still carries them, and nothing serves them.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "8a7989a3fab0"
down_revision: str | Sequence[str] | None = "5c3e9a1d7b20"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

#: `config.ALLOWED_IMAGE_EXTENSIONS` as it stood on the day this ran, written
#: out for the reason `e5b2c8f14a37` gives.
_EXTENSIONS = ("jpeg", "jpg", "png", "webp")


def upgrade() -> None:
    extensions = ", ".join(f"'{extension}'" for extension in _EXTENSIONS)
    op.create_table(
        "cover_images",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("book_id", sa.Integer(), nullable=False),
        sa.Column("extension", sa.String(length=4), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint(f"extension IN ({extensions})", name="ck_cover_images_extension"),
        sa.ForeignKeyConstraint(["book_id"], ["books.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sqlite_autoincrement=True,
    )
    op.create_index(op.f("ix_cover_images_id"), "cover_images", ["id"])
    op.create_index(op.f("ix_cover_images_book_id"), "cover_images", ["book_id"])


def downgrade() -> None:
    op.drop_index(op.f("ix_cover_images_book_id"), table_name="cover_images")
    op.drop_index(op.f("ix_cover_images_id"), table_name="cover_images")
    op.drop_table("cover_images")
