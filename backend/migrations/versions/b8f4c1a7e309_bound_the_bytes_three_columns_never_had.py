"""Bound the bytes three text columns never had, and give one address a rule.

Revision ID: b8f4c1a7e309
Revises: a6d3f92c7b14
Create Date: 2026-09-20

**`length()` counts one character per UTF-8 lead byte and skips continuation
bytes without limit**, which `f4a1c62d0b97` closed for five ceilings and
`a6d3f92c7b14` recorded on the two it left. Measured on sqlite 3.46.1 (the
`sqlite3` CLI) and 3.50.4 (this Python's module), which agree on every figure
below. Four columns, and the four are four different holes:

| constraint | what it had | what it was missing |
|---|---|---|
| `ck_book_identifiers_bounds` | a ceiling and a NUL clause | the budget that makes the ceiling exact |
| `ck_catalogue_targets_indexes` | a charset rule and a NUL clause | any bound on size at all |
| `ck_catalogue_credentials_envelope` | a shape and a floor | the ceiling a NUL clause would have needed |
| `ck_catalogue_targets_base_url` | **nothing** | the four arms its sibling column carries |

**None of them is urgent and saying so is part of the record.** `book_identifiers`
is reachable only through `backup.restore` of a hand edited archive, and an
archive's manifest is JSON, so every value it inserts is a Python string and
encodes at four bytes per character at worst: the reachable maximum is 240,
which is exactly the arm installed here. `catalogue_targets` is written by
`main.seed_catalogue_targets` from `targets.SEEDED` on every boot and by that
same restore, and nothing reads either index column off a row into a query
today. `catalogue_credentials` is admin only. What each arm is, is the last line
for a write that never came through this application, which is the reason
`ck_opds_servers_base_url` already gives for carrying one.

**`ck_book_identifiers_bounds`: 60 counted characters at 1,000,020 bytes.**
Sixty `x'C0'` lead bytes each followed by 16,666 continuation bytes satisfied
the ceiling and the NUL clause together, carrying no NUL for `instr` to find.
240 is four times the ceiling, four bytes being UTF-8's widest character, so
sixty four byte characters land exactly on the budget and nothing valid is
refused.

**`ck_catalogue_targets_indexes`: a charset rule bounds no size.** Both columns
were confined to `[A-Za-z0-9._]` with a NUL clause and given no `length()` term
of any kind, `String(64)` refusing nothing in SQLite, so the same lead byte trick
stored a megabyte in either. The bound here is written **on the bytes rather
than on the characters**, once rather than twice: the charset rule and the NUL
clause together admit only characters SQLite stores in one byte, so on this
column the two units are the same number, and the byte one is the one that still
binds if a later hand weakens either.

**`ck_catalogue_credentials_envelope`: the ceiling `a6d3f92c7b14` said was the
other question.** That revision left this constraint alone because a NUL clause
would have bounded nothing against a `Text` column with no ceiling, and said so
as the exclusion. The ceiling is 2,825 **bytes**, derived from what the two
writers can hand `credentials.seal` rather than chosen: `SourceCredentialIn`
bounds a username at 320 characters and a password at 200, they are sealed as
`username:password` encoded UTF-8, so the plaintext reaches 2,081 bytes; AES-GCM
adds a 16 byte tag, base64url of 2,097 bytes is 2,796 characters, and `v2`, the
eight character generation tag, the sixteen character nonce and three separators
make 29 more. Measured through `credentials.put`'s own call against a real key:
2,825. The OPDS route's 255 and 255 reach 2,772. An envelope is base64url and
dots, so it is ASCII and its bytes are its characters; the bound is in bytes
because that is the count a lead byte cannot walk past.

**And still no NUL clause on that one, on either engine.** Every clause it
carries now reads the whole value: a byte count is a byte count whatever is in
it, the floor reads **shorter** past a NUL and is therefore harder to satisfy,
and both `GLOB` patterns end in `*`, which absorbs any suffix, so truncation can
only make them fail. The asymmetry `a6d3f92c7b14` recorded survives this
revision with a better reason than the one it had.

**`ck_catalogue_targets_base_url` is new and had no predecessor at all**, where
`opds_servers.base_url` carries a scheme rule, a NUL clause and both ceilings.
Two columns holding an address a request is later built from, both written by
`backup.restore` through Core with no validating arm, and only one of them said
so. The four arms are that constraint's, for its reasons. What this refuses that
nothing refused before: a `file://` or `gopher://` address where a sync will
read it, an address of unbounded length, and a megabyte parked behind one lead
byte.

**What this does to existing rows: nothing, or it refuses to run.** A batch
rebuild is `INSERT INTO new SELECT FROM old` and SQLite enforces the new CHECK
on the copy. The first question asked of each of these bounds was whether a row
this application could already have written can fail one, and none can. All
eleven addresses in `targets.SEEDED` are `http` or `https` and the widest is 61
characters; the widest seeded index name is `bib.anywhere` at 12; a stored
envelope cannot exceed the figure derived above, and the two constants it is
derived from have never held another value, measured over this repository's
whole history. Every other writer binds a Python `str`. A failing row can only
have arrived through `backup.restore` of a hand edited archive, which is that
module's stated threat model, and failing loudly names the table where repairing
one silently would rewrite a store's own token, a query's index or an address a
sync then fetches.

**A failed batch rebuild leaves `_alembic_tmp_<table>` behind**, so a second
attempt fails on that table rather than on the row and reads like a different
fault. Drop it before retrying.

Downgrade drops each arm this adds and the whole constraint this adds. It
widens, so no row can fail it.
"""

