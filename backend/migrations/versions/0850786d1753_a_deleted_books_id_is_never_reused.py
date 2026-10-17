"""A deleted Book's id is never given to another Book.

Revision ID: 0850786d1753
Revises: e6c2a9d41f73
Create Date: 2026-10-17

Without `AUTOINCREMENT` SQLite gives an insert `max(rowid) + 1`, so deleting the
highest id Book hands its id to the next Book created. An import that matched
the deleted Book by id then wrote its status and gap fill onto the new one and
answered 200. Postgres takes ids from a sequence that a delete never moves back,
so this changes nothing there.

**A batch rebuild, because SQLite cannot add `AUTOINCREMENT` to a table that
exists.** Batch mode reflects the table and keeps its CHECK and its indexes, the
partial ISBN index included, which `c2f95a80d417` measured for the same rebuild
of `books`. The rebuild copies every id, and the copy's own inserts set the
table's counter in `sqlite_sequence` to the highest one. **An id deleted before
this revision ran and above every surviving id can still be handed out once**:
no row records it.

The foreign keys are off on a migration connection (`env.py` builds its own
engine, and the `ON` listener lives on `database.engine`), so dropping the old
table cascades to no child row.

Downgrade rebuilds without it, which only lets SQLite reuse ids again.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0850786d1753"
down_revision: str | Sequence[str] | None = "e6c2a9d41f73"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _rebuild(*, autoincrement: bool) -> None:
    # `recreate="always"` rebuilds on every engine, Postgres included, where
    # dropping `books` would fail on the tables that reference it.
    if op.get_bind().dialect.name != "sqlite":
        return
    with op.batch_alter_table(
        "books", recreate="always", table_kwargs={"sqlite_autoincrement": autoincrement}
    ):
        pass


def upgrade() -> None:
    _rebuild(autoincrement=True)


def downgrade() -> None:
    _rebuild(autoincrement=False)
