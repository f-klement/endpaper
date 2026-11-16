"""BIBSYS joins the roster, and five ranks move down one.

Revision ID: c6e92f4a0b38
Revises: b5d81e3f9a27
Create Date: 2026-11-16

`b5d81e3f9a27` added the fifteenth row. This adds the sixteenth, BIBSYS, the
Norwegian union catalogue, behind LIBRIS, and renumbers the five rows below it
in `sources.DEFAULT_ORDER`.

**No schema change, and the CHECK constraints admit this row unchanged**, for
the reasons `d2b9f0c74a13` checked for the BNE, whose shape this row has but
for its source, its rank and its address: it is `sru`, it does not waive the
ISBN identity check, `alma.isbn` is the BNE's own index, it names no PQF use
attribute, and its `base_url` is `https://` and short.

**A migration rather than the seeder alone**, for the reason `d2b9f0c74a13`
gives: `main.seed_catalogue_targets` grows a running deployment, and only a
revision grows the migrated database
`test_schema.py::TestTheSeededCatalogueTargetsMatchTheCode` compares against
`targets.SEEDED`.

**The row is written out here rather than imported**, so a library upgrading in
a year seeds the roster as it was on the day this ran. **The ranks are
rewritten by name and not by arithmetic**, for the reason `d2b9f0c74a13` gives.

Downgrade deletes the row and puts the five ranks back.
"""

from collections.abc import Sequence
from typing import Any

import sqlalchemy as sa
from alembic import op

revision: str = "c6e92f4a0b38"
down_revision: str | Sequence[str] | None = "b5d81e3f9a27"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

#: The row as it stands on the day this ran. The BNE's shape: lookup only, so
#: its three search columns are zero and empty.
_BIBSYS_ROW: dict[str, Any] = {
    "source": "bibsys",
    "rank": 10,
    "transport": "sru",
    "base_url": "https://bibsys.alma.exlibrisgroup.com/view/sru/47BIBSYS_NETWORK",
    "reader": "marc_gnd",
    "answers_lookup": True,
    "answers_search": False,
    "metered": False,
    "needs_key": False,
    "sru_version": "1.2",
    "query_parameter": "query",
    "query_language": "cql",
    "record_schema": "marcxml",
    "isbn_index": "alma.isbn",
    "isbn_attribute": None,
    "title_index": "",
    "title_query_shape": None,
    "lookup_records": 5,
    "search_multiplier": 0,
    "search_cap": 0,
    "refuses_component_parts": True,
    "requires_isbn_claim": True,
    "reads_author_identifiers": False,
    "timeout_seconds": None,
    "is_seeded": True,
}

#: What each displaced source's rank was, and what it becomes.
_MOVED: tuple[tuple[str, int, int], ...] = (
    ("bna", 10, 11),
    ("bnu", 11, 12),
    ("google_books", 12, 13),
    ("bnf", 13, 14),
    ("loc", 14, 15),
)

#: Named columns rather than reflection, for the reason `d2b9f0c74a13` gives.
_TABLE = sa.table(
    "catalogue_targets",
    *(sa.column(name) for name in _BIBSYS_ROW),
)


def upgrade() -> None:
    # Bottom up, so no intermediate state has two rows claiming one rank.
    for source, _was, becomes in reversed(_MOVED):
        op.execute(_TABLE.update().where(_TABLE.c.source == op.inline_literal(source)).values(rank=becomes))
    op.bulk_insert(_TABLE, [_BIBSYS_ROW])


def downgrade() -> None:
    op.execute(_TABLE.delete().where(_TABLE.c.source == op.inline_literal("bibsys")))
    # Forward order, the mirror of `upgrade`'s.
    for source, was, _becomes in _MOVED:
        op.execute(_TABLE.update().where(_TABLE.c.source == op.inline_literal(source)).values(rank=was))
