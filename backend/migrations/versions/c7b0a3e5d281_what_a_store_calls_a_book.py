"""What a store calls a book, where that is not an ISBN.

Revision ID: c7b0a3e5d281
Revises: f4a1c62d0b97
Create Date: 2026-09-11

One table hanging off a book, holding the number a store gives an edition: an
ASIN off a Kindle for PC catalogue, a Google Books volume id off a Play Books
Takeout. Both were read in the browser and neither was kept, because `BookCreate`
had one identifier field and it was `isbn`.

**Not a wider `isbn`, and that is the decision this revision records.** That
column is the importer's match key and every path into it check digits its
input. An ASIN is ten characters beginning `B` and passes no such test, so a row
carrying one in that column matches nothing and takes the dedupe surface down
with it for the rows that do.

**A table rather than a column per scheme.** `POST /api/books/merge` folds up to
20 rows into one and moves their children across, so one book really can carry
an ASIN and a volume id at once: two rows for one book are commonly two imports
of two stores. A nullable column would have cost nothing today and a migration
per store afterwards, and four stores are wired. The same trade `b2e94f7c1a03`
made for the file references.

**The unique key carries the value, and `author_identifiers`' does not.** There
a second differing assertion about one name is a conflict somebody has to look
at, so the index refuses it. Here it is what a merge produces, and an index that
refuses it turns a merge into an `IntegrityError` rather than into a fact worth
keeping: two ASINs on one book say two Kindle entries were declared the same
book.

**The CHECK is what enforces the width, not the `String(n)`.** SQLite ignores
VARCHAR width, so a Core insert of a megabyte into a `String(60)` stores a
megabyte, and `backup.restore` is that path: it sees no Pydantic model.

**And it refuses a NUL rather than carrying a byte budget.** SQLite's `length()`
counts characters up to the first NUL, so on a Core insert the character
inequality alone passes on a value nothing bounded. `b2e94f7c1a03` closed that
with a budget at four times the ceiling, which caps such a value rather than
refusing it, because the column there holds a member's own text. Every value
here is a token a machine wrote, so a NUL is never legitimate and the tighter
arm is available: with it the character ceiling is exact. The two credential
columns already carry this arm.

No backfill, and nothing could be invented: no existing row records a store's
number. A book imported from a Kindle library before this migration kept its
title, its authors, its publisher and its year, which is the state it was
written in.

Downgrade drops the table and every identifier with it. Nothing else can happen:
the table is the only place they live. The same shape as `b2e94f7c1a03`'s.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "c7b0a3e5d281"
down_revision: str | Sequence[str] | None = "f4a1c62d0b97"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

#: Kept in step with `models.BOOK_IDENTIFIER_MAX`, and written out here rather
#: than imported: a migration describes the schema at one point in time and must
#: not change meaning when a constant is later retuned.
#:
#: **"Kept in step with" is a promise, so a test keeps it**: production builds
#: its schema from this file and every test builds one from `models.py`, which
#: is a fact stored twice with nothing between the copies.
#: `tests/test_schema.py::TestTheIdentifierBoundsSurvivedIntoTheMigration` reads
#: both.
_VALUE_MAX = 60

#: The scheme list as it stood on the day this ran, spelled out rather than
#: derived. `models.py` builds the same constraint from `enums.BookIdentifier
#: Scheme` through `_scheme_check`, which is what stops the two separating: a
#: member added there with no migration is a value the application accepts and
#: the database rejects, and `tests/test_schema.py` asks the **migrated**
#: database whether each member is storable, which a model built one cannot.
_SCHEMES = ("asin", "google_books")


def upgrade() -> None:
    schemes = ", ".join(f"'{scheme}'" for scheme in _SCHEMES)
    op.create_table(
        "book_identifiers",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("book_id", sa.Integer(), nullable=False),
        sa.Column("scheme", sa.String(length=20), nullable=False),
        sa.Column("value", sa.String(length=_VALUE_MAX), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            f"scheme IN ({schemes})",
            name="ck_book_identifiers_scheme",
        ),
        sa.CheckConstraint(
            f"length(value) > 0 AND length(value) <= {_VALUE_MAX}"
            " AND instr(value, char(0)) = 0",
            name="ck_book_identifiers_bounds",
        ),
        sa.ForeignKeyConstraint(["book_id"], ["books.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_book_identifiers_id"), "book_identifiers", ["id"])
    # Unique on the assertion, not on a row id, so re-importing a library
    # somebody imported last month finds the row instead of doubling it.
    # `book_id` gets no index of its own: this one leads with it.
    op.create_index(
        "uq_book_identifiers_book_scheme_value",
        "book_identifiers",
        ["book_id", "scheme", "value"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index(
        "uq_book_identifiers_book_scheme_value", table_name="book_identifiers"
    )
    op.drop_index(op.f("ix_book_identifiers_id"), table_name="book_identifiers")
    op.drop_table("book_identifiers")
