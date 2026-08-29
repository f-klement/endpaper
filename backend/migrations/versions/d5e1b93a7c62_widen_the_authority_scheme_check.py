"""Widen ck_author_identifiers_scheme for the cross reference schemes.

Revision ID: d5e1b93a7c62
Revises: a4c73e0b19d5
Create Date: 2026-08-28

`a4c73e0b19d5` wrote `scheme IN ('gnd')`, which was the honest state of the
supply: the DNB was the only source of a person's identifier and it writes GND.
Every GND record this app resolves already carries ISNI, LCNAF, VIAF and
Wikidata in `sameAs`, and all four were handed to the client and dropped.
Storing them is what needs this list widened.

**Measured before the enum was widened**, 2026-08-28, over fourteen GND records
spanning Spanish, Portuguese, Brazilian, Argentine, Uruguayan and Italian
authors: all fourteen carried all four. Nothing here is speculative headroom.

**This revision was written twice, and the first version is worth recording
because its reasoning was plausible and false.** It handed `batch_alter_table` a
whole `sa.Table` through `copy_from`, on the belief that SQLAlchemy does not
reflect SQLite CHECK constraints and that batch mode would therefore rebuild the
table without the other three. Both halves were measured on a database built
through `a4c73e0b19d5`, and both are wrong on SQLAlchemy 2.0.52 with Alembic
1.19.1: a bare `batch_alter_table` keeps all four CHECKs and both indexes.

The cost of getting it wrong was not theoretical. **`copy_from` replaces
reflection rather than supplementing it**, so the two `Index` objects that
version did not think to declare were silently dropped: the upgrade exited
clean and `SELECT name FROM sqlite_master WHERE type='index'` returned nothing.
`uq_author_identifiers_key_scheme` is what makes "an identifier cannot be
retyped" enforceable below the application, so a spelling would have been able to
hold two values under one scheme with nothing to raise.

So the general rule is the opposite of the one that version stated: **let batch
mode reflect, and reach for `copy_from` only when a measurement says reflection
is losing something.** `render_as_batch=True` in `env.py` is what makes any of
this work on SQLite, which cannot alter a constraint in place.

**No backfill.** Nothing could have written a row under any of the four new
schemes before this revision, so there is nothing to migrate; the rows appear
the first time a Member confirms a candidate after it.

Downgrade narrows the list back to `('gnd')` and **deletes every row under
another scheme first**. Narrowing a CHECK with rows that violate it fails on a
real database and is accepted on SQLite, and a row the schema says cannot exist
is worse than a row that is gone: the same call `b7d41f0a2c95` made for an
over-long classification number.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "d5e1b93a7c62"
down_revision: str | Sequence[str] | None = "a4c73e0b19d5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

#: Written out rather than imported from `models` or `enums`, for the reason
#: `a4c73e0b19d5` gives: a migration describes the schema at one point in time
#: and must not change meaning when a constant is later retuned. Widening the
#: enum again is another revision, and
#: `tests/test_schema.py::TestTheAuthorityIdentifierConstraintsOnAMigratedDatabase
#: ::test_every_scheme_the_enum_offers_is_storable` is what makes forgetting it a
#: failure rather than a runtime `IntegrityError`.
_SCHEMES_BEFORE = "scheme IN ('gnd')"
_SCHEMES_AFTER = "scheme IN ('gnd', 'isni', 'lcnaf', 'viaf', 'wikidata')"

_CONSTRAINT = "ck_author_identifiers_scheme"


def _swap(wanted: str) -> None:
    with op.batch_alter_table("author_identifiers") as batch:
        batch.drop_constraint(_CONSTRAINT, type_="check")
        batch.create_check_constraint(_CONSTRAINT, wanted)


def upgrade() -> None:
    _swap(_SCHEMES_AFTER)


def downgrade() -> None:
    op.execute(sa.text("DELETE FROM author_identifiers WHERE scheme <> 'gnd'"))
    _swap(_SCHEMES_BEFORE)
