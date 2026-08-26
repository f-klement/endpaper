"""Classifications stored whole.

Revision ID: e2c74a91b5d8
Revises: d3f6b81c9a27
Create Date: 2026-08-23

A scheme, a number and the caption a catalogue gave it: `DDC`, `004`,
`Informatik`. Until now the number was thrown away at parse time so the caption
could substring match a tag by name, which discarded the only language
independent half of the heading.

**Measured before it was written.** Ten German ISBNs put to the DNB on
2026-08-23: eight came back with a DDC heading, and every one of the eight
captions was German (`830 Deutsche Literatur`, `150 Psychologie`,
`360 Soziale Probleme, Sozialdienste, Versicherungen`). None of the eight
matched any of the 105 seeded tag names, so the caption based suggestion scored
zero on exactly the catalogue the DDC heading comes from.

**Its own table rather than columns on `books`.** A book carries several at
once: K10plus returned both `005.133` and `004` for one ISBN, and the Library
of Congress returns a DDC and an LCC side by side. Three columns on `books`
would hold the first and silently drop the rest.

**Unique per book, scheme and number.** Selecting the same record twice must
not deposit a second copy of every heading. Not unique on the number alone, for the two
reasons above: two schemes, and two precisions of one scheme, are both real.

`ondelete="CASCADE"` matches `book_tags` rather than `notes`: a heading is an
assertion about a book and means nothing without it. SQLite enforces that only
with `PRAGMA foreign_keys` on, which `database.py` sets, and the ORM
relationship carries `delete-orphan` besides.

No backfill. Nothing in an existing database holds a number to recover: the
parse dropped it before any row was written, and `books.categories` holds the
stripped captions with no way to tell which came from a classification.
Selecting a Catalogue record for a book fills it in.

Downgrade drops the table. Every heading goes with it, and there is nowhere
else they live.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "e2c74a91b5d8"
down_revision: str | Sequence[str] | None = "d3f6b81c9a27"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

#: Kept in step with `models.CLASSIFICATION_NUMBER_MAX` and
#: `models.CLASSIFICATION_LABEL_MAX`, and written out here rather than
#: imported: a migration describes the schema at one point in time and must not
#: change meaning when a constant is later retuned.
_NUMBER_MAX = 40
_LABEL_MAX = 200


def upgrade() -> None:
    op.create_table(
        "classifications",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("book_id", sa.Integer(), nullable=False),
        sa.Column("scheme", sa.String(length=20), nullable=False),
        sa.Column("number", sa.String(length=_NUMBER_MAX), nullable=False),
        sa.Column("label", sa.String(length=_LABEL_MAX), nullable=True),
        sa.ForeignKeyConstraint(["book_id"], ["books.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_classifications_id", "classifications", ["id"])
    # No standalone `ix_classifications_book_id` beside it: this composite
    # leads with the same column, so it already serves "the headings on this
    # book", and a second B-tree would be written on every insert for nothing.
    # The same reasoning `d3f6b81c9a27` applied to `ix_quotes_book_page`.
    op.create_index(
        "uq_classifications_book_scheme_number",
        "classifications",
        ["book_id", "scheme", "number"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index(
        "uq_classifications_book_scheme_number", table_name="classifications"
    )
    op.drop_index("ix_classifications_id", table_name="classifications")
    op.drop_table("classifications")
