"""A catalogue source becomes a row, seeded with the nine this release ships.

Revision ID: b7d4e6f01a95
Revises: a3f7c1d94e82
Create Date: 2026-09-03

A source's address, transport, query indexes and record bounds were nine sets of
Python constants and eleven near identical adapters. They are one table and one
SRU door now, and adding a national catalogue is a row plus, only if its record
format is genuinely new, a reader. The parsers did not move: a row picks a
reader, it cannot say what a reader accepts.

**A fresh install is identical to the release before this one**, which is the
only property this had to have, and it holds by construction rather than by
comparison: `targets.SEEDED` is the same data the deleted per source constants
held, and it is what the runtime reads. This table is seeded from it and read by
nothing yet. #130 makes a row editable and is its first reader, #132 enforces
`timeout_seconds`, and #32 adds the institution's hard filter.

**The rows are written out here rather than imported from `targets.SEEDED`**,
which is the rule `a4c73e0b19d5`, `c9a5f27b3e41` and `c1f8a7e3d240` all state: a
migration describes the schema and the data as they were on the day it ran.
Importing today's constants would make a library upgrading in a year seed a
roster this revision never saw. `main.seed_catalogue_targets` is what keeps the
table current after that, and
`test_schema.py::TestTheSeededCatalogueTargetsMatchTheCode` is what makes this
literal and that constant agree today.

## The CHECK constraints, which are the only enforcement that reaches a restore

`targets.Target.__post_init__` validates every invariant it can see on one row,
and it fires on nothing a database returns. `backup.restore` deletes and
reinserts through Core, where, in `backup.py`'s own words, `@validates` never
fires and a dataclass never runs at all, and that file has already settled the
trust question: an admin is not a reason to trust a file, since it may have come
from another deployment or have been edited by hand. `docs/security.md` records
what one restored row did to `custom_fields.kind`.

So three constraints, each stating a refusal the Python already makes:

* **`ck_catalogue_targets_isbn_claim`** allows `requires_isbn_claim` to be false
  for the DNB alone. Everywhere else that check is the identity test, and at the
  Austrian National Library it is the whole defence against a mistyped index,
  which answers HTTP 200 with 7,793,152 records and no diagnostic rather than
  with an error. One boolean flipped on a restored row would put an arbitrary
  catalogue record on a member's shelf from a barcode scan. The DNB waives it
  because its `num=` index matches cross references and refusing there turns a
  live lookup into a miss; it ranks instead.
* **`ck_catalogue_targets_transport`** refuses `z3950`, which is the refusal
  `Target.__post_init__` makes because there is no Z39.50 door yet. #129 lifts it
  in both places at once.
* **`ck_catalogue_targets_indexes`** refuses `=`, a quote, a space, a
  parenthesis, `<`, `>`, `/` and a backslash in either index column, which is
  `targets._INDEX` stated in what SQLite has. An index name is concatenated into
  a CQL query unquoted, so this is the substitution defence the ticket's own
  comment asked to be written down.

Downgrade drops the table. Nothing outside it references it, and nothing reads
it, so there is no data to preserve and no row anywhere to orphan.
"""

from collections.abc import Sequence
from typing import Any

import sqlalchemy as sa
from alembic import op

revision: str = "b7d4e6f01a95"
down_revision: str | Sequence[str] | None = "a3f7c1d94e82"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

#: An index name's whole repertoire as a **negated** GLOB class: letters,
#: digits, a dot and an underscore, which is `targets._INDEX` stated in what
#: SQLite has.
#:
#: **Negated rather than a denylist, and the difference was measured.** The
#: first version listed ten characters to refuse; a critic ran 25 index shapes
#: against it and against the regex and they disagreed on **15**, seven of which
#: carry a CQL token separator the list did not name, TAB and NBSP among them.
#: This spelling closes 14 of the 15. The residual is an embedded NUL, which
#: SQLite's pattern matcher stops at.
#:
#: **Not an equality with that regex, and it cannot be one.** A CHECK has no way
#: to spell "one dot, not two", so six shapes of nineteen pass here and fail
#: there, all of them character safe. `models.CatalogueTarget` names them. What
#: is zero is the direction a restore needs: nothing `targets._INDEX` accepts is
#: refused here.
_INDEX_REPERTOIRE = "*[^A-Za-z0-9._]*"

