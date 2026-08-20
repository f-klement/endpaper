"""Appearance per account.

Revision ID: c4d8e91a2f60
Revises: b8e2f04c17aa

The palette, light or dark, and the wallpaper used to live in `localStorage`,
which makes them per device rather than per person: the same member got a
different library on their phone, and two members sharing a laptop overwrote
each other's choice.

Three nullable columns on `users`, not a `user_preferences` table. It is a
one-to-one with no history and no lifecycle: a side table would add a join to
every read and a row that both shadow-account paths in `auth_backends.py` would
have to remember to create. NULL is the answer for "has not chosen", which is
what every account starts as and what the directory modes get for free.

`render_as_batch=True` is on in `env.py`, so the ALTERs SQLite cannot do are
rewritten as a table copy. Adding a nullable column needs no rewrite, but the
batch context is used anyway so the downgrade, which drops columns, works on
SQLite too.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "c4d8e91a2f60"
down_revision: str | None = "b8e2f04c17aa"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None

_COLUMNS = (
    ("appearance_palette", 30),
    ("appearance_mode", 10),
    ("appearance_wallpaper", 30),
)


def upgrade() -> None:
    with op.batch_alter_table("users") as batch_op:
        for name, length in _COLUMNS:
            batch_op.add_column(sa.Column(name, sa.String(length=length), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("users") as batch_op:
        for name, _ in _COLUMNS:
            batch_op.drop_column(name)
