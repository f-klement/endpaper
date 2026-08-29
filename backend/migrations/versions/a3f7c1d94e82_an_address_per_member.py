"""An address per member.

Revision ID: a3f7c1d94e82
Revises: c9a5f27b3e41

`users.email`, nullable, so a reminder can be addressed to the borrower rather
than to the household mailbox. Nothing sends to it yet: the mail sender still
posts one digest to `overdue_mail_to`, and NULL means exactly that, so a library
upgrading past this revision sees no behaviour change.

Nullable rather than defaulted, because there is no address that would be right
for an existing row. NULL is "nobody has said", which is what every row here is
and what a directory shadow account starts as, the same shape the three
`appearance_*` columns took in `c4d8e91a2f60`.

One column rather than a column plus a provenance flag. Who owns the value is a
property of the deployment's configuration rather than of the row: with
`LDAP_EMAIL_ATTRIBUTE` or `PROXY_EMAIL_HEADER` set, the directory writes it on
every sign in and nobody else may; unset, it is the member's own, and an admin
may write it for anybody. `auth_backends.directory_owns_email` is the one
place that is decided, so a second column would be a cached copy of a config
lookup that three call sites already share.

`render_as_batch=True` is on in `env.py`, so the ALTERs SQLite cannot do are
rewritten as a table copy. Adding a nullable column needs no rewrite; the batch
context is used anyway so the downgrade, which drops the column, works on
SQLite too.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "a3f7c1d94e82"
down_revision: str | None = "c9a5f27b3e41"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None

#: The RFC 5321 maximum for a path, and the bound
#: `schemas.settings.MAX_MAIL_ADDRESS` already puts on the household address.
_MAX_ADDRESS = 320


def upgrade() -> None:
    with op.batch_alter_table("users") as batch_op:
        batch_op.add_column(sa.Column("email", sa.String(length=_MAX_ADDRESS), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("users") as batch_op:
        batch_op.drop_column("email")
