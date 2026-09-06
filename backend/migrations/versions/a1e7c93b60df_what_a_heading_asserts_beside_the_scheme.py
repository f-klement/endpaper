"""A heading records what it was asserting, beside the scheme it is in.

Revision ID: a1e7c93b60df
Revises: d2b9f0c74a13
Create Date: 2026-09-06

The DNB writes a content type and a carrier type into the same subject fields as
a subject heading, with a `(DE-588)` number on each, so `CD-ROM` and
`Hochschulschrift` were stored as assertions about what a book is about.
`classifications.kind` is what separates them, read from the record's `$2`.

**A column rather than two more `ClassificationScheme` members**, which was the
other candidate and is refused at `enums.ClassificationScheme`: those codes name
the same file and give the number the same reading, and moving a row into a new
scheme would change the key `uq_classifications_book_scheme_number` is on.

**Constrained, where `scheme` beside it is not**, and the split is the one
`tests/test_house_rules.py` holds: a CHECK costs a batch rebuild every time the
enum grows, and `HeadingKind` does not grow when a catalogue is added.
`b8e2f4c7a913` records what the constraint is worth: `backup.restore` inserts
through Core, so without one an archive decides the value and a single
unrecognised row 500s the member listing, the facet endpoint and the
unauthenticated public catalogue for good. `subject` is not permitted either,
because that state is the null.

## Nothing is backfilled, and that is measured rather than conceded

A row already stored does not record the `$2` it came from, so the only
correction available is an `UPDATE` keyed on the GND numbers of the two
vocabularies. That works only if the vocabularies enumerate. Measured live
against the DNB on 2026-09-06, two independent samples:

* the 91 survey ISBNs the DNB answers, 99 records: 37 `gnd-content` fields
  carrying **17** distinct numbers, 1 `gnd-carrier` field carrying **1**.
* 25 broad title sweeps at 100 records each, 5,000 records: 207 `gnd-content`
  fields carrying **39** distinct numbers, 8 `gnd-carrier` fields carrying **2**.

The content curve is still climbing where the second sample stops, 33 distinct
at 4,100 records against 39 at 5,000, and the two samples' carrier sets are
**disjoint**: the first found only CD-ROM, the second only CD and Schallplatte,
so 0 of the 3 numbers seen appear in both. A list written into this file would
have been incomplete on the day it ran, would have corrected some rows and
missed others, and nothing would have gone red.

So the null this leaves means what it says: the record never told us. Correction
happens at the write site, where the record is in hand, and reaches a book when
that book is next enriched. `classifications.add_headings` fills the column in
on the same rule it fills in a missing caption.

The downgrade drops the column and loses every kind read since. That is stated
rather than hidden: there is no second copy of it anywhere, because the `$2` it
came from is not stored either.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "a1e7c93b60df"
down_revision: str | Sequence[str] | None = "d2b9f0c74a13"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

#: The width `models.Classification.kind` declares. The longest member of
#: `enums.HeadingKind` on this date is `subject`, at 7, and the column is sized
#: like `scheme` beside it rather than to today's longest word.
_KIND_WIDTH = 20


def upgrade() -> None:
    op.add_column(
        "classifications",
        sa.Column("kind", sa.String(length=_KIND_WIDTH), nullable=True),
    )
    # SQLite cannot ALTER in a CHECK, so this rebuilds the table.
    # `render_as_batch=True` in `migrations/env.py` is what makes it do so, and
    # the rebuild carries `uq_classifications_book_scheme_number` with it: that
    # index is what stops enrichment depositing a second copy of every heading,
    # and `b7d41f0a2c95` already lost a wave to proving a batch rewrite keeps
    # it.
    #
    # Nothing has to precede this DDL. On SQLite a failed revision does not
    # reliably roll back, so a revision that **refuses** has to run its check
    # before its first DDL statement; this one refuses nothing and backfills
    # nothing, and every existing row is null, which the constraint permits.
    with op.batch_alter_table("classifications") as batch:
        batch.create_check_constraint(
            "ck_classifications_kind",
            sa.text("kind IS NULL OR kind IN ('content', 'carrier')"),
        )


def downgrade() -> None:
    with op.batch_alter_table("classifications") as batch:
        batch.drop_constraint("ck_classifications_kind", type_="check")
        batch.drop_column("kind")
