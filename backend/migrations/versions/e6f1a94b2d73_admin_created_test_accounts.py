"""Admin-created test accounts.

Revision ID: e6f1a94b2d73
Revises: c4d8e91a2f60

One boolean on `users`, and it is the whole feature: an admin can create a
local account with a password to see the library as an ordinary member sees it,
and can exchange that password for a session on it.

The column exists rather than the check being "auth_source is local" because
the two are not the same account. A local account from before a deployment
moved to a directory is also local, belongs to a real person, and must be
neither a switch target nor a row a directory identity is refused adoption of.

Existing rows are `False`, which is the safe direction: nothing that predates
this migration becomes switchable by running it.

`render_as_batch=True` is on in `env.py`, so the ALTERs SQLite cannot do are
rewritten as a table copy. Adding a column needs no rewrite; the batch context
is used anyway so the downgrade, which drops one, works on SQLite too.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "e6f1a94b2d73"
down_revision: str | None = "c4d8e91a2f60"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("users") as batch_op:
        batch_op.add_column(
            sa.Column(
                "is_test_account",
                sa.Boolean(),
                nullable=False,
                server_default="0",
            )
        )


def downgrade() -> None:
    with op.batch_alter_table("users") as batch_op:
        batch_op.drop_column("is_test_account")
