"""Bind every text ceiling on bytes too, so a NUL cannot walk past one.

Revision ID: f4a1c62d0b97
Revises: b2e94f7c1a03
Create Date: 2026-09-10

**SQLite's `length()` on text counts characters up to the first NUL.** Measured:
a value of `"a\\x00" + "x" * 10000` reports a `length()` of 1 and stores 10,002
bytes, so a ceiling written as a character inequality alone admits a value
nothing bounded. `b2e94f7c1a03` found this while writing
`ck_digital_references_bounds` and carried the arm that closes it; this revision
puts the same arm on every ceiling that predates it.

Five constraints, one arm each:

| constraint | column | characters |
|---|---|---|
| `ck_quotes_text_bounds` | `text`, `note` | 2000, 1000 |
| `ck_author_identifiers_bounds` | `identifier` | 60 |
| `ck_custom_fields_name_bounds` | `name` | 60 |
| `ck_custom_field_values_bounds` | `value` | 500 |
| `ck_opds_servers_name` | `name` | 100 |

**Four bytes is UTF-8's widest character**, so a byte budget of four times the
character budget refuses nothing NUL free the character arm already admits, and
the widest legitimate value lands exactly on it.

**It caps a NUL carrying value rather than refusing one**, and saying so is the
point: a first draft of this paragraph claimed the stronger thing. Measured, a
quote of `"a\x00" + "x" * 7998` is 8,000 bytes and is **accepted**; 8,001 is
not. So the slack a NUL buys is bounded at four times the ceiling instead of
being unbounded, which is the whole of what these constraints were written to
stop.

**`instr(x, char(0)) = 0` would make the character ceiling exact and is
deliberately not taken.** The two credential columns carry it because a NUL is
never a legitimate value there. These five hold text a member typed, `text` and
`note` above all, and the API stores a NUL in one today: `QuoteCreate` bounds
the Python string and does not refuse the character.
`tests/test_models.py::TestQuote::test_the_schema_admits_a_nul_which_is_why_this
_column_bounds_bytes` is the tripwire on that, because this reason is the whole
argument and it would otherwise go stale in silence the day somebody filters a
control character out of that schema. Adding that arm here would
therefore turn an upgrade that **cannot** fail on any row this application wrote
into one that fails on a row a member could already have pasted in, which is a
much larger change than the hole it closes.

**Floors are deliberately not touched.** A NUL shortens the count, so
`length(x) > 0` becomes stricter rather than weaker on the same value and there
is nothing to close.

**`GLOB` charset rules are a different class and none is here.** Stated as the
exclusion rather than as a count, because an earlier draft said "two" and named
one that is not in the class at all. `ck_catalogue_targets_indexes` is genuinely
defeated: `'bath.isbn\x00 or 1=1'` is accepted where `'bath.isbn or 1=1'` is
refused. `ck_opds_servers_base_url` is **not**, because a positive prefix GLOB
can only fail under truncation, measured on sqlite 3.46.1; its defect is that
nothing bounds the text after the prefix, which is a different one wanting the
same arm. `ck_catalogue_credentials_envelope` is defeated too and its column has
no ceiling to mirror. Each needs its own call about what else the value must
satisfy, so they are in the tracker rather than here.

**What this does to existing rows: nothing, or it refuses to run.** A batch
rebuild is `INSERT INTO new SELECT FROM old` and SQLite enforces the new CHECK
on that copy, measured, and `tests/test_schema.py` pins both halves rather than
leaving this paragraph as prose.

**And a failed rebuild leaves `_alembic_tmp_quotes` behind**, so a second attempt
fails on that table rather than on the row, which reads like a different fault.
Drop it before retrying. Found by the test above rather than reasoned about: it
poisoned every case after it in that module until the drop was added.

**Foreign keys are off while it runs**, which is why rebuilding a parent table
is safe here. `database.py` registers `PRAGMA foreign_keys=ON` on the
application's engine **instance**, and `migrations/env.py` builds its own through
`engine_from_config`, so nothing re-applies it during an upgrade. This is the
first revision to batch alter a table another table points at: `custom_fields`
has `custom_field_values` beneath it, and dropping it with rows there would fail
under enforcement. Do not move that PRAGMA onto the `Engine` class without
reading this.

**No row this application wrote can be that row**, and the reason is the whole
argument for not repairing anything here. Every write outside `backup.restore`
goes through a Pydantic `max_length`, which counts a Python string and therefore
counts past a NUL: 10,002 for the value above. A violating row can only have
arrived through a restore of an archive somebody edited by hand, which is the
threat model `backup.py` states. Deleting one silently would destroy a member's
quote to spare an operator a message about a file they were handed; failing
loudly names the table and is the outcome an operator should see.

Downgrade drops the byte arms and restores each constraint's character-only
text. It widens, so no row can fail it.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "f4a1c62d0b97"
down_revision: str | Sequence[str] | None = "b2e94f7c1a03"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

#: Every ceiling this revision widens with a byte arm, as
#: `(table, constraint, before, after)`.
#:
#: **The SQL is written out rather than imported from `models`**, for the reason
#: every revision here gives: a migration describes the schema at one moment and
#: must not change meaning when a constant is retuned. The cost is a fact stored
#: twice, and
#: `tests/test_schema.py::TestEveryTextCeilingIsInstalledWithItsByteArm` is what
#: stands between the copies.
#:
#: **`before` is what `downgrade()` installs, and it is checked against the
#: schema this revision found rather than against itself.**
#: `TestEveryTextCeilingIsInstalledWithItsByteArm::test_the_downgrade_puts_each
#: _ceiling_back` reads `sqlite_master` at `b2e94f7c1a03` before upgrading at
#: all, which is the only reading of it that is evidence: a version that
#: downgraded and then compared was a tautology, because `downgrade()` installs
#: exactly what it is asked to.
#:
#: `drop_constraint` takes a name, so the upgrade never reads `before` and a
#: wrong one breaks only the way back, silently and in the one situation nobody
#: is watching.
_CEILINGS: tuple[tuple[str, str, str, str], ...] = (
    (
        "quotes",
        "ck_quotes_text_bounds",
        "length(text) <= 2000 AND (note IS NULL OR length(note) <= 1000)",
        "length(text) <= 2000 "
        "AND length(CAST(text AS BLOB)) <= 8000 "
        "AND (note IS NULL OR (length(note) <= 1000 "
        "AND length(CAST(note AS BLOB)) <= 4000))",
    ),
    (
        "author_identifiers",
        "ck_author_identifiers_bounds",
        "length(identifier) > 0 AND length(identifier) <= 60",
        "length(identifier) > 0 AND length(identifier) <= 60"
        " AND length(CAST(identifier AS BLOB)) <= 240",
    ),
    (
        "custom_fields",
        "ck_custom_fields_name_bounds",
        "length(name) > 0 AND length(name) <= 60",
        "length(name) > 0 AND length(name) <= 60"
        " AND length(CAST(name AS BLOB)) <= 240",
    ),
    (
        "custom_field_values",
        "ck_custom_field_values_bounds",
        "length(value) > 0 AND length(value) <= 500",
        "length(value) > 0 AND length(value) <= 500"
        " AND length(CAST(value AS BLOB)) <= 2000",
    ),
    (
        "opds_servers",
        "ck_opds_servers_name",
        "length(name) BETWEEN 1 AND 100",
        "length(name) BETWEEN 1 AND 100 "
        "AND length(CAST(name AS BLOB)) <= 400",
    ),
)


def _swap(table: str, constraint: str, wanted: str) -> None:
    """Replace one CHECK, letting batch mode reflect everything else.

    **No `copy_from`**, which replaces reflection rather than supplementing it:
    `d5e1b93a7c62` records the two indexes a hand written `sa.Table` silently
    dropped, one of them the unique index enforcing that an identifier cannot be
    retyped. `opds_servers` carries a named `UniqueConstraint` and
    `custom_field_values` a unique index, and both survive on reflection.
    """
    with op.batch_alter_table(table) as batch:
        batch.drop_constraint(constraint, type_="check")
        batch.create_check_constraint(constraint, wanted)


def upgrade() -> None:
    for table, constraint, _, after in _CEILINGS:
        _swap(table, constraint, after)


def downgrade() -> None:
    for table, constraint, before, _ in _CEILINGS:
        _swap(table, constraint, before)
