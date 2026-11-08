"""The Uruguayan national library joins the roster, and three ranks move down one.

Revision ID: a3e81c5d7f20
Revises: f7a3c91e2d48
Create Date: 2026-11-07

`e4f7a2c81b09` added the eleventh row. This adds the twelfth, the Biblioteca
Nacional de Uruguay, and renumbers the three rows below it in
`sources.DEFAULT_ORDER`.

**No schema change, and the CHECK constraints admit this row unchanged**, for
the reasons `e4f7a2c81b09` checked for the Argentine row, which this one matches
column for column but for its source, its rank and its address: it is `sru`, it
does not waive the ISBN identity check, its two index names are empty, its PQF
use attribute is 7, and its `base_url` is `http://` and short.

**A migration rather than the seeder alone**, for the reason `e4f7a2c81b09`
gives: `main.seed_catalogue_targets` grows a running deployment, and only a
revision grows the migrated database
`test_schema.py::TestTheSeededCatalogueTargetsMatchTheCode` compares against
`targets.SEEDED`.

**The row is written out here rather than imported**, so a library upgrading in
a year seeds the roster as it was on the day this ran. **The ranks are
rewritten by name and not by arithmetic**, for the reason `d2b9f0c74a13` gives.

Downgrade deletes the row and puts the three ranks back.
"""

from collections.abc import Sequence
from typing import Any

import sqlalchemy as sa
from alembic import op

revision: str = "a3e81c5d7f20"
down_revision: str | Sequence[str] | None = "f7a3c91e2d48"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

#: The row as it stands on the day this ran. The Argentine row's shape: bare
#: Dublin Core with no `recordSchema`, PQF in `x-pquery`, one record a lookup.
_BNU_ROW: dict[str, Any] = {
    "source": "bnu",
    "rank": 8,
    "transport": "sru",
    "base_url": "http://164.73.2.157:9992/BNU01",
    "reader": "dublin_core_bare",
    "answers_lookup": True,
    "answers_search": False,
    "metered": False,
    "needs_key": True,
    "sru_version": "1.1",
    "query_parameter": "x-pquery",
    "query_language": "pqf",
    "record_schema": "",
    "isbn_index": "",
    "isbn_attribute": 7,
    "title_index": "",
    "title_query_shape": None,
    "lookup_records": 1,
    "search_multiplier": 0,
    "search_cap": 0,
    "refuses_component_parts": False,
    "requires_isbn_claim": True,
    "reads_author_identifiers": False,
    "timeout_seconds": None,
    "is_seeded": True,
}

#: What each displaced source's rank becomes, and what it was.
_MOVED: tuple[tuple[str, int, int], ...] = (
    ("google_books", 8, 9),
    ("bnf", 9, 10),
    ("loc", 10, 11),
)

#: Named columns rather than reflection, for the reason `e4f7a2c81b09` gives.
_TABLE = sa.table(
    "catalogue_targets",
    *(sa.column(name) for name in _BNU_ROW),
)


def upgrade() -> None:
    # Bottom up, so no intermediate state has two rows claiming one rank.
    for source, _was, becomes in reversed(_MOVED):
        op.execute(_TABLE.update().where(_TABLE.c.source == op.inline_literal(source)).values(rank=becomes))
    op.bulk_insert(_TABLE, [_BNU_ROW])


def downgrade() -> None:
    op.execute(_TABLE.delete().where(_TABLE.c.source == op.inline_literal("bnu")))
    # Forward order, the mirror of `upgrade`'s.
    for source, was, _becomes in _MOVED:
        op.execute(_TABLE.update().where(_TABLE.c.source == op.inline_literal(source)).values(rank=was))
