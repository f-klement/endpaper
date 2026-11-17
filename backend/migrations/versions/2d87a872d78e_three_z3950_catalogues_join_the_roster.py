"""Three Z39.50 catalogues join the roster, with an ISBN-10 retry each.

Revision ID: 2d87a872d78e
Revises: 6ecb05b436b5
Create Date: 2026-11-17

`6ecb05b436b5` let a Z39.50 row exist. This adds the first three: the SBN,
Italy's union catalogue, PORBASE, Portugal's, and the OSZK, Hungary's national
library, ahead of Open Library in `sources.DEFAULT_ORDER`, and moves every
rank from Open Library's down by three.

**`retries_as_isbn10` is new**: whether a lookup that misses is asked once more
with the ISBN-10 form of the book. False on every row this revision finds, true
on the three it adds. Its rule couples it to what can carry it, as
`targets.Target` does: a row answering a lookup whose query this application
builds, so never a bespoke one.

**The CHECK constraints admit the three rows**: each is `z3950` with a
`z3950://` address and a `record_charset`, which `6ecb05b436b5` requires there;
none waives the ISBN identity check; each names use attribute 7, the one
`ck_catalogue_targets_use_attribute` admits; and none names a CQL index.

**The rows are written out here rather than imported**, and the ranks are
rewritten by name and not by arithmetic, for the reasons `d2b9f0c74a13` gives.

Downgrade deletes the three rows, puts the ranks back, and drops the rule and
the column.
"""

from collections.abc import Sequence
from typing import Any

import sqlalchemy as sa
from alembic import op

from dialect import AddedRule, DialectSQL

revision: str = "2d87a872d78e"
down_revision: str | Sequence[str] | None = "6ecb05b436b5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

#: The rule the new column carries.
_ADDED: tuple[AddedRule, ...] = (
    AddedRule(
        "catalogue_targets",
        "ck_catalogue_targets_isbn10_retry",
        "retries_as_isbn10 = 0 OR (answers_lookup = 1 AND transport <> 'bespoke')",
        "NOT retries_as_isbn10 OR (answers_lookup AND transport <> 'bespoke')",
    ),
)

#: What the three rows share: lookup only, PQF on use attribute 7, no SRU field.
_Z3950_ROW: dict[str, Any] = {
    "transport": "z3950",
    "answers_lookup": True,
    "answers_search": False,
    "metered": False,
    "needs_key": False,
    "sru_version": "",
    "query_parameter": "",
    "query_language": "pqf",
    "isbn_index": "",
    "isbn_attribute": 7,
    "title_index": "",
    "title_query_shape": None,
    "retries_as_isbn10": True,
    "search_multiplier": 0,
    "search_cap": 0,
    "requires_isbn_claim": True,
    "reads_author_identifiers": False,
    "timeout_seconds": None,
    "is_seeded": True,
}

#: The three rows as they stand on the day this ran.
_ROWS: tuple[dict[str, Any], ...] = (
    _Z3950_ROW
    | {
        "source": "sbn",
        "rank": 5,
        "base_url": "z3950://opac.sbn.it:2100/nopac",
        "reader": "marc_gnd",
        "record_schema": "marc21",
        "record_charset": "utf8",
        "lookup_records": 5,
        "refuses_component_parts": True,
    },
    _Z3950_ROW
    | {
        "source": "porbase",
        "rank": 6,
        "base_url": "z3950://z3950.catalogo.bnportugal.gov.pt:210/bn",
        "reader": "unimarc",
        "record_schema": "unimarc",
        "record_charset": "iso5426",
        "lookup_records": 1,
        "refuses_component_parts": False,
    },
    _Z3950_ROW
    | {
        "source": "oszk",
        "rank": 7,
        "base_url": "z3950://amicus.oszk.hu:1616/ANY",
        "reader": "marc_gnd",
        "record_schema": "marc21",
        "record_charset": "utf8",
        "lookup_records": 5,
        "refuses_component_parts": True,
    },
)

#: What each displaced source's rank was, and what it becomes.
_MOVED: tuple[tuple[str, int, int], ...] = (
    ("open_library", 5, 8),
    ("oenb", 6, 9),
    ("nkp", 7, 10),
    ("bne", 8, 11),
    ("libris", 9, 12),
    ("melinda", 10, 13),
    ("bibsys", 11, 14),
    ("bna", 12, 15),
    ("bnu", 13, 16),
    ("google_books", 14, 17),
    ("bnf", 15, 18),
    ("loc", 16, 19),
)

#: Named columns rather than reflection, for the reason `d2b9f0c74a13` gives.
_TABLE = sa.table("catalogue_targets", *(sa.column(name) for name in _ROWS[0]))


def upgrade() -> None:
    # One batch, so SQLite rebuilds the table once. The server default fills
    # the rows already there; the model's own default covers every later write.
    with op.batch_alter_table("catalogue_targets") as batch:
        batch.add_column(
            sa.Column("retries_as_isbn10", sa.Boolean(), server_default=sa.false(), nullable=False)
        )
        for added in _ADDED:
            batch.create_check_constraint(
                added.constraint, DialectSQL(sqlite=added.sqlite, postgresql=added.postgresql)
            )
    # Bottom up, so no intermediate state has two rows claiming one rank.
    for source, _was, becomes in reversed(_MOVED):
        op.execute(_TABLE.update().where(_TABLE.c.source == op.inline_literal(source)).values(rank=becomes))
    op.bulk_insert(_TABLE, list(_ROWS))


def downgrade() -> None:
    for row in _ROWS:
        op.execute(_TABLE.delete().where(_TABLE.c.source == op.inline_literal(row["source"])))
    # Forward order, the mirror of `upgrade`'s.
    for source, was, _becomes in _MOVED:
        op.execute(_TABLE.update().where(_TABLE.c.source == op.inline_literal(source)).values(rank=was))
    with op.batch_alter_table("catalogue_targets") as batch:
        for added in _ADDED:
            batch.drop_constraint(added.constraint, type_="check")
        batch.drop_column("retries_as_isbn10")
