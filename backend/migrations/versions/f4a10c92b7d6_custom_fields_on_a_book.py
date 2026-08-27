"""Custom fields on a book.

Revision ID: f4a10c92b7d6
Revises: e7b3d02a5c94
Create Date: 2026-08-27

A household keeps facts about a book that this schema should not know about.
The first concrete one, and the reason the feature exists: a link to the book
in a calibre-web instance. Two tables, a library wide definition and a per book
value.

**Two tables rather than a JSON column on `books`.** A JSON blob cannot be
indexed, counted or renamed without rewriting every row that mentions the old
name, and the rename has to preserve every value under it. Here a rename is one
UPDATE of one row and no value moves at all, because a value references the
definition by id and never carries its name.

**`uq_custom_field_values_book_field` is the shape of the feature**, not an
optimisation. One value per field per book is what makes "the value" a
well-defined thing for every reader and every writer; without it a second row
renders twice and no writer knows which one it is updating.

**All three CHECKs repeat what the Pydantic models already validate**, for the
reason `d3f6b81c9a27` gives: a restore inserts through Core and never sees a
Pydantic model. Two of them are load bearing rather than belt and braces.

`length(value) > 0` is the first. Clearing a value
deletes the row, so "a book with no value shows nothing" is a property of the
schema rather than of a filter somebody has to remember; an empty string stored
here would be a field that renders as a blank line with no way to tell it from
a rendering bug.

`ck_custom_fields_kind` is the second, and it guards a **500 rather than a bad
row**. `kind` is a plain VARCHAR holding an enum, and `CustomFieldOut.kind` is
typed, so a single row carrying anything else makes Pydantic raise while
serialising the library wide definitions route: one restored row, and every
member's settings page answers 500 for good. `custom_fields._kind_of` degrades
an unrecognised kind to text at the per book read end, which is the half that
can degrade safely; this is the half that cannot, so it refuses the insert and
a corrupt archive fails loudly at the restore instead.

SQLite ignores a VARCHAR width, so the widths below document the columns and
these constraints enforce them. Measured on `quotes`, not assumed.

**No check runs before the DDL because there is nothing this upgrade can
refuse.** It creates two empty tables and reads nothing. That matters here:
pysqlite opens a transaction for DML only, so DDL run with none open is durable
immediately and a later failure cannot roll it back. Any future migration on
these tables that wants to refuse an upgrade has to decide before its first
`op.` call. `docs/decisions.md` records the rule.

`PRAGMA foreign_keys` is 0 on a migration connection, so the ON DELETE CASCADEs
below enforce nothing here. They are declared for the application connection,
which `database.py` turns the pragma on for, and the application deletes the
child rows by hand anyway (`custom_fields.remove`), for the reason `delete_tag`
does.

Downgrade drops both tables, which destroys every value. Nothing else can
happen: the tables are the only place they live. Honest rather than clever, and
the same shape as `d3f6b81c9a27`'s.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "f4a10c92b7d6"
down_revision: str | Sequence[str] | None = "e7b3d02a5c94"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

#: Kept in step with `models.CUSTOM_FIELD_NAME_MAX` and
#: `models.CUSTOM_FIELD_VALUE_MAX`, and written out here rather than imported: a
#: migration describes the schema at one point in time and must not change
#: meaning when a constant is later retuned.
_NAME_MAX = 60
_VALUE_MAX = 500


def upgrade() -> None:
    op.create_table(
        "custom_fields",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=_NAME_MAX), nullable=False),
        sa.Column("kind", sa.String(length=20), nullable=False),
        sa.CheckConstraint(
            f"length(name) > 0 AND length(name) <= {_NAME_MAX}",
            name="ck_custom_fields_name_bounds",
        ),
        # `kind` is a plain VARCHAR carrying an enum, so this is what makes it
        # closed. Written out rather than interpolated from `CustomFieldKind`,
        # for the reason the widths above are: a migration describes the schema
        # at one point in time and must not change meaning when the enum grows.
        # A third kind is a second migration.
        sa.CheckConstraint("kind IN ('text', 'url')", name="ck_custom_fields_kind"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name"),
    )
    op.create_index("ix_custom_fields_id", "custom_fields", ["id"])

    op.create_table(
        "custom_field_values",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("book_id", sa.Integer(), nullable=False),
        sa.Column("field_id", sa.Integer(), nullable=False),
        sa.Column("value", sa.String(length=_VALUE_MAX), nullable=False),
        sa.CheckConstraint(
            f"length(value) > 0 AND length(value) <= {_VALUE_MAX}",
            name="ck_custom_field_values_bounds",
        ),
        sa.ForeignKeyConstraint(["book_id"], ["books.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["field_id"], ["custom_fields.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_custom_field_values_id", "custom_field_values", ["id"])
    # The only lookup this table has is "the values on this book", and the only
    # other read is "the values under this definition", which runs once when an
    # admin deletes one. A composite leading with `book_id` serves the first and
    # is also the uniqueness rule, so there is **no** standalone index on either
    # column beside it: a second B-tree would be written on every insert for
    # nothing. The same reasoning `d3f6b81c9a27` applied to `quotes`.
    op.create_index(
        "uq_custom_field_values_book_field",
        "custom_field_values",
        ["book_id", "field_id"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("uq_custom_field_values_book_field", table_name="custom_field_values")
    op.drop_index("ix_custom_field_values_id", table_name="custom_field_values")
    op.drop_table("custom_field_values")
    op.drop_index("ix_custom_fields_id", table_name="custom_fields")
    op.drop_table("custom_fields")