_SEEDED_ROWS: list[dict[str, Any]] = [
    {
        'source': 'dnb',
        'rank': 0,
        'transport': 'sru',
        'base_url': 'https://services.dnb.de/sru/dnb',
        'reader': 'marc_gnd',
        'answers_lookup': True,
        'answers_search': True,
        'metered': False,
        'needs_key': False,
        'sru_version': '1.1',
        'query_parameter': 'query',
        'query_language': 'cql',
        'record_schema': 'MARC21-xml',
        'isbn_index': 'num',
        'isbn_attribute': None,
        'title_index': 'WOE',
        'title_query_shape': 'word_sequence',
        'lookup_records': 5,
        'search_multiplier': 3,
        'search_cap': 50,
        'refuses_component_parts': False,
        'requires_isbn_claim': False,
        'reads_author_identifiers': True,
        'timeout_seconds': None,
        'is_seeded': True,
    },
    {
        'source': 'k10plus',
        'rank': 1,
        'transport': 'sru',
        'base_url': 'https://sru.k10plus.de/opac-de-627',
        'reader': 'marc_plain',
        'answers_lookup': True,
        'answers_search': True,
        'metered': False,
        'needs_key': False,
        'sru_version': '1.1',
        'query_parameter': 'query',
        'query_language': 'cql',
        'record_schema': 'marcxml',
        'isbn_index': 'pica.isb',
        'isbn_attribute': None,
        'title_index': 'pica.all',
        'title_query_shape': 'anded_terms',
        'lookup_records': 5,
        'search_multiplier': 3,
        'search_cap': 50,
        'refuses_component_parts': False,
        'requires_isbn_claim': True,
        'reads_author_identifiers': False,
        'timeout_seconds': None,
        'is_seeded': True,
    },
    {
        'source': 'open_library',
        'rank': 2,
        'transport': 'bespoke',
        'base_url': 'https://openlibrary.org',
        'reader': 'open_library',
        'answers_lookup': True,
        'answers_search': True,
        'metered': False,
        'needs_key': False,
        'sru_version': '',
        'query_parameter': '',
        'query_language': None,
        'record_schema': '',
        'isbn_index': '',
        'isbn_attribute': None,
        'title_index': '',
        'title_query_shape': None,
        'lookup_records': 0,
        'search_multiplier': 0,
        'search_cap': 0,
        'refuses_component_parts': False,
        'requires_isbn_claim': True,
        'reads_author_identifiers': False,
        'timeout_seconds': None,
        'is_seeded': True,
    },
    {
        'source': 'nkp',
        'rank': 3,
        'transport': 'sru',
        'base_url': 'http://aleph.nkp.cz:9991/NKC',
        'reader': 'dublin_core_bare',
        'answers_lookup': True,
        'answers_search': False,
        'metered': False,
        'needs_key': False,
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
    },
    {
        'source': 'nlg',
        'rank': 4,
        'transport': 'sru',
        'base_url': 'http://catalogue.nlg.gr:210/biblios',
        'reader': 'marc_gnd',
        'answers_lookup': True,
        'answers_search': True,
        'metered': False,
        'needs_key': False,
        'sru_version': '1.1',
        'query_parameter': 'query',
        'query_language': 'cql',
        'record_schema': 'marcxml',
        'isbn_index': 'dc.isbn',
        'isbn_attribute': None,
        'title_index': 'dc.title',
        'title_query_shape': 'anded_terms',
        'lookup_records': 5,
        'search_multiplier': 3,
        'search_cap': 50,
        'refuses_component_parts': True,
        'requires_isbn_claim': True,
        'reads_author_identifiers': False,
        'timeout_seconds': None,
        'is_seeded': True,
    },
    {
        'source': 'oenb',
        'rank': 5,
        'transport': 'sru',
        'base_url': 'https://obv-at-oenb.alma.exlibrisgroup.com/view/sru/43ACC_ONB',
        'reader': 'marc_gnd',
        'answers_lookup': True,
        'answers_search': True,
        'metered': False,
        'needs_key': False,
        'sru_version': '1.2',
        'query_parameter': 'query',
        'query_language': 'cql',
        'record_schema': 'marcxml',
        'isbn_index': 'alma.isbn',
        'isbn_attribute': None,
        'title_index': 'alma.title',
        'title_query_shape': 'anded_terms',
        'lookup_records': 5,
        'search_multiplier': 3,
        'search_cap': 50,
        'refuses_component_parts': True,
        'requires_isbn_claim': True,
        'reads_author_identifiers': False,
        'timeout_seconds': None,
        'is_seeded': True,
    },
    {
        'source': 'google_books',
        'rank': 6,
        'transport': 'bespoke',
        'base_url': 'https://www.googleapis.com/books/v1/volumes',
        'reader': 'google_books',
        'answers_lookup': True,
        'answers_search': True,
        'metered': True,
        'needs_key': True,
        'sru_version': '',
        'query_parameter': '',
        'query_language': None,
        'record_schema': '',
        'isbn_index': '',
        'isbn_attribute': None,
        'title_index': '',
        'title_query_shape': None,
        'lookup_records': 0,
        'search_multiplier': 0,
        'search_cap': 0,
        'refuses_component_parts': False,
        'requires_isbn_claim': True,
        'reads_author_identifiers': False,
        'timeout_seconds': None,
        'is_seeded': True,
    },
    {
        'source': 'bnf',
        'rank': 7,
        'transport': 'sru',
        'base_url': 'https://catalogue.bnf.fr/api/SRU',
        'reader': 'dublin_core',
        'answers_lookup': False,
        'answers_search': True,
        'metered': False,
        'needs_key': False,
        'sru_version': '1.2',
        'query_parameter': 'query',
        'query_language': 'cql',
        'record_schema': 'dublincore',
        'isbn_index': '',
        'isbn_attribute': None,
        'title_index': 'bib.anywhere',
        'title_query_shape': 'quoted_all',
        'lookup_records': 0,
        'search_multiplier': 2,
        'search_cap': 20,
        'refuses_component_parts': False,
        'requires_isbn_claim': True,
        'reads_author_identifiers': False,
        'timeout_seconds': None,
        'is_seeded': True,
    },
    {
        'source': 'loc',
        'rank': 8,
        'transport': 'sru',
        'base_url': 'http://lx2.loc.gov:210/lcdb',
        'reader': 'mods',
        'answers_lookup': False,
        'answers_search': True,
        'metered': False,
        'needs_key': False,
        'sru_version': '1.1',
        'query_parameter': 'query',
        'query_language': 'cql',
        'record_schema': 'mods',
        'isbn_index': '',
        'isbn_attribute': None,
        'title_index': 'dc.title',
        'title_query_shape': 'quoted_phrase',
        'lookup_records': 0,
        'search_multiplier': 2,
        'search_cap': 20,
        'refuses_component_parts': False,
        'requires_isbn_claim': True,
        'reads_author_identifiers': False,
        'timeout_seconds': None,
        'is_seeded': True,
    },
]


