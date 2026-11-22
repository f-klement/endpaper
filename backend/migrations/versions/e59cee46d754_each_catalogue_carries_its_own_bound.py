"""Each catalogue carries its own bound, and the table refuses one out of range.

Revision ID: e59cee46d754
Revises: 8a7989a3fab0
Create Date: 2026-11-19

`targets.Target.timeout_seconds` ends one question to one catalogue. This
writes the seeded bounds and adds `ck_catalogue_targets_timeout`, the rule
`targets.Target._check_timeout` holds in Python: NULL, or over 0 and at most
10 seconds.

**Out of range values are cleared before the rule is added**, so a database
restored from a hand edited archive upgrades rather than failing on the
constraint. On PostgreSQL that clears a NaN too, which compares above every
number there; SQLite stores NaN as NULL.

**Every row is updated by its source alone, whatever it held.** No row can
carry a value a household chose: nothing edits a catalogue row yet, and
`main.seed_catalogue_targets` writes `targets.SEEDED` over every seeded row on
every boot, `is_seeded` or not. A condition such as `timeout_seconds IS NULL`
would only let a restored archive's value and the constant disagree until that
boot. The day a row can be edited, that change decides what survives.

**The seeds are a margin over a measurement** taken through the application's
own seam on 2026-11-19: the slowest ask the row answered, doubled and rounded
up to whole seconds, at least 3 and at most 10, plus one second on a Z39.50 row
because its client waits whole seconds and truncates. The slowest rather than
the 95th percentile, because over about 20 asks the percentile discards the one
or two slowest, and at the BNE that was an ask taking 80% of the bound.
A row with no trustworthy measurement keeps NULL, which is one request's own
10 seconds as before:

* the DNB, which refused this cluster's requests that day, so its timings were
  of a refusal;
* the SBN, which timed out on every ask, and the SNK, which dropped the
  connection on most of them;
* Open Library, whose slowest asks reached the transport's 10 seconds, so the
  measurement was of the ceiling rather than of the catalogue;
* the BNA, the BnU and Google Books, which need a key the measurement did not
  hold.

**Written out rather than imported from `targets.SEEDED`**, for the reason
`c1f8a7e3d240` gives; `test_schema.py` holds the two together at head.

Downgrade sets every bound back to NULL and drops the rule.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from dialect import AddedRule, DialectSQL

revision: str = "e59cee46d754"
down_revision: str | Sequence[str] | None = "8a7989a3fab0"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

#: The same text on both engines: it names no boolean and no SQLite function.
_RULE = "timeout_seconds IS NULL OR (timeout_seconds > 0 AND timeout_seconds <= 10.0)"

_ADDED: tuple[AddedRule, ...] = (
    AddedRule("catalogue_targets", "ck_catalogue_targets_timeout", sqlite=_RULE, postgresql=_RULE),
)

#: Each seeded row's bound in seconds on the day this ran. A row missing here
#: keeps NULL.
_SEEDS: dict[str, float] = {
    "k10plus": 6.0,
    "nkp": 3.0,
    "bne": 7.0,
    "nlg": 3.0,
    "libris": 3.0,
    "melinda": 3.0,
    "bibsys": 3.0,
    "porbase": 5.0,
    "oszk": 4.0,
    "kb_dk": 3.0,
    "bn_pl": 3.0,
    "oenb": 5.0,
    "bnf": 4.0,
    "loc": 4.0,
}

_TABLE = sa.table("catalogue_targets", sa.column("source"), sa.column("timeout_seconds"))


def upgrade() -> None:
    op.execute(
        _TABLE.update()
        .where(sa.not_(sa.and_(_TABLE.c.timeout_seconds > 0, _TABLE.c.timeout_seconds <= 10.0)))
        .values(timeout_seconds=None)
    )
    with op.batch_alter_table("catalogue_targets") as batch:
        for added in _ADDED:
            batch.create_check_constraint(
                added.constraint, DialectSQL(sqlite=added.sqlite, postgresql=added.postgresql)
            )
    for source, seconds in _SEEDS.items():
        row = _TABLE.c.source == op.inline_literal(source)
        op.execute(_TABLE.update().where(row).values(timeout_seconds=seconds))


def downgrade() -> None:
    op.execute(_TABLE.update().values(timeout_seconds=None))
    with op.batch_alter_table("catalogue_targets") as batch:
        for added in _ADDED:
            batch.drop_constraint(added.constraint, type_="check")
