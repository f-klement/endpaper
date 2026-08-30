"""Widen classifications.number for LCSH.

Revision ID: b7d41f0a2c95
Revises: e2c74a91b5d8
Create Date: 2026-08-24

**A subject heading is not a notation, and the column was sized for a
notation.** `e2c74a91b5d8` set `number` to 40 characters, which is comfortably
above the longest Dewey number, LCC call number or GND authority number this
app has seen. LCSH is the fourth scheme and it has no identifier at all: MODS
from the Library of Congress carries no `valueURI` on a single `<subject>`
element across 900 live records (measured 2026-08-24), so the authorised
heading string is the access point and it goes in `number`.

**Measured before it was written**, over the 1,559 LCSH headings in those 900
records:

| Bound | Headings it refuses |
|---|---|
| 40 | 399, 25.6% |
| 50 | 190, 12.2% |
| 60 | 91, 5.8% |
| 80 | 5, 0.3% |
| 100 | 0 |
| 120 | 0 |

Median 29, p99 75, longest **in that sample** 91, and a second sample of 505
headings reached 92, which is the point: the tail is sample bound, so the
headroom above the observed maximum is what 120 buys rather than the exact
figure. Longest seen: `University of Nebraska (Lincoln campus).
University Galleries -- Exhibitions -- Periodicals`. 40 refuses exactly the
subdivided headings, which are the ones carrying the information, so this is a
widening rather than a preference.

`render_as_batch=True` is set in `env.py`, which is what lets SQLite alter a
column at all: it rebuilds the table. Nothing is lost either way, because every
stored value already fits in 40.

**No backfill and nothing to recover.** Before this revision an LCSH heading
could not be stored at all, and a heading longer than 40 characters was dropped
at parse time by `classifications.bounded_headings` rather than truncated, so no row
holds a clipped value.

Downgrade narrows the column back to 40. Any stored value longer than that is
deleted first, because narrowing a column with over-long rows fails on a real
database and silently keeps them on SQLite, and a row the schema says cannot
exist is worse than a row that is gone.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "b7d41f0a2c95"
down_revision: str | Sequence[str] | None = "e2c74a91b5d8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

#: Written out rather than imported from `models`, for the reason
#: `e2c74a91b5d8` gives: a migration describes the schema at one point in time
#: and must not change meaning when a constant is later retuned.
_NUMBER_MAX = 120
_NUMBER_MAX_BEFORE = 40


def upgrade() -> None:
    with op.batch_alter_table("classifications") as batch:
        batch.alter_column(
            "number",
            existing_type=sa.String(length=_NUMBER_MAX_BEFORE),
            type_=sa.String(length=_NUMBER_MAX),
            existing_nullable=False,
        )


def downgrade() -> None:
    op.execute(
        sa.text(
            "DELETE FROM classifications WHERE length(number) > :bound"
        ).bindparams(bound=_NUMBER_MAX_BEFORE)
    )
    with op.batch_alter_table("classifications") as batch:
        batch.alter_column(
            "number",
            existing_type=sa.String(length=_NUMBER_MAX),
            type_=sa.String(length=_NUMBER_MAX_BEFORE),
            existing_nullable=False,
        )
