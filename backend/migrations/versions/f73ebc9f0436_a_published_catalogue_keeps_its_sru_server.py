"""A catalogue published before the SRU switch existed keeps its SRU server.

Revision ID: f73ebc9f0436
Revises: e59cee46d754
Create Date: 2026-11-19

`sru_server_enabled` defaults off, so a fresh install serves no SRU until an
admin says so. SRU shipped in v0.13.0 behind the publish state alone, and no
row for the switch existed before it did, so without this a deployment
answering on `/sru` today would read the default after the upgrade and go dark
with nobody told. The owner's decision on issue #178: a deployment whose
catalogue is published today keeps answering.

**Published means both rows, library mode and the publish switch**, because
that is what `settings_store.public_catalogue_is_published` reads and what the
public gate in front of `/sru` asks. A publish row left on while library mode
is off served nothing before this, so it is not switched on here either.

**Truthy is read as `settings_store` reads it**: stripped, lowercased, one of
`_TRUE_VALUES`, decided in Python rather than in SQL. A literal `= 'true'`
would read a row stored as `1` published in the app and unpublished here, and
SQL's `TRIM` strips spaces alone where `str.strip` strips every whitespace.
The set is written out rather than imported, for the reason `c1f8a7e3d240`
gives; `test_schema.py` holds the two together at head.

**A row that already exists is left as it is**, whatever it holds: it is an
admin's answer, and this revision only fills the silence the default would
otherwise fill.

Downgrade deletes the switch's row where it holds exactly `true`, which is the
only row the upgrade writes. An admin's `true` written after the upgrade looks
the same and goes too; the default it falls back to is off, the narrower
direction.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "f73ebc9f0436"
down_revision: str | Sequence[str] | None = "e59cee46d754"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

#: `settings_store._TRUE_VALUES` on the day this ran.
_TRUE_VALUES: frozenset[str] = frozenset({"true", "1", "yes", "on"})

_SWITCH = "sru_server_enabled"

#: The two rows `settings_store.public_catalogue_is_published` reads.
_PUBLISHED_BY = ("library_mode", "public_catalogue_enabled")

_TABLE = sa.table("settings", sa.column("key"), sa.column("value"))


def _is_true(value: str | None) -> bool:
    """`settings_store.get_bool` over one row; a missing or NULL row reads its
    default, which is off for all three keys this revision reads."""
    return value is not None and value.strip().lower() in _TRUE_VALUES


def upgrade() -> None:
    rows = dict(
        op.get_bind()
        .execute(sa.select(_TABLE.c.key, _TABLE.c.value).where(_TABLE.c.key.in_((_SWITCH, *_PUBLISHED_BY))))
        .tuples()
        .all()
    )
    if _SWITCH in rows or not all(_is_true(rows.get(key)) for key in _PUBLISHED_BY):
        return
    op.execute(_TABLE.insert().values(key=op.inline_literal(_SWITCH), value=op.inline_literal("true")))


def downgrade() -> None:
    op.execute(
        _TABLE.delete().where(
            sa.and_(_TABLE.c.key == op.inline_literal(_SWITCH), _TABLE.c.value == op.inline_literal("true"))
        )
    )
