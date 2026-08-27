"""Which record in an authority file an author spelling means.

Revision ID: a4c73e0b19d5
Revises: c1f8a7e3d240
Create Date: 2026-08-27

The DNB has been sending the author's GND number in MARC `100 $0` since the
MARC21 switch on 2026-08-24, `metadata._gnd_identifier` has been parsing it, and
it was thrown away for want of somewhere correct to put it.
`docs/decisions.md`, "The author's GND is read by nothing", said the two
candidate homes were a column on `author_aliases` or authors becoming rows. This
is the third answer, and it is neither.

**Its own table, keyed on the spelling.** An alias row is a decision somebody
made about two names and most spellings have none, so a column there would have
nowhere to put the ordinary case. A person row is the change §30g says to decide
before writing a migration, and it is not needed to store an identifier.

**Unique per key and scheme, which is where "cannot be retyped" is enforced.**
The application refuses a differing assertion rather than updating the row; this
index is what makes a writer that forgot to check raise instead of storing two
answers.

**Not unique on the identifier**, because two spellings sharing one GND number
is exactly the case a merge is made from.

**No backfill, and nothing is recoverable.** The identifier was dropped at parse
time before any row was written, so there is nothing in an existing database to
read it out of. A refresh or an enrichment against the book's own ISBN fills it
in.

Downgrade drops the table. Every identifier goes with it and there is nowhere
else they live, which is the same trade `e2c74a91b5d8` made for
`classifications`.

**No refusal check, so nothing here depends on `PRAGMA foreign_keys`.** That
pragma is 0 on a migration connection, and pysqlite opens a transaction for DML
only, so a check placed after any DDL would already be durable when it raised.
This revision runs DDL alone and takes no view of existing rows, so the ordering
trap has nothing to bite on.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "a4c73e0b19d5"
down_revision: str | Sequence[str] | None = "c1f8a7e3d240"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

#: Kept in step with `models.AUTHOR_KEY_MAX` and
#: `models.AUTHORITY_IDENTIFIER_MAX`, and written out rather than imported: a
#: migration describes the schema at one point in time and must not change
#: meaning when a constant is later retuned. The same rule `e2c74a91b5d8`
#: states for the classification bounds.
_KEY_MAX = 500
_IDENTIFIER_MAX = 60


def upgrade() -> None:
    op.create_table(
        "author_identifiers",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("author_key", sa.String(length=_KEY_MAX), nullable=False),
        sa.Column("scheme", sa.String(length=20), nullable=False),
        sa.Column("identifier", sa.String(length=_IDENTIFIER_MAX), nullable=False),
        sa.Column("provenance", sa.String(length=20), nullable=False),
        sa.Column("created_by_user_id", sa.Integer(), nullable=True),
        # `nullable=False`, matching `Mapped[datetime]` on the model and every
        # other `created_at` in the tree. **This was `nullable=True` and no test
        # could have caught it**: `conftest.py` builds the schema with
        # `create_all`, so the suite sees the model and only production sees the
        # migration. The two have to be read against each other by a person.
        sa.Column(
            "created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint("scheme IN ('gnd')", name="ck_author_identifiers_scheme"),
        sa.CheckConstraint(
            "provenance IN ('catalogue', 'member')",
            name="ck_author_identifiers_provenance",
        ),
        sa.CheckConstraint(
            "provenance <> 'catalogue' OR created_by_user_id IS NULL",
            name="ck_author_identifiers_asserter",
        ),
        sa.CheckConstraint(
            f"length(identifier) > 0 AND length(identifier) <= {_IDENTIFIER_MAX}",
            name="ck_author_identifiers_bounds",
        ),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_author_identifiers_id", "author_identifiers", ["id"])
    # No standalone index on `author_key` beside it: this composite leads with
    # that column, so it already serves every read this table has, and a second
    # B-tree would be written on every insert for nothing. The same reasoning
    # `e2c74a91b5d8` applied to `classifications.book_id`.
    op.create_index(
        "uq_author_identifiers_key_scheme",
        "author_identifiers",
        ["author_key", "scheme"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("uq_author_identifiers_key_scheme", table_name="author_identifiers")
    op.drop_index("ix_author_identifiers_id", table_name="author_identifiers")
    op.drop_table("author_identifiers")
