"""Account recovery, and confirming an address.

Revision ID: a7c41d9e6b28
Revises: f3a20d68c4b1

Two features and one revision, because they touch the same table and two
concurrent migrations both take the current head as `down_revision`, which
leaves Alembic with two heads and a merge revision to untangle.

**Six columns on `users`, added and never rewritten.** `render_as_batch=True` is
on in `env.py`, so this uses a batch context for the downgrade's sake; the
upgrade is `ALTER TABLE ADD COLUMN` throughout, which SQLite performs in place
even for the one that carries a `REFERENCES` clause, since its default is NULL.
**No check constraint is added to `users`**, deliberately: one would force a full
table copy of a table that from this revision on carries a self referential
foreign key, and the rule it would express (an admin assertion names the admin,
every other names nobody) is written by one function and pinned by a test
instead.

**Every account that already exists is backfilled as confirmed.** They were made
under a policy that asked nothing, so treating them as unconfirmed would mean an
upgrade plus one switch locks a household out of its own catalogue. The
provenance says exactly that: `not_required`, nobody was asked. The consequence,
stated rather than discovered, is that turning the policy on cannot retroactively
require confirmation of accounts already here; the admin override is how an admin
acts on one of those.

`CURRENT_TIMESTAMP` rather than a Python value, so the backfill is one statement
and the timestamps are the database's own, in the same naive UTC every other
`DateTime` column in this schema holds.

**One live request per account is a partial unique index**, not a plain one:
completed rows are the history a member reads back and there may be several per
account, so uniqueness has to be conditional on the row still being live.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "a7c41d9e6b28"
down_revision: str | None = "f3a20d68c4b1"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("users", sa.Column("email_verified_at", sa.DateTime(), nullable=True))
    op.add_column(
        "users",
        sa.Column("email_verification_source", sa.String(length=20), nullable=True),
    )
    # **Raw SQL for this one column, and the reason is a refusal rather than a
    # limitation.** SQLite performs `ALTER TABLE ... ADD COLUMN ... REFERENCES`
    # in place whenever the new column's default is NULL, which this one's is.
    # Alembic will not emit it: `add_column` with a `ForeignKey` routes through
    # `add_constraint`, which the SQLite dialect refuses outright, and inside a
    # batch context the same constraint is unnamed and refused for that instead.
    # Naming it to get past the second refusal turns the migration into a full
    # copy of `users`, which is the one operation this revision is written to
    # avoid: the table is referenced by nine others and this column makes it
    # self referential.
    op.execute(
        "ALTER TABLE users ADD COLUMN email_verified_by_user_id "
        "INTEGER REFERENCES users (id)"
    )
    op.add_column(
        "users", sa.Column("verification_code_hash", sa.String(length=255), nullable=True)
    )
    op.add_column(
        "users", sa.Column("verification_code_expires_at", sa.DateTime(), nullable=True)
    )
    op.add_column("users", sa.Column("sessions_valid_from", sa.DateTime(), nullable=True))

    op.execute(
        "UPDATE users SET email_verified_at = CURRENT_TIMESTAMP, "
        "email_verification_source = 'not_required'"
    )

    op.create_table(
        "password_reset_requests",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column(
            "requested_at",
            sa.DateTime(),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            # Not null, because `Mapped[datetime]` on the model is not, and
            # `tests/test_schema.py::TestTheMigrationsAndTheModelsAgree` compares
            # the migrated database against the model column by column.
            nullable=False,
        ),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("code_hash", sa.String(length=255), nullable=True),
        sa.Column("code_expires_at", sa.DateTime(), nullable=True),
        sa.Column("approved_by_user_id", sa.Integer(), nullable=True),
        sa.Column("approved_at", sa.DateTime(), nullable=True),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["approved_by_user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint(
            "(code_expires_at IS NULL AND approved_by_user_id IS NULL "
            "AND approved_at IS NULL) "
            "OR (code_expires_at IS NOT NULL AND approved_by_user_id IS NOT NULL "
            "AND approved_at IS NOT NULL)",
            name="ck_password_reset_requests_approval",
        ),
        sa.CheckConstraint(
            "code_hash IS NULL OR approved_at IS NOT NULL",
            name="ck_password_reset_requests_code",
        ),
        sa.CheckConstraint(
            "completed_at IS NULL OR approved_at IS NOT NULL",
            name="ck_password_reset_requests_completion",
        ),
    )
    op.create_index(
        op.f("ix_password_reset_requests_id"),
        "password_reset_requests",
        ["id"],
        unique=False,
    )
    op.create_index(
        "uq_password_reset_requests_live",
        "password_reset_requests",
        ["user_id"],
        unique=True,
        sqlite_where=sa.text("completed_at IS NULL"),
        postgresql_where=sa.text("completed_at IS NULL"),
    )


def downgrade() -> None:
    op.drop_index("uq_password_reset_requests_live", table_name="password_reset_requests")
    op.drop_index(
        op.f("ix_password_reset_requests_id"), table_name="password_reset_requests"
    )
    op.drop_table("password_reset_requests")
    with op.batch_alter_table("users") as batch_op:
        batch_op.drop_column("sessions_valid_from")
        batch_op.drop_column("verification_code_expires_at")
        batch_op.drop_column("verification_code_hash")
        batch_op.drop_column("email_verified_by_user_id")
        batch_op.drop_column("email_verification_source")
        batch_op.drop_column("email_verified_at")
