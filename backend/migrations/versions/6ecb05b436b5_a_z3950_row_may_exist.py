"""A Z39.50 row may exist: widen the transport, couple the address to it, name the charset.

Revision ID: 6ecb05b436b5
Revises: d7fa3b5c1e49
Create Date: 2026-11-16

`b7d4e6f01a95` refused `z3950` in `ck_catalogue_targets_transport` because no
door served it. `metadata._DOORS` now holds one per transport, so this widens
the list to every member and the model derives it from `enums.Transport` rather
than spelling it out.

**The address follows the transport.** A Z39.50 row's `base_url` is
`z3950://host:port/database`, which `ck_catalogue_targets_base_url` refused as a
scheme it did not know. It now admits `z3950://` on a Z39.50 row and only there,
so a restore cannot point an SRU row at a Z39.50 port or the reverse. Every
other arm of that rule is unchanged.

**`record_charset` is new**: the character set a Z39.50 target's records arrive
in, which the client converts from. Required on a Z39.50 row and NULL on every
other, which its rule couples to the transport as the address rule does; every
row this revision finds is SRU or bespoke, so nothing is backfilled.

**What this does to existing rows: nothing.** Every seeded row is `sru` or
`bespoke` with an `http` or `https` address, which both new rules admit as the
old ones did.

Downgrade deletes any Z39.50 row first, because narrowing a CHECK under a row
that violates it fails on Postgres and is accepted on SQLite, and then puts the
two rules back and drops the column.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from dialect import AddedRule, DialectSQL, SwappedRule

revision: str = "6ecb05b436b5"
down_revision: str | Sequence[str] | None = "d7fa3b5c1e49"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

#: The two rules this revision rewrites. Written out rather than imported from
#: `models` or `enums`, for the reason every revision here gives: a migration
#: describes the schema at one moment and must not change meaning when an enum
#: grows.
_SWAPPED: tuple[SwappedRule, ...] = (
    SwappedRule(
        "catalogue_targets",
        "ck_catalogue_targets_transport",
        "transport IN ('sru', 'bespoke')",
        "transport IN ('sru', 'bespoke')",
        "transport IN ('sru', 'z3950', 'bespoke')",
        "transport IN ('sru', 'z3950', 'bespoke')",
    ),
    SwappedRule(
        "catalogue_targets",
        "ck_catalogue_targets_base_url",
        "(base_url GLOB 'http://?*' OR base_url GLOB 'https://?*') "
        "AND instr(base_url, char(0)) = 0 "
        "AND length(base_url) <= 255 "
        "AND length(CAST(base_url AS BLOB)) <= 1020",
        "(base_url ~ '^http://.' OR base_url ~ '^https://.') "
        "AND length(base_url) <= 255 "
        "AND octet_length(base_url) <= 1020",
        "(CASE WHEN transport = 'z3950' THEN base_url GLOB 'z3950://?*' "
        "ELSE (base_url GLOB 'http://?*' OR base_url GLOB 'https://?*') END) "
        "AND instr(base_url, char(0)) = 0 "
        "AND length(base_url) <= 255 "
        "AND length(CAST(base_url AS BLOB)) <= 1020",
        "(CASE WHEN transport = 'z3950' THEN base_url ~ '^z3950://.' "
        "ELSE (base_url ~ '^http://.' OR base_url ~ '^https://.') END) "
        "AND length(base_url) <= 255 "
        "AND octet_length(base_url) <= 1020",
    ),
)

#: The rule the new column carries, on both engines alike.
_ADDED: tuple[AddedRule, ...] = (
    AddedRule(
        "catalogue_targets",
        "ck_catalogue_targets_record_charset",
        "CASE WHEN transport = 'z3950' THEN record_charset IS NOT NULL AND "
        "record_charset IN ('utf8', 'marc8', 'iso5426') ELSE record_charset IS NULL END",
        "CASE WHEN transport = 'z3950' THEN record_charset IS NOT NULL AND "
        "record_charset IN ('utf8', 'marc8', 'iso5426') ELSE record_charset IS NULL END",
    ),
)


def upgrade() -> None:
    # One batch, so SQLite rebuilds the table once. Batch mode reflects every
    # other rule and index, for the reason `d5e1b93a7c62` records.
    with op.batch_alter_table("catalogue_targets") as batch:
        batch.add_column(sa.Column("record_charset", sa.String(16), nullable=True))
        for rule in _SWAPPED:
            batch.drop_constraint(rule.constraint, type_="check")
            after = DialectSQL(sqlite=rule.after, postgresql=rule.after_pg)
            batch.create_check_constraint(rule.constraint, after)
        for added in _ADDED:
            batch.create_check_constraint(
                added.constraint, DialectSQL(sqlite=added.sqlite, postgresql=added.postgresql)
            )


def downgrade() -> None:
    op.execute(sa.text("DELETE FROM catalogue_targets WHERE transport = 'z3950'"))
    with op.batch_alter_table("catalogue_targets") as batch:
        for added in _ADDED:
            batch.drop_constraint(added.constraint, type_="check")
        for rule in _SWAPPED:
            batch.drop_constraint(rule.constraint, type_="check")
            before = DialectSQL(sqlite=rule.before, postgresql=rule.before_pg)
            batch.create_check_constraint(rule.constraint, before)
        batch.drop_column("record_charset")
