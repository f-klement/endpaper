"""A note carries its own visibility.

Revision ID: a3d7f1b09c25
Revises: d9c1f47b2a06

One boolean on `notes`. A note has always been per member as **authorship**,
and `get_notes` filtered on the book alone, so every member of the library read
every note on any book they could see. That was the intended rule for a note
somebody typed into a shared library, and the wrong one for a review an import
carried: `private notes` is one of the header names the CSV reader maps to a
review, so a column another app called private arrived here under the member's
own name for everyone to read. Owner's decision, 2026-09-06.

**Existing rows are `False`, and that is the whole of the backfill.** Every
note in an existing database was written through the API into a shared library
and has been readable by the other members since it was saved; leaving it
readable is what keeps its meaning unchanged. `False` is also the safe
direction for the column's other half: nothing that predates this migration
disappears from anybody's screen by running it.

**Reviews an earlier import wrote are not retro-privatised, and this migration
could not do it honestly.** Nothing on the row records that a note came from an
import, so the only available rule would be a guess at content or a timestamp
window, and a note other members have already read going invisible is a content
removal nobody asked for. Each stays where its author can see it, in the
listing with the rest, and each is theirs to delete.

`render_as_batch=True` is on in `env.py`, so the ALTERs SQLite cannot do are
rewritten as a table copy. Adding a column needs no rewrite; the batch context
is used anyway so the downgrade, which drops one, works on SQLite too.

**The downgrade loses the distinction, not the notes.** Dropping the column
makes every private note readable again by whoever can see its book. That is
the honest consequence of going back to a schema with nowhere to record it, and
it is stated rather than worked around: there is no second place the flag
lives.

No index. This predicate only ever rides behind `book_id`, which is indexed,
and one book carries a handful of notes.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "a3d7f1b09c25"
down_revision: str | Sequence[str] | None = "d9c1f47b2a06"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("notes") as batch_op:
        batch_op.add_column(
            sa.Column(
                "is_private",
                sa.Boolean(),
                nullable=False,
                server_default="0",
            )
        )


def downgrade() -> None:
    with op.batch_alter_table("notes") as batch_op:
        batch_op.drop_column("is_private")
