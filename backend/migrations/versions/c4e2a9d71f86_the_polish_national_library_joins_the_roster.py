"""The Polish national library joins the roster, and the tail is reordered around it.

Revision ID: c4e2a9d71f86
Revises: bea3d1ed4b9c
Create Date: 2026-11-16

`a3e81c5d7f20` added the twelfth row. This adds the thirteenth, the Biblioteka
Narodowa, at rank 3, and renumbers ten rows to `sources.DEFAULT_ORDER` as it
stood with the BN_PL and without LIBRIS. That is more than an insertion: the
owner's rule of 2026-11-16 compares a remitted row with an unremitted one on the
remitted row's ISBNs alone, which moves the NLG ahead of Open Library and the
OeNB ahead of the NKP, and `TAIL_MARGINAL`'s docstring states it.

**No schema change, and the CHECK constraints admit this row unchanged**, for
the reasons `d2b9f0c74a13` checked for the BNE, which this one matches column for
column but for its source, its rank and its address: it is `sru`, it does not
waive the ISBN identity check, its `alma.isbn` carries nothing outside the index
repertoire, it names no PQF use attribute, and its `base_url` is `https://` and
short.

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

revision: str = "c4e2a9d71f86"
down_revision: str | Sequence[str] | None = "bea3d1ed4b9c"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

#: The row as it stands on the day this ran. The BNE's shape: lookup only, so
#: its three search columns are zero and empty.
_BN_PL_ROW: dict[str, Any] = {
    "source": "bn_pl",
    "rank": 3,
    "transport": "sru",
    "base_url": "https://bn-nl.alma.exlibrisgroup.com/view/sru/48OMNIS_NLOP",
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

#: What each moved source's rank was, and what it becomes.
#:
#: **Listed in the order `downgrade` writes them, and `upgrade` writes them in
#: reverse**, so each write lands on a rank nobody holds at that moment:
#: upgrade walks one chain, the LoC to 12 first through the NLG to 2, then the
#: OeNB takes the NLG's old 5 and last the NKP the OeNB's old 6, leaving 3 for
#: the new row. Ranks are not
#: unique in the schema, so this is not correctness; it is what a reader
#: debugging a half applied migration finds, as `d2b9f0c74a13` says.
_MOVED: tuple[tuple[str, int, int], ...] = (
    ("nkp", 3, 6),
    ("oenb", 6, 5),
    ("nlg", 5, 2),
    ("open_library", 2, 4),
    ("bne", 4, 7),
    ("bna", 7, 8),
    ("bnu", 8, 9),
    ("google_books", 9, 10),
    ("bnf", 10, 11),
    ("loc", 11, 12),
)

#: Named columns rather than reflection, for the reason `d2b9f0c74a13` gives.
_TABLE = sa.table(
    "catalogue_targets",
    *(sa.column(name) for name in _BN_PL_ROW),
)


def upgrade() -> None:
    # Reversed, so no intermediate state has two rows claiming one rank.
    for source, _was, becomes in reversed(_MOVED):
        op.execute(_TABLE.update().where(_TABLE.c.source == op.inline_literal(source)).values(rank=becomes))
    op.bulk_insert(_TABLE, [_BN_PL_ROW])


def downgrade() -> None:
    op.execute(_TABLE.delete().where(_TABLE.c.source == op.inline_literal("bn_pl")))
    # Forward order, the mirror of `upgrade`'s: the NKP takes the 3 the delete
    # freed, and each later row the rank the one before it left.
    for source, was, _becomes in _MOVED:
        op.execute(_TABLE.update().where(_TABLE.c.source == op.inline_literal(source)).values(rank=was))
