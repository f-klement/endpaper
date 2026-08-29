"""Widen ck_author_identifiers_scheme for the six national authority files.

Revision ID: c9a5f27b3e41
Revises: d5e1b93a7c62
Create Date: 2026-08-28

`d5e1b93a7c62` widened the list to the four cross references a GND record
carries in `sameAs`. **`sameAs` does not carry a national library's number**,
and a VIAF cluster does: measured 2026-08-28 over six Romance and Latin American
authors, the cluster named by the confirmed GND record's own `sameAs` returned
BLBNB, ARBABN, BNE, PTBNP, ICCU and BNCHL identifiers, and its `DNB` source
carried back the same GND number in all six. Storing those is what needs this
list widened.

**Six in one revision rather than six revisions**, because two migrations cannot
be written concurrently: both take the current head as `down_revision`, Alembic
then has two heads, and untangling it is a merge revision. Six would serialise
six pieces of work behind each other for nothing.

**Storing is not resolving, and the distinction is why these are worth a
migration now.** None of the six is a lookup source: `acervo.bn.gov.br` answers
403 to every agent tried and has no open Z39.50 port, and the rest wait on a
Z39.50 transport this app does not have. The identifier arrives free from a VIAF
cluster today, which is what makes a national adapter cheap on the day its
transport lands.

**No backfill.** Nothing could have written a row under any of the six before
this revision, so there is nothing to migrate; the rows appear the first time a
Member confirms a GND candidate after it.

Downgrade narrows the list back to the five `d5e1b93a7c62` left and **deletes
every row under one of the six first**, for the reason that revision gives:
narrowing a CHECK with rows that violate it fails on a real database and is
accepted on SQLite, and a row the schema says cannot exist is worse than a row
that is gone.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "c9a5f27b3e41"
down_revision: str | Sequence[str] | None = "d5e1b93a7c62"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

#: Written out rather than imported from `models` or `enums`, for the reason
#: `a4c73e0b19d5` gives: a migration describes the schema at one point in time
#: and must not change meaning when a constant is later retuned. Widening the
#: enum again is another revision, and
#: `tests/test_schema.py::TestTheAuthorityIdentifierConstraintsOnAMigratedDatabase
#: ::test_every_scheme_the_enum_offers_is_storable` is what makes forgetting it a
#: failure rather than a runtime `IntegrityError`.
_SCHEMES_BEFORE = "scheme IN ('gnd', 'isni', 'lcnaf', 'viaf', 'wikidata')"
_SCHEMES_AFTER = (
    "scheme IN ('gnd', 'isni', 'lcnaf', 'viaf', 'wikidata', "
    "'blbnb', 'arbabn', 'bne', 'ptbnp', 'iccu', 'bnchl')"
)

_CONSTRAINT = "ck_author_identifiers_scheme"

#: The six this revision adds, for the downgrade to clear. Spelled out rather
#: than derived from the two lists above, so the delete cannot widen by itself
#: if a later revision edits `_SCHEMES_AFTER` in place.
_ADDED = ("blbnb", "arbabn", "bne", "ptbnp", "iccu", "bnchl")

#: The `IN` list the downgrade clears, built from `_ADDED` so the six are
#: written once. A literal rather than a bound parameter, for the reason
#: `_SCHEMES_AFTER` is one: a revision says what it did on the day it ran, and
#: these are six constants this file owns rather than anything a caller supplies.
_ADDED_LIST = ", ".join(f"'{scheme}'" for scheme in _ADDED)


def _swap(wanted: str) -> None:
    with op.batch_alter_table("author_identifiers") as batch:
        batch.drop_constraint(_CONSTRAINT, type_="check")
        batch.create_check_constraint(_CONSTRAINT, wanted)


def upgrade() -> None:
    _swap(_SCHEMES_AFTER)


def downgrade() -> None:
    op.execute(
        sa.text(f"DELETE FROM author_identifiers WHERE scheme IN ({_ADDED_LIST})")
    )
    _swap(_SCHEMES_BEFORE)
