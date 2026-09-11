"""A NUL clause on two GLOB rules, put there for two different reasons.

Revision ID: a6d3f92c7b14
Revises: c7b0a3e5d281
Create Date: 2026-09-11

**SQLite's `GLOB` is a C string operation and stops at the first NUL**, exactly
as `length()` does, which `f4a1c62d0b97` closed for every character ceiling.
Five CHECK constraints in this schema rest on `GLOB`; **three carry no NUL clause
beside them, and only one of those three is defeated by that**. Both qualifiers
are load bearing, and stating the three separately is the point: a first account
of this said two and named one that is not in the class.

Measured on sqlite 3.46.1 (the `sqlite3` CLI) and 3.50.4 (this Python's module),
which agree on every figure below.

| constraint | shape | what the arm is for |
|---|---|---|
| `ck_catalogue_targets_indexes` | negative charset `GLOB` | truncation hides the rest of the value |
| `ck_opds_servers_base_url` | positive prefix `GLOB` | nothing bounds the text after the prefix |
| `ck_catalogue_credentials_envelope` | positive shape `GLOB` | not here: no ceiling to make exact |

**`ck_catalogue_targets_indexes` is defeated.** A negative charset rule reads the
text up to a NUL and never sees the rest, so `'bath.isbn or 1=1'` is refused and
`'bath.isbn' || char(0) || ' or 1=1'` is stored, nine characters by `length()`
and seventeen bytes on disk. `instr(x, char(0)) = 0` is the whole fix, and it is
the clause `ck_catalogue_credentials_source` already carries.

**`ck_opds_servers_base_url` is not defeated**, and this revision gives it the
same clause for a different reason. A positive prefix can only fail under
truncation: `'file:///etc/passwd' || char(0) || 'http://x'`,
`'ht' || char(0) || 'tp://x'` and `'http://' || char(0)` are all refused. Its
defect is that it placed no rule and no bound on the text after the prefix, so
`'http://x' || char(0) || <a megabyte>` stored 1,000,009 bytes in a column every
sync walks, with `length()` reporting 8.

**So this revision gives it a ceiling in both units, and the three arms are three
different rules.** `instr(base_url, char(0)) = 0` makes a character count
readable; `length(base_url) <= 255` is the column's declared width, which
`models.BASE_URL_MAX` already holds every write through the route to, being what
`schemas/opds.py` imports; and `length(CAST(base_url AS BLOB)) <= 1020` is the only one that counts what
reaches the disk. **A character ceiling bounds no bytes**, which is the half a
first draft of this paragraph got wrong by reasoning from UTF-8 rather than
measuring: `length()` counts a lead byte and skips continuation bytes without
limit, so the same megabyte behind one `x'C0'` instead of a NUL satisfies both
other arms, at 1,000,009 bytes with `length()` reporting 9.

1,020 is four times the character ceiling, and **no writer in this application
can reach it**: each binds a Python `str`, an archive is JSON, so what arrives is
valid UTF-8 and the character ceiling already implies the byte one. The widest
**valid** value is 999 bytes; an invalid one of 255 characters runs to 2,478,
measured, which is the value this arm exists to refuse. The arm is the last line for a
write that never came through the application at all, which is the reason the
scheme rule it joins exists. This is the arm `ck_opds_servers_name` carries on
the same table.

**`ck_catalogue_credentials_envelope` is defeated and is deliberately not
touched.** A valid shape followed by a NUL and 50,000 characters is stored
whole, 50,048 bytes, with `length()` reporting 47. `envelope` is `Text` and has no ceiling, so
`instr` alone would bound nothing; what that column may hold is
`credentials.unseal`'s question and not this revision's. Stated here as the
exclusion, because an inclusion is what goes stale.

**What this does to existing rows: nothing, or it refuses to run.** A batch
rebuild is `INSERT INTO new SELECT FROM old` and SQLite enforces the new CHECK on
the copy. **Both tables are in `backup._TABLES`**, so a row in either can only
fail if it arrived through `backup.restore` of a hand edited archive, which is
that module's stated threat model: every other writer validates first, and
`main.seed_catalogue_targets` holds each seeded index to
`targets._INDEX.fullmatch`. Failing loudly names the table, where repairing a row
silently would change an index a query is built from, or an address a sync then
fetches.

**A failed batch rebuild leaves `_alembic_tmp_<table>` behind**, so a second
attempt fails on that table rather than on the row and reads like a different
fault. Drop it before retrying.

Downgrade restores each constraint's earlier text. It widens both, so no row can
fail it.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "a6d3f92c7b14"
down_revision: str | Sequence[str] | None = "c7b0a3e5d281"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

#: Each GLOB rule this revision rewrites, as `(table, constraint, before, after)`.
#:
#: **The SQL is written out rather than imported from `models`**, for the reason
#: every revision here gives: a migration describes the schema at one moment and
#: must not change meaning when a constant is retuned. The cost is a fact stored
#: twice, and `tests/test_schema.py::TestTheGlobRulesThatLearnedAboutNul` is what
#: stands between the copies.
#:
#: **`before` is what `downgrade()` installs, and it is checked against the
#: schema this revision found rather than against itself**: `drop_constraint`
#: takes a name, so `upgrade()` never reads `before` and a wrong one breaks only
#: the way back, in the one situation nobody is watching.
_GLOB_RULES: tuple[tuple[str, str, str, str], ...] = (
    (
        "catalogue_targets",
        "ck_catalogue_targets_indexes",
        "(isbn_index = '' OR isbn_index NOT GLOB '*[^A-Za-z0-9._]*') "
        "AND (title_index = '' OR title_index NOT GLOB '*[^A-Za-z0-9._]*')",
        "(isbn_index = '' OR isbn_index NOT GLOB '*[^A-Za-z0-9._]*') "
        "AND instr(isbn_index, char(0)) = 0 "
        "AND (title_index = '' OR title_index NOT GLOB '*[^A-Za-z0-9._]*') "
        "AND instr(title_index, char(0)) = 0",
    ),
    (
        "opds_servers",
        "ck_opds_servers_base_url",
        "base_url GLOB 'http://?*' OR base_url GLOB 'https://?*'",
        "(base_url GLOB 'http://?*' OR base_url GLOB 'https://?*') "
        "AND instr(base_url, char(0)) = 0 "
        "AND length(base_url) <= 255 "
        "AND length(CAST(base_url AS BLOB)) <= 1020",
    ),
)


def _swap(table: str, constraint: str, wanted: str) -> None:
    """Replace one CHECK, letting batch mode reflect everything else.

    **No `copy_from`**, which replaces reflection rather than supplementing it:
    `d5e1b93a7c62` records the two indexes a hand written `sa.Table` silently
    dropped. `opds_servers` carries a named `UniqueConstraint` on
    `credential_key` and `catalogue_targets` three further CHECKs, and all of
    them survive on reflection.
    """
    with op.batch_alter_table(table) as batch:
        batch.drop_constraint(constraint, type_="check")
        batch.create_check_constraint(constraint, wanted)


def upgrade() -> None:
    for table, constraint, _, after in _GLOB_RULES:
        _swap(table, constraint, after)


def downgrade() -> None:
    for table, constraint, before, _ in _GLOB_RULES:
        _swap(table, constraint, before)