from collections.abc import Sequence
from typing import NamedTuple

from alembic import op

from dialect import DialectSQL, SwappedRule

revision: str = "b8f4c1a7e309"
down_revision: str | Sequence[str] | None = "a6d3f92c7b14"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


class AddedRule(NamedTuple):
    """One CHECK a revision adds where the table carried none of that name.

    **Not a `SwappedRule` with an empty `before`**, which would read as a
    constraint whose earlier text was the empty string and would hand
    `drop_constraint` a name that is not there. The two lists are separate
    because the two directions of the migration are: a swap goes back to its
    `before`, and an addition goes back to nothing at all.

    This shape lives here rather than in `dialect.py` for the reason that module
    gives for holding no SQL: a revision is frozen, and a structure only one
    revision needs is one more thing a later edit could change under it.
    """

    table: str
    constraint: str
    sqlite: str
    postgresql: str


#: Every constraint this revision rewrites. `dialect.SwappedRule` names the six
#: fields and carries what `before` is checked against.
#:
#: **The SQL is written out rather than imported from `models`**, for the reason
#: every revision here gives: a migration describes the schema at one moment and
#: must not change meaning when a constant is retuned. The cost is a fact stored
#: twice, and `tests/test_schema.py::TestTheBoundsThisRevisionPutOnBytes` is
#: what stands between the SQLite copies;
#: `tests/test_dialect.py::TestTheRevisionsPostgresArmIsTheModelsPostgresArm`
#: stands between the Postgres ones.
#:
#: **`before` is checked against the schema this revision found** rather than
#: against itself, which is a tautology: `downgrade()` installs `before`, so a
#: test that downgrades and then compares scores any value at all. The
#: comparison that is evidence reads `sqlite_master` at `a6d3f92c7b14` before
#: upgrading. `f4a1c62d0b97` records how that was learned.
#:
#: **`length(CAST(x AS BLOB))` is SQLite's byte count and `octet_length(x)` is
#: Postgres's**, and the arm is kept on both rather than dropped as redundant on
#: either. The NUL clauses go with the engine, Postgres `text` and `varchar`
#: being unable to hold the byte, which is why `catalogue_targets`' Postgres arms
#: here gain a bound and no clause beside it.
_SWAPPED: tuple[SwappedRule, ...] = (
    SwappedRule(
        "book_identifiers",
        "ck_book_identifiers_bounds",
        "length(value) > 0 AND length(value) <= 60 AND instr(value, char(0)) = 0",
        "length(value) > 0 AND length(value) <= 60",
        "length(value) > 0 AND length(value) <= 60 AND instr(value, char(0)) = 0"
        " AND length(CAST(value AS BLOB)) <= 240",
        "length(value) > 0 AND length(value) <= 60"
        " AND octet_length(value) <= 240",
    ),
    SwappedRule(
        "catalogue_targets",
        "ck_catalogue_targets_indexes",
        "(isbn_index = '' OR isbn_index NOT GLOB '*[^A-Za-z0-9._]*') "
        "AND instr(isbn_index, char(0)) = 0 "
        "AND (title_index = '' OR title_index NOT GLOB '*[^A-Za-z0-9._]*') "
        "AND instr(title_index, char(0)) = 0",
        "(isbn_index = '' OR (isbn_index COLLATE \"C\") !~ '[^A-Za-z0-9._]') "
        "AND (title_index = '' OR (title_index COLLATE \"C\") !~ '[^A-Za-z0-9._]')",
        "(isbn_index = '' OR isbn_index NOT GLOB '*[^A-Za-z0-9._]*') "
        "AND instr(isbn_index, char(0)) = 0 "
        "AND length(CAST(isbn_index AS BLOB)) <= 64 "
        "AND (title_index = '' OR title_index NOT GLOB '*[^A-Za-z0-9._]*') "
        "AND instr(title_index, char(0)) = 0 "
        "AND length(CAST(title_index AS BLOB)) <= 64",
        "(isbn_index = '' OR (isbn_index COLLATE \"C\") !~ '[^A-Za-z0-9._]') "
        "AND octet_length(isbn_index) <= 64 "
        "AND (title_index = '' OR (title_index COLLATE \"C\") !~ '[^A-Za-z0-9._]') "
        "AND octet_length(title_index) <= 64",
    ),
    SwappedRule(
        "catalogue_credentials",
        "ck_catalogue_credentials_envelope",
        "(envelope GLOB 'v1.*.*.*' OR envelope GLOB 'v2.*.*.*') "
        "AND length(envelope) >= 40",
        r"(envelope ~ '^v1\..*\..*\.' OR envelope ~ '^v2\..*\..*\.') "
        "AND length(envelope) >= 40",
        "(envelope GLOB 'v1.*.*.*' OR envelope GLOB 'v2.*.*.*') "
        "AND length(envelope) >= 40 "
        "AND length(CAST(envelope AS BLOB)) <= 2825",
        r"(envelope ~ '^v1\..*\..*\.' OR envelope ~ '^v2\..*\..*\.') "
        "AND length(envelope) >= 40 "
        "AND octet_length(envelope) <= 2825",
    ),
)

