"""A custom field records who defined it.

Revision ID: c7b41e92f80a
Revises: b8f4c1a7e309
Create Date: 2026-10-01

**`custom_fields` had no member axis at all**, and two separate problems come
out of that one absence.

A Member can be locked out of a field they defined. `fields.Fields` tells a
Member a definition exists when a Book they can see carries a value in it, when
a Book in their trash does, or when no Book at all does. A field whose only
value sits on somebody else's Private Book satisfies none of those, so it
vanishes from the definer's own settings page, and retyping the name is a loop
rather than a recovery: `custom_fields.define` hands back the existing row and
writes nothing, so the field is still carried and still hidden.

And any Member can relabel the whole Library's vocabulary. The rename takes any
member where the delete takes an admin, and the row recorded nobody, so the one
verb that renames content other people typed left no owner to ask.

**Nullable, and every existing row gets null.** Null means "no author to ask",
which is the state the whole table was in before this revision, and the rule
for such a row is the rule the table already had: any Member may rename it. The
alternative, backfilling an admin or refusing a rename on a null, takes a
working verb away from the library on the morning of the upgrade and would do
the same to any archive taken before today.

**Raw SQL for the column, which is `a7c41d9e6b28`'s precedent and its reason.**
SQLite adds a column with a `REFERENCES` clause in place whenever the new
column's default is NULL, which this one's is. Alembic will not emit it:
`add_column` carrying a `ForeignKey` routes through `add_constraint`, which the
SQLite dialect refuses, and inside a batch context the constraint is unnamed
and refused for that instead. Naming it to get past the second refusal turns
this into a full copy of `custom_fields`, and that table is the parent of
`custom_field_values`, so the copy is the one operation worth avoiding here.
PostgreSQL accepts the same statement.

**The downgrade does need the batch context**, because dropping a column is the
operation SQLite cannot do in place. It drops the column and nothing else: no
value moves, and a field that was renamable before this revision is renamable
after the downgrade for the reason null gives above.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "c7b41e92f80a"
down_revision: str | None = "b8f4c1a7e309"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE custom_fields ADD COLUMN created_by_user_id "
        "INTEGER REFERENCES users (id)"
    )


def downgrade() -> None:
    with op.batch_alter_table("custom_fields") as batch_op:
        batch_op.drop_column("created_by_user_id")