def upgrade() -> None:
    table = op.create_table(
        "catalogue_targets",
        sa.Column("source", sa.String(length=32), primary_key=True),
        sa.Column("rank", sa.Integer(), nullable=False),
        sa.Column("transport", sa.String(length=16), nullable=False),
        sa.Column("base_url", sa.String(length=255), nullable=False),
        sa.Column("reader", sa.String(length=32), nullable=False),
        sa.Column("answers_lookup", sa.Boolean(), nullable=False),
        sa.Column("answers_search", sa.Boolean(), nullable=False),
        sa.Column("metered", sa.Boolean(), nullable=False),
        sa.Column("needs_key", sa.Boolean(), nullable=False),
        sa.Column("sru_version", sa.String(length=8), nullable=False),
        sa.Column("query_parameter", sa.String(length=32), nullable=False),
        sa.Column("query_language", sa.String(length=8), nullable=True),
        sa.Column("record_schema", sa.String(length=32), nullable=False),
        sa.Column("isbn_index", sa.String(length=64), nullable=False),
        sa.Column("isbn_attribute", sa.Integer(), nullable=True),
        sa.Column("title_index", sa.String(length=64), nullable=False),
        sa.Column("title_query_shape", sa.String(length=32), nullable=True),
        sa.Column("lookup_records", sa.Integer(), nullable=False),
        sa.Column("search_multiplier", sa.Integer(), nullable=False),
        sa.Column("search_cap", sa.Integer(), nullable=False),
        sa.Column("refuses_component_parts", sa.Boolean(), nullable=False),
        sa.Column("requires_isbn_claim", sa.Boolean(), nullable=False),
        sa.Column("reads_author_identifiers", sa.Boolean(), nullable=False),
        sa.Column("timeout_seconds", sa.Float(), nullable=True),
        sa.Column("is_seeded", sa.Boolean(), nullable=False),
        sa.CheckConstraint(
            "requires_isbn_claim = 1 OR source = 'dnb'",
            name="ck_catalogue_targets_isbn_claim",
        ),
        sa.CheckConstraint(
            "transport IN ('sru', 'bespoke')",
            name="ck_catalogue_targets_transport",
        ),
        sa.CheckConstraint(
            f"(isbn_index = '' OR isbn_index NOT GLOB '{_INDEX_REPERTOIRE}') "
            f"AND (title_index = '' OR title_index NOT GLOB '{_INDEX_REPERTOIRE}')",
            name="ck_catalogue_targets_indexes",
        ),
        # `targets._USE_ATTRIBUTES` in SQL. The column is declared INTEGER and
        # SQLite's affinity is a preference, so a Core insert stores
        # `'7 @and @attr 1=4 x'` as text and `z3950.query` would render a two
        # term `@and`. Both halves refuse that one; `typeof` refuses nothing the
        # `IN` does not, so it is redundant rather than dead, and it is kept as a
        # type test beside a value test. `models.CatalogueTarget` carries the
        # seven probes and what each spelling does to them.
        sa.CheckConstraint(
            "isbn_attribute IS NULL OR (typeof(isbn_attribute) = 'integer' "
            "AND isbn_attribute IN (7))",
            name="ck_catalogue_targets_use_attribute",
        ),
    )
    op.bulk_insert(table, _SEEDED_ROWS)


def downgrade() -> None:
    op.drop_table("catalogue_targets")
