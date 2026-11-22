"""A patron is a third kind of borrower

Revision ID: f009f139047c
Revises: c2015421927e
Create Date: 2026-11-20

`patrons` holds a registered borrower who is not a member, and `loans` gains
`loaned_to_patron_id` beside the member and the typed name, plus
`borrower_anonymised_at`, the marker `patrons.erase` leaves on a loan whose
patron asked to be forgotten. `ck_loans_one_borrower` becomes exactly one of
the three, or none beside the marker. `models.Patron` says what the record is
and what binds on it.

**Every existing loan names exactly one of a member and a typed name**, so it
satisfies the new constraint with both new columns null and no data step.

The open loan index is dropped first and recreated after, for the reason
`d5c31b7a09fe` gives: batch mode rebuilds the table by reflecting it, and a
partial index that came back plain would forbid lending a returned book again.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "f009f139047c"
down_revision: str | Sequence[str] | None = "c2015421927e"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_OPEN_LOAN_INDEX = "uq_loans_one_open_per_book"
_BORROWER_CHECK = "ck_loans_one_borrower"
_PATRON_FK = "fk_loans_loaned_to_patron_id"

# Copies, not imports of `models.ONE_BORROWER_SQL`, for the reason
# `d5c31b7a09fe` gives: a revision records what was applied on a day.
# `tests/test_models.py::TestTheBorrowerRuleHasOneSpelling` holds the constant
# to what a migrated database carries.
_THREE_KINDS = (
    "(CASE WHEN loaned_to_user_id IS NULL THEN 0 ELSE 1 END "
    "+ CASE WHEN loaned_to_patron_id IS NULL THEN 0 ELSE 1 END "
    "+ CASE WHEN loaned_to_name IS NULL THEN 0 ELSE 1 END) "
    "= (CASE WHEN borrower_anonymised_at IS NULL THEN 1 ELSE 0 END) "
    "AND (loaned_to_name IS NULL OR length(trim(loaned_to_name)) > 0)"
)
_TWO_KINDS = (
    "(loaned_to_user_id IS NULL) <> (loaned_to_name IS NULL) "
    "AND (loaned_to_name IS NULL OR length(trim(loaned_to_name)) > 0)"
)


def _drop_open_loan_index() -> None:
    op.drop_index(_OPEN_LOAN_INDEX, table_name="loans", if_exists=True)


def _create_open_loan_index() -> None:
    op.create_index(
        _OPEN_LOAN_INDEX,
        "loans",
        ["book_id"],
        unique=True,
        sqlite_where=sa.text("returned_at IS NULL"),
        postgresql_where=sa.text("returned_at IS NULL"),
        if_not_exists=True,
    )


def upgrade() -> None:
    op.create_table(
        "patrons",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("card_number", sa.String(length=32), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("email", sa.String(length=320), nullable=True),
        sa.Column("phone", sa.String(length=40), nullable=True),
        sa.Column("street", sa.String(length=120), nullable=True),
        sa.Column("house_number", sa.String(length=20), nullable=True),
        sa.Column("postcode", sa.String(length=20), nullable=True),
        sa.Column("city", sa.String(length=80), nullable=True),
        sa.Column("expires_on", sa.Date(), nullable=True),
        sa.Column("enrolled_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_patrons_id", "patrons", ["id"])
    op.create_index("ix_patrons_card_number", "patrons", ["card_number"], unique=True)

    _drop_open_loan_index()
    with op.batch_alter_table("loans") as batch:
        batch.add_column(sa.Column("loaned_to_patron_id", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("borrower_anonymised_at", sa.DateTime(), nullable=True))
        batch.create_foreign_key(_PATRON_FK, "patrons", ["loaned_to_patron_id"], ["id"])
        batch.drop_constraint(_BORROWER_CHECK, type_="check")
        batch.create_check_constraint(_BORROWER_CHECK, _THREE_KINDS)
    op.create_index("ix_loans_loaned_to_patron_id", "loans", ["loaned_to_patron_id"])
    _create_open_loan_index()


def downgrade() -> None:
    # A loan to a patron, or one whose borrower was erased, names nobody the
    # older schema can hold. Dropping those rows is the honest reversal, as in
    # `d5c31b7a09fe`: keeping them would need an invented borrower.
    op.execute(
        sa.text(
            "DELETE FROM loans WHERE loaned_to_patron_id IS NOT NULL OR borrower_anonymised_at IS NOT NULL"
        )
    )
    op.drop_index("ix_loans_loaned_to_patron_id", table_name="loans")
    _drop_open_loan_index()
    with op.batch_alter_table("loans") as batch:
        batch.drop_constraint(_BORROWER_CHECK, type_="check")
        batch.drop_constraint(_PATRON_FK, type_="foreignkey")
        batch.drop_column("borrower_anonymised_at")
        batch.drop_column("loaned_to_patron_id")
        batch.create_check_constraint(_BORROWER_CHECK, _TWO_KINDS)
    _create_open_loan_index()

    op.drop_index("ix_patrons_card_number", table_name="patrons")
    op.drop_index("ix_patrons_id", table_name="patrons")
    op.drop_table("patrons")
