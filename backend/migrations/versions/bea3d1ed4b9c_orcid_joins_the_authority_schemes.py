"""Widen ck_author_identifiers_scheme for ORCID.

Revision ID: bea3d1ed4b9c
Revises: f4a9c2e17b30
Create Date: 2026-11-16

`c9a5f27b3e41` left eleven schemes. ORCID is the twelfth, and it arrives by two
routes: as the last file a name search asks, where the GND and the Library of
Congress hold nobody under the name, and free in a GND record's `sameAs`.
**Measured before the enum was widened**, 2026-11-16 on lobid: 392,941
differentiated persons carry an `orcid.org` link, 132,259 of them beside an
ISNI. Nothing here is speculative headroom.

**No backfill.** Nothing could have written a row under `orcid` before this
revision, so there is nothing to migrate.

Downgrade narrows the list back to the eleven `c9a5f27b3e41` left and **deletes
every `orcid` row first**, for the reason `d5e1b93a7c62` gives: narrowing a CHECK
with rows that violate it fails on a real database and is accepted on SQLite.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "bea3d1ed4b9c"
down_revision: str | Sequence[str] | None = "f4a9c2e17b30"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

#: Written out rather than imported from `models` or `enums`, for the reason
#: `a4c73e0b19d5` gives: a migration describes the schema at one point in time.
_SCHEMES_BEFORE = (
    "scheme IN ('gnd', 'isni', 'lcnaf', 'viaf', 'wikidata', "
    "'blbnb', 'arbabn', 'bne', 'ptbnp', 'iccu', 'bnchl')"
)
_SCHEMES_AFTER = (
    "scheme IN ('gnd', 'isni', 'lcnaf', 'viaf', 'wikidata', "
    "'blbnb', 'arbabn', 'bne', 'ptbnp', 'iccu', 'bnchl', 'orcid')"
)

_CONSTRAINT = "ck_author_identifiers_scheme"


def _swap(wanted: str) -> None:
    with op.batch_alter_table("author_identifiers") as batch:
        batch.drop_constraint(_CONSTRAINT, type_="check")
        batch.create_check_constraint(_CONSTRAINT, wanted)


def upgrade() -> None:
    _swap(_SCHEMES_AFTER)


def downgrade() -> None:
    op.execute(sa.text("DELETE FROM author_identifiers WHERE scheme = 'orcid'"))
    _swap(_SCHEMES_BEFORE)
