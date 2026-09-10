"""Where a book file is said to be, and who said so.

Revision ID: b2e94f7c1a03
Revises: a3d7f1b09c25
Create Date: 2026-09-10

One table hanging off a book, holding a Member's account of where one of their
book files lives. **No bytes reach this server**, so nothing here was read or
checked, and the table is shaped so that the columns say which half is a claim
and which half is this server's own clock.

**A table rather than columns on `books`.** MARC 856 is repeatable and Koha's
`biblioitems.url` is one column, which is the prior art for the repeat having
nowhere to go. The case that turns a column into a table is the same book at two
paths on two machines, so it is a table now instead of a migration later.

**The CHECK is what enforces the widths, not the `String(n)`.** SQLite ignores
VARCHAR width, so a Core insert of a megabyte into a `String(4094)` stores a
megabyte; `backup.restore` is that path and it sees no Pydantic model.
`ck_digital_references_bounds` is therefore the rule, exactly as
`ck_quotes_text_bounds` is.

**And it carries a byte arm as well as a character one.** SQLite's `length()`
counts characters up to the first NUL, so on a Core insert the character
inequality alone passes on a value nothing bounded: measured, `"a\x00" + "x" *
10000` reports a length of 1 and stores 10,002 bytes. Four bytes is UTF-8's
widest character, so the byte arm never refuses what the character arm admits.

**The unique index is the identity.** A reference is identified by where the
file is, not by a row id, which is what makes re-importing a folder somebody
imported last month refresh the rows instead of doubling them.

No backfill, and nothing could be invented: no existing row records a file. A
book catalogued from an EPUB before this migration knows its format and nothing
else, which is the state it was written in.

Downgrade drops the table and every reference with it. Nothing else can happen:
the table is the only place they live. The same shape as `d3f6b81c9a27`'s.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "b2e94f7c1a03"
down_revision: str | Sequence[str] | None = "a3d7f1b09c25"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

#: Kept in step with `models.DIGITAL_REFERENCE_PATH_MAX`, and written out here
#: rather than imported: a migration describes the schema at one point in time
#: and must not change meaning when a constant is later retuned. Derived there
#: from `getconf PATH_MAX /` (4096, including the NUL) less one separator.
#:
#: **"Kept in step with" is a promise, so a test keeps it**: production builds
#: its schema from this file and every test builds one from `models.py`, which
#: is a fact stored twice with nothing between the copies.
#: `tests/test_schema.py::TestTheMigratedDatabaseCarriesTheBoundsItPromises`
#: reads both.
_PATH_MAX = 4094

#: Kept in step with `models.DIGITAL_REFERENCE_MAX_SIZE`, and written out for the
#: same reason. `Number.MAX_SAFE_INTEGER`: the producer is a browser, and a
#: larger size did not survive the JSON that carried it.
_MAX_SIZE = 9007199254740991


def upgrade() -> None:
    op.create_table(
        "digital_references",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("book_id", sa.Integer(), nullable=False),
        sa.Column("root_label", sa.String(length=_PATH_MAX), nullable=False),
        sa.Column("relative_path", sa.String(length=_PATH_MAX), nullable=False),
        sa.Column(
            "root_confirmed", sa.Boolean(), server_default="0", nullable=False
        ),
        sa.Column("size_bytes", sa.Integer(), nullable=True),
        sa.Column("file_modified_at", sa.DateTime(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "confirmed_at", sa.DateTime(), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("missing_since", sa.DateTime(), nullable=True),
        sa.CheckConstraint(
            "length(root_label) >= 1 "
            "AND length(relative_path) >= 1 "
            f"AND length(root_label) + length(relative_path) <= {_PATH_MAX} "
            "AND length(CAST(root_label AS BLOB)) + length(CAST(relative_path AS BLOB)) "
            f"<= {4 * _PATH_MAX} "
            "AND (size_bytes IS NULL OR (size_bytes >= 0 "
            f"AND size_bytes <= {_MAX_SIZE}))",
            name="ck_digital_references_bounds",
        ),
        sa.ForeignKeyConstraint(["book_id"], ["books.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_digital_references_id"), "digital_references", ["id"])
    # Unique on where the file is, not on a row id. `book_id` gets no index of
    # its own: this one leads with it.
    op.create_index(
        "uq_digital_references_location",
        "digital_references",
        ["book_id", "root_label", "relative_path"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("uq_digital_references_location", table_name="digital_references")
    op.drop_index(op.f("ix_digital_references_id"), table_name="digital_references")
    op.drop_table("digital_references")
