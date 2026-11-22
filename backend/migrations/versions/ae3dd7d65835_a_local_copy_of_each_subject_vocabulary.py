"""A local copy of each subject vocabulary

Revision ID: ae3dd7d65835
Revises: 8cfb39d1d900
Create Date: 2026-11-20

Two tables. `vocabulary_labels` holds one row per label of one entry, the
preferred label and each alternate, under the entry's identifier and the load
it came from. `vocabulary_copies` holds one row per vocabulary that has
finished a load: which load is current, when it was fetched and the source's
own release date. `models.VocabularyCopy` and `models.VocabularyLabel` say why
a load sits beside the current one until it is swapped in.

No backfill: nothing held a vocabulary before this. Downgrade drops both
tables, and a copy is fetched again from its source.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from dialect import DialectSQL

revision: str = "ae3dd7d65835"
down_revision: str | Sequence[str] | None = "8cfb39d1d900"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

#: `models.CLASSIFICATION_SCHEME_CODE_MAX`, `VOCABULARY_LABEL_MAX` and
#: `VOCABULARY_IDENTIFIER_MAX` as they stood on the day this ran, written out
#: for the reason `e5b2c8f14a37` gives.
_SCHEME_MAX = 20
_LABEL_MAX = 200
_IDENTIFIER_MAX = 120


def upgrade() -> None:
    op.create_table(
        "vocabulary_copies",
        sa.Column("scheme", sa.String(length=_SCHEME_MAX), nullable=False),
        sa.Column("generation", sa.Integer(), nullable=False),
        sa.Column("entries", sa.Integer(), nullable=False),
        sa.Column("fetched_at", sa.DateTime(), nullable=False),
        sa.Column("released", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("scheme"),
    )
    op.create_table(
        "vocabulary_labels",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("scheme", sa.String(length=_SCHEME_MAX), nullable=False),
        sa.Column("generation", sa.Integer(), nullable=False),
        sa.Column("identifier", sa.String(length=_IDENTIFIER_MAX), nullable=False),
        sa.Column("label", sa.String(length=_LABEL_MAX), nullable=False),
        sa.Column("preferred", sa.Boolean(), nullable=False),
        sa.CheckConstraint(
            DialectSQL(
                sqlite=(
                    f"length(label) BETWEEN 1 AND {_LABEL_MAX} "
                    f"AND length(CAST(label AS BLOB)) <= {4 * _LABEL_MAX} "
                    f"AND length(identifier) BETWEEN 1 AND {_IDENTIFIER_MAX} "
                    f"AND length(CAST(identifier AS BLOB)) <= {4 * _IDENTIFIER_MAX}"
                ),
                postgresql=(
                    f"length(label) BETWEEN 1 AND {_LABEL_MAX} "
                    f"AND octet_length(label) <= {4 * _LABEL_MAX} "
                    f"AND length(identifier) BETWEEN 1 AND {_IDENTIFIER_MAX} "
                    f"AND octet_length(identifier) <= {4 * _IDENTIFIER_MAX}"
                ),
            ),
            name="ck_vocabulary_labels_bounds",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "uq_vocabulary_labels_entry_label",
        "vocabulary_labels",
        ["scheme", "generation", "identifier", "label"],
        unique=True,
    )
    op.create_index("ix_vocabulary_labels_label", "vocabulary_labels", ["scheme", "generation", "label"])


def downgrade() -> None:
    op.drop_index("ix_vocabulary_labels_label", table_name="vocabulary_labels")
    op.drop_index("uq_vocabulary_labels_entry_label", table_name="vocabulary_labels")
    op.drop_table("vocabulary_labels")
    op.drop_table("vocabulary_copies")
