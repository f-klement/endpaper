"""The Slovak National Library joins the roster over Z39.50.

Revision ID: 5c3e9a1d7b20
Revises: 2d87a872d78e
Create Date: 2026-11-17

`2d87a872d78e` added the first three Z39.50 rows. This adds a fourth, the SNK,
Slovakia's national library, after the OSZK and ahead of Open Library in
`sources.DEFAULT_ORDER`, and moves every rank from Open Library's down by one.

**The CHECK constraints admit the row** as they admit the three before it: it is
`z3950` with a `z3950://` address and a `record_charset`, it waives no ISBN
identity check, and it names use attribute 7 and no CQL index. It does not
retry as an ISBN-10, its index matching the ten digit form already.

**The row is written out here rather than imported**, and the ranks are
rewritten by name and not by arithmetic, for the reasons `d2b9f0c74a13` gives.

Downgrade deletes the row and puts the ranks back.
"""

from collections.abc import Sequence
from typing import Any

import sqlalchemy as sa
from alembic import op

revision: str = "5c3e9a1d7b20"
down_revision: str | Sequence[str] | None = "2d87a872d78e"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

#: The row as it stands on the day this ran.
_ROW: dict[str, Any] = {
    "source": "snk",
    "rank": 8,
    "transport": "z3950",
    "base_url": "z3950://z3950.snk.sk:1111/Default",
    "reader": "marc_gnd",
    "answers_lookup": True,
    "answers_search": False,
    "metered": False,
    "needs_key": False,
    "sru_version": "",
    "query_parameter": "",
    "query_language": "pqf",
    "record_schema": "marc21",
    "record_charset": "utf8",
    "isbn_index": "",
    "isbn_attribute": 7,
    "title_index": "",
    "title_query_shape": None,
    "lookup_records": 5,
    "retries_as_isbn10": False,
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
    ("open_library", 8, 9),
    ("oenb", 9, 10),
    ("nkp", 10, 11),
    ("bne", 11, 12),
    ("libris", 12, 13),
    ("melinda", 13, 14),
    ("bibsys", 14, 15),
    ("bna", 15, 16),
    ("bnu", 16, 17),
    ("google_books", 17, 18),
    ("bnf", 18, 19),
    ("loc", 19, 20),
)

#: Named columns rather than reflection, for the reason `d2b9f0c74a13` gives.
_TABLE = sa.table("catalogue_targets", *(sa.column(name) for name in _ROW))


def upgrade() -> None:
    # Bottom up, so no intermediate state has two rows claiming one rank.
    for source, _was, becomes in reversed(_MOVED):
        op.execute(_TABLE.update().where(_TABLE.c.source == op.inline_literal(source)).values(rank=becomes))
    op.bulk_insert(_TABLE, [_ROW])


def downgrade() -> None:
    op.execute(_TABLE.delete().where(_TABLE.c.source == op.inline_literal(_ROW["source"])))
    # Forward order, the mirror of `upgrade`'s.
    for source, was, _becomes in _MOVED:
        op.execute(_TABLE.update().where(_TABLE.c.source == op.inline_literal(source)).values(rank=was))