#: The constraint this revision adds where the table carried none.
#:
#: A tuple of one, because the shape is what the next addition wants and a bare
#: pair of strings would have to be unpacked into one. Written out rather than
#: imported for the reason `_SWAPPED` states.
_ADDED: tuple[AddedRule, ...] = (
    AddedRule(
        "catalogue_targets",
        "ck_catalogue_targets_base_url",
        "(base_url GLOB 'http://?*' OR base_url GLOB 'https://?*') "
        "AND instr(base_url, char(0)) = 0 "
        "AND length(base_url) <= 255 "
        "AND length(CAST(base_url AS BLOB)) <= 1020",
        "(base_url ~ '^http://.' OR base_url ~ '^https://.') "
        "AND length(base_url) <= 255 "
        "AND octet_length(base_url) <= 1020",
    ),
)


def _swap(table: str, constraint: str, sqlite: str, postgresql: str) -> None:
    """Replace one CHECK, letting batch mode reflect everything else.

    **No `copy_from`**, which replaces reflection rather than supplementing it:
    `d5e1b93a7c62` records the two indexes a hand written `sa.Table` silently
    dropped. `book_identifiers` carries a unique index on the assertion and a
    scheme CHECK, `catalogue_targets` three further CHECKs, and
    `catalogue_credentials` the source rule, and all of them survive on
    reflection.
    """
    with op.batch_alter_table(table) as batch:
        batch.drop_constraint(constraint, type_="check")
        batch.create_check_constraint(
            constraint, DialectSQL(sqlite=sqlite, postgresql=postgresql)
        )


def _add(table: str, constraint: str, sqlite: str, postgresql: str) -> None:
    """Install one CHECK the table did not carry, through the same batch mode."""
    with op.batch_alter_table(table) as batch:
        batch.create_check_constraint(
            constraint, DialectSQL(sqlite=sqlite, postgresql=postgresql)
        )


def _drop(table: str, constraint: str) -> None:
    with op.batch_alter_table(table) as batch:
        batch.drop_constraint(constraint, type_="check")


def upgrade() -> None:
    for rule in _SWAPPED:
        _swap(rule.table, rule.constraint, rule.after, rule.after_pg)
    for added in _ADDED:
        _add(added.table, added.constraint, added.sqlite, added.postgresql)


def downgrade() -> None:
    for added in _ADDED:
        _drop(added.table, added.constraint)
    for rule in _SWAPPED:
        _swap(rule.table, rule.constraint, rule.before, rule.before_pg)
