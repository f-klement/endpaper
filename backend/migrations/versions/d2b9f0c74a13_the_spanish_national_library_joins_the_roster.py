"""The Spanish national library joins the roster, and five ranks move down one.

Revision ID: d2b9f0c74a13
Revises: f1c30ab27d84
Create Date: 2026-09-05

`b7d4e6f01a95` made a catalogue source a row and seeded nine. This adds the
tenth, the Biblioteca Nacional de España, and renumbers the five rows that sit
below it in `sources.DEFAULT_ORDER`.

**No schema change, and that is the point of the table.** The BNE reuses the
transport, the query language, the record schema and the reader the Austrian
National Library already uses, so adding a national catalogue is one INSERT and
five UPDATEs. The four CHECK constraints `b7d4e6f01a95` wrote all admit this row
unchanged: it is `sru`, it does not waive the ISBN identity check, its
`alma.isbn` carries nothing outside the index repertoire, and it names no PQF
use attribute.

**Why a migration at all, when `main.seed_catalogue_targets` reconciles the
table on every boot.** That seeder inserts a missing row, so a running
deployment would grow this one without any revision. A **migrated** database
would not, and that is the database
`test_schema.py::TestTheSeededCatalogueTargetsMatchTheCode` builds: it runs
`upgrade_to_head()` and nothing else, then asserts the table is exactly
`targets.SEEDED`. So the seeder covers the deployment and this revision covers
the schema, and only together do they cover both.

**The rows are written out here rather than imported from `targets.SEEDED`**,
which is the rule `b7d4e6f01a95`, `a4c73e0b19d5`, `c9a5f27b3e41` and
`c1f8a7e3d240` all state: a migration describes the data as it was on the day it
ran, so a library upgrading in a year does not seed a roster this revision never
saw.

**The ranks are rewritten by name and not by arithmetic.** `rank + 1` on
everything above a threshold reads more cleanly and is wrong the moment a
household has edited a row, which #130 makes possible; naming the five sources
and their new positions says what this revision knows and touches nothing else.

Downgrade deletes the row and puts the five ranks back, which returns the table
to what `b7d4e6f01a95` seeded. It does not drop the table: this revision did not
create it.
"""

from collections.abc import Sequence
from typing import Any

import sqlalchemy as sa
from alembic import op

revision: str = "d2b9f0c74a13"
down_revision: str | Sequence[str] | None = "f1c30ab27d84"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

#: The row as it stands on the day this ran.
#:
#: `answers_search` is False and its three search columns are therefore zero and
#: empty, the same shape the NKP row carries. The reason differs and is on
#: `targets.SEEDED`: the NKP cannot answer a search, and this one was never
#: measured answering one.
_BNE_ROW: dict[str, Any] = {
    'source': 'bne',
    'rank': 4,
    'transport': 'sru',
    'base_url': 'https://catalogo.bne.es/view/sru/34BNE_INST',
    'reader': 'marc_gnd',
    'answers_lookup': True,
    'answers_search': False,
    'metered': False,
    'needs_key': False,
    'sru_version': '1.2',
    'query_parameter': 'query',
    'query_language': 'cql',
    'record_schema': 'marcxml',
    'isbn_index': 'alma.isbn',
    'isbn_attribute': None,
    'title_index': '',
    'title_query_shape': None,
    'lookup_records': 5,
    'search_multiplier': 0,
    'search_cap': 0,
    'refuses_component_parts': True,
    'requires_isbn_claim': True,
    'reads_author_identifiers': False,
    'timeout_seconds': None,
    'is_seeded': True,
}

#: What each displaced source's rank becomes, and what it was.
_MOVED: tuple[tuple[str, int, int], ...] = (
    ('nlg', 4, 5),
    ('oenb', 5, 6),
    ('google_books', 6, 7),
    ('bnf', 7, 8),
    ('loc', 8, 9),
)

#: Named columns rather than `sa.table(...)` reflection, because `bulk_insert`
#: needs a table object and reflecting one would read whatever the database has
#: rather than what this revision was written against.
_TABLE = sa.table(
    "catalogue_targets",
    *(
        sa.column(name)
        for name in (
            "source", "rank", "transport", "base_url", "reader",
            "answers_lookup", "answers_search", "metered", "needs_key",
            "sru_version", "query_parameter", "query_language",
            "record_schema", "isbn_index", "isbn_attribute", "title_index",
            "title_query_shape", "lookup_records", "search_multiplier",
            "search_cap", "refuses_component_parts", "requires_isbn_claim",
            "reads_author_identifiers", "timeout_seconds", "is_seeded",
        )
    ),
)


def upgrade() -> None:
    # **Bottom up**, so no intermediate state has two rows claiming one rank.
    # Ranks are not unique in the schema, so this is not correctness; it is what
    # a reader debugging a half applied migration finds. Forward order gives
    # `nlg` rank 5 while `oenb` still holds 5, and then `oenb` rank 6 while
    # `google_books` still holds 6, which is the duplicate this avoids rather
    # than the one an earlier version of this comment claimed.
    for source, _was, becomes in reversed(_MOVED):
        op.execute(
            _TABLE.update()
            .where(_TABLE.c.source == op.inline_literal(source))
            .values(rank=becomes)
        )
    op.bulk_insert(_TABLE, [_BNE_ROW])


def downgrade() -> None:
    op.execute(_TABLE.delete().where(_TABLE.c.source == op.inline_literal("bne")))
    # Forward order here, and it is the mirror of `upgrade`'s: moving a rank
    # **down** collides with the row above it, so the row nearest the gap goes
    # first.
    for source, was, _becomes in _MOVED:
        op.execute(
            _TABLE.update()
            .where(_TABLE.c.source == op.inline_literal(source))
            .values(rank=was)
        )
