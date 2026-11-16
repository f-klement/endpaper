"""The Royal Danish Library joins the roster, and ten ranks move down one.

Revision ID: b5d81e3f9a27
Revises: e7b3d05a2c91
Create Date: 2026-11-16

`e7b3d05a2c91` added the fourteenth row. This adds the fifteenth, Det Kgl.
Bibliotek, behind the BN_PL and ahead of Open Library, where the remit
placement in `sources.TAIL_MARGINAL` puts a catalogue asked only about Danish
ISBNs, and renumbers the ten rows below it in `sources.DEFAULT_ORDER`.

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

Downgrade deletes the row and puts the ten ranks back.
"""

from collections.abc import Sequence
from typing import Any

import sqlalchemy as sa
from alembic import op

revision: str = "b5d81e3f9a27"
down_revision: str | Sequence[str] | None = "e7b3d05a2c91"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

#: The row as it stands on the day this ran. The BNE's shape: lookup only, so
#: its three search columns are zero and empty.
_KB_DK_ROW: dict[str, Any] = {
    "source": "kb_dk",
    "rank": 4,
    "transport": "sru",
    "base_url": "https://eu01.alma.exlibrisgroup.com/view/sru/45KBDK_KGL",
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
    ("open_library", 4, 5),
    ("oenb", 5, 6),
    ("nkp", 6, 7),
    ("bne", 7, 8),
    ("libris", 8, 9),
    ("bna", 9, 10),
    ("bnu", 10, 11),
    ("google_books", 11, 12),
    ("bnf", 12, 13),
    ("loc", 13, 14),
)

#: Named columns rather than reflection, for the reason `d2b9f0c74a13` gives.
_TABLE = sa.table(
    "catalogue_targets",
    *(sa.column(name) for name in _KB_DK_ROW),
)


def upgrade() -> None:
    # Bottom up, so no intermediate state has two rows claiming one rank.
    for source, _was, becomes in reversed(_MOVED):
        op.execute(_TABLE.update().where(_TABLE.c.source == op.inline_literal(source)).values(rank=becomes))
    op.bulk_insert(_TABLE, [_KB_DK_ROW])


def downgrade() -> None:
    op.execute(_TABLE.delete().where(_TABLE.c.source == op.inline_literal("kb_dk")))
    # Forward order, the mirror of `upgrade`'s.
    for source, was, _becomes in _MOVED:
        op.execute(_TABLE.update().where(_TABLE.c.source == op.inline_literal(source)).values(rank=was))
