"""Named collections, and one per book.

Revision ID: c2f95a80d417
Revises: b1e7c94a2d05
Create Date: 2026-08-23

A library separates physical from ebook, kept from sold, and one person's
shelf from another's. All three are partitions, so a book carries **one**
collection: a nullable `books.collection_id` rather than a join table.

**No backfill and no invented collection.** Every book that exists predates
this migration, and every one of them stays unfiled. Creating a default
collection would mean choosing its name here, which is a name in one language
that nobody picked, and it would put the feature in front of every library
that never asked for it. Unfiled is a real state and the API says so.

`ON DELETE SET NULL`: deleting a collection unfiles its books and destroys
none of them. The rule is in the database rather than in the handler because a
restore and a hand-edited row reach the table without passing the handler.

The name is unique **case insensitively**, through a functional index on
`lower(name)`. Two shelves called "Ebooks" and "ebooks" are a typo that nothing
downstream can tell apart.

**The books rewrite keeps the partial ISBN index.** `batch_alter_table` rebuilds
the table by reflecting it, and d5c31b7a09fe had to drop and recreate
`uq_loans_one_open_per_book` around exactly this step because a partial index
returning as a plain unique one would have forbidden lending a book twice. The
same hazard applies to `uq_books_isbn_single_copy`, so it was measured rather
than assumed: after this migration on SQLAlchemy 2.0.52 with Alembic 1.19.1 the
index is still
`CREATE UNIQUE INDEX uq_books_isbn_single_copy ON books (isbn) WHERE copy_group
IS NULL`, predicate intact, alongside the new foreign key that proves the table
really was rewritten. No dance is needed here; if that reflection ever
regresses, the fix is d5c31b7a09fe's.

Downgrade drops the table and the column, which loses which books were in which
collection. Nothing else can happen: the column is the only place that fact
lives.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "c2f95a80d417"
down_revision: str | Sequence[str] | None = "b1e7c94a2d05"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "collections",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=80), nullable=False),
        sa.Column("created_by_user_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_collections_id", "collections", ["id"])
    # `created_by_user_id` is deliberately not indexed: nothing queries by it,
    # and no path deletes a user, so there is no child check to speed up.
    # Written as a text expression because the index is on `lower(name)` rather
    # than on a column. A stored lowercase column would be the same name twice.
    op.create_index(
        "uq_collections_name_nocase",
        "collections",
        [sa.text("lower(name)")],
        unique=True,
    )

    # batch_alter_table because SQLite rebuilds the table rather than altering
    # it, and a foreign key cannot be added any other way here.
    with op.batch_alter_table("books") as batch:
        batch.add_column(sa.Column("collection_id", sa.Integer(), nullable=True))
        batch.create_foreign_key(
            "fk_books_collection_id",
            "collections",
            ["collection_id"],
            ["id"],
            ondelete="SET NULL",
        )
    op.create_index("ix_books_collection_id", "books", ["collection_id"])


def downgrade() -> None:
    op.drop_index("ix_books_collection_id", table_name="books")
    with op.batch_alter_table("books") as batch:
        batch.drop_constraint("fk_books_collection_id", type_="foreignkey")
        batch.drop_column("collection_id")

    op.drop_index("uq_collections_name_nocase", table_name="collections")
    op.drop_index("ix_collections_id", table_name="collections")
    op.drop_table("collections")
