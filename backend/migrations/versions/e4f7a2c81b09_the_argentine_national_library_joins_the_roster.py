"""The Argentine national library joins the roster, and three ranks move down one.

Revision ID: e4f7a2c81b09
Revises: a7c41d9e6b28
Create Date: 2026-09-07

`d2b9f0c74a13` added the tenth row. This adds the eleventh, the Biblioteca
Nacional Argentina, and renumbers the three rows below it in
`sources.DEFAULT_ORDER`.

**No schema change, and the four CHECK constraints `b7d4e6f01a95` wrote all admit
this row unchanged**, which was checked rather than assumed: it is `sru`, it does
not waive the ISBN identity check, its two index names are empty, and its PQF use
attribute is 7, the one value `ck_catalogue_targets_use_attribute` permits. It is
the first seeded row to name a use attribute at all, so that constraint is
exercised here for the first time by a row rather than by a test.

**Why a migration at all, when `main.seed_catalogue_targets` reconciles the table
on every boot.** That seeder inserts a missing row, so a running deployment grows
this one without any revision. A **migrated** database would not, and that is the
database `test_schema.py::TestTheSeededCatalogueTargetsMatchTheCode` builds: it
runs `upgrade_to_head()` and nothing else, then asserts the table is exactly
`targets.SEEDED`. The seeder covers the deployment, this revision covers the
schema, and only together do they cover both. The ticket that added this row said
no schema change was needed, which is true of a deployment and false of the
suite, and that is the distinction this docstring exists to keep.

**The row is written out here rather than imported from `targets.SEEDED`**, the
rule `b7d4e6f01a95`, `a4c73e0b19d5`, `c9a5f27b3e41`, `c1f8a7e3d240` and
`d2b9f0c74a13` all state: a migration describes the data as it was on the day it
ran, so a library upgrading in a year does not seed a roster this revision never
saw.

**`needs_key` is true and `metered` is false, and that pair is new.** Every
earlier row that needed a credential was one that charged for requests. This
catalogue publishes its own login and charges nothing, which is why
`sources.NEEDS_A_KEY` and `sources.METERED` stopped being the same set on the day
this landed.

**The ranks are rewritten by name and not by arithmetic**, for the reason
`d2b9f0c74a13` gives: `rank + 1` above a threshold is wrong the moment a
household has edited a row.

Downgrade deletes the row and puts the three ranks back, returning the table to
what `d2b9f0c74a13` left. It does not drop the table: this revision did not
create it.
"""

from collections.abc import Sequence
from typing import Any

import sqlalchemy as sa
from alembic import op

revision: str = "e4f7a2c81b09"
down_revision: str | Sequence[str] | None = "a7c41d9e6b28"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

#: The row as it stands on the day this ran.
#:
#: `answers_search` is False and its three search columns are therefore zero and
#: empty, the same shape the NKP and BNE rows carry. `record_schema` is empty
#: because this catalogue answers bare Dublin Core and refuses `marcxml` with
#: diagnostic 1/66, and `lookup_records` is 1 because it renders one populated
#: record per response whatever is asked for.
_BNA_ROW: dict[str, Any] = {
    'source': 'bna',
    'rank': 7,
    'transport': 'sru',
    'base_url': 'http://200.123.191.9:9991/BNA01',
    'reader': 'dublin_core_bare',
    'answers_lookup': True,
    'answers_search': False,
    'metered': False,
    'needs_key': True,
    'sru_version': '1.1',
    'query_parameter': 'x-pquery',
    'query_language': 'pqf',
    'record_schema': '',
    'isbn_index': '',
    'isbn_attribute': 7,
    'title_index': '',
    'title_query_shape': None,
    'lookup_records': 1,
    'search_multiplier': 0,
    'search_cap': 0,
    'refuses_component_parts': False,
    'requires_isbn_claim': True,
    'reads_author_identifiers': False,
    'timeout_seconds': None,
    'is_seeded': True,
}

#: What each displaced source's rank becomes, and what it was.
_MOVED: tuple[tuple[str, int, int], ...] = (
    ('google_books', 7, 8),
    ('bnf', 8, 9),
    ('loc', 9, 10),
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
    # **Bottom up**, so no intermediate state has two rows claiming one rank,
    # for the reason `d2b9f0c74a13` records: ranks are not unique in the schema,
    # so this is what a reader debugging a half applied migration finds rather
    # than correctness.
    for source, _was, becomes in reversed(_MOVED):
        op.execute(
            _TABLE.update()
            .where(_TABLE.c.source == op.inline_literal(source))
            .values(rank=becomes)
        )
    op.bulk_insert(_TABLE, [_BNA_ROW])


def downgrade() -> None:
    op.execute(_TABLE.delete().where(_TABLE.c.source == op.inline_literal("bna")))
    # Forward order here, the mirror of `upgrade`'s: moving a rank **down**
    # collides with the row above it, so the row nearest the gap goes first.
    for source, was, _becomes in _MOVED:
        op.execute(
            _TABLE.update()
            .where(_TABLE.c.source == op.inline_literal(source))
            .values(rank=was)
        )
