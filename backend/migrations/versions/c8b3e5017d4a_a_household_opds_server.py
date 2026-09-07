"""A household's own OPDS server, as a table of its own.

Revision ID: c8b3e5017d4a
Revises: e4f7a2c81b09
Create Date: 2026-09-07

A member's Calibre-Web, Komga, Kavita or Ubooquity, so that what they hold there
can be read into this catalogue. Holdings only: a title, an author, and the fact
that somebody owns the book.

## Why this is not a row in `catalogue_targets`, which is the question this
migration exists to answer

**That table's primary key is a closed enum, and the key space is the reason
rather than the width.** `catalogue_targets.source` holds a `CatalogueSource`
value, `sources.Plan.parse` validates a stored settings row against that enum,
and every door onto the ISBN lookup path is keyed on it. A household's own
server placed in that key space is one member's private holdings able to be
selected as a source answering another member's ISBN scan, which is precisely
what `enums.SourceFamily` exists to refuse and what
`tests/test_decoders.py::TestTwoFamiliesMeanTwoRegistries` enforces.

Widening `ck_catalogue_targets_transport` was the alternative and it is the
smaller half of the work: the constraint is a batch rebuild under
`render_as_batch=True`, which this project sets because SQLite cannot ALTER one.
What it does not do is make the row belong there. `main.seed_catalogue_targets`
reconciles every seeded row against `targets.SEEDED` on each start and would
need a second rule to skip these, and of that table's twenty two columns a
server here fills one: no query grammar, no record schema, no index name, no
search cap, no reader choice.

**The credential side needed no decision at all**, which is the evidence that
this split is the shape already intended. `catalogue_credentials.source` was
deliberately not keyed to the enum so that "a row added by a curated registry,
or a typed host, gets a credential with no migration", and this is that row
arriving.

## The three constraints, and which one is not obvious

`name` and `base_url` are shape checks: a row with an empty name is unusable on
a screen, and a `base_url` that is not http or https is an address
`opds.is_fetchable` would refuse anyway. The scheme check is the last line for a
write that never came through the route, which is what a restore is.

**`credential_key` is the one that matters.** Its value becomes
`catalogue_credentials.source`, and that column travels: the settings screen is
sent the source of any login it cannot open so that somebody can remove it, and
a generated client interpolates it into a URL path. There is no foreign key in
either direction, `backup.restore` inserts through Core, and an archive is a
file somebody was handed. So this carries `ck_catalogue_credentials_source`'s
rule verbatim, NUL clause included: SQLite's `length` and `GLOB` are C string
operations and stop at the first NUL, so without it the constraint reads
`opds-1<NUL>../../books/5?` as `opds-1` and admits what the Python rule refuses.

**Unique, and generated at random rather than from the row id.** SQLite reuses
`max(rowid) + 1` after a delete unless the column is declared `AUTOINCREMENT`,
so a key derived from the id would hand a newly added server the sealed login of
the one that used to have that id, and `credentials.for_request` binds a
credential to the address it is **asked** about: it would be sent to the new
host. See `models.new_opds_credential_key`.

## What the downgrade loses

The configured servers, and nothing else. A sealed login for one of them stays
in `catalogue_credentials` as an orphan, which is a row a settings screen can
already show and delete: that table has no foreign key on purpose, and the
delete path deliberately does not check the roster so that an orphan can be
removed rather than needing a database edit.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "c8b3e5017d4a"
down_revision: str | Sequence[str] | None = "e4f7a2c81b09"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

#: Matches `catalogue_credentials.source` in width, because it becomes one.
_KEY_WIDTH = 32

#: `ck_catalogue_credentials_source`'s rule over this column's name, plus the
#: prefix. Spelled out rather than imported: a migration is frozen and must not
#: move when a constant does.
#:
#: **The prefix clause is what keeps this column out of the other key space.**
#: `catalogue_credentials.source` holds a `CatalogueSource` value for a roster
#: row and this value for a household's server, and `credentials.stored` is
#: keyed on the source alone. Without this an archive could name `bne` here
#: beside an address of its own, and the next sync would send the library's
#: sealed login for the Spanish national library to that address: the plaintext
#: reaching a host the archive chose, from an archive that carries no key.
_SAFE_KEY = (
    "length(credential_key) BETWEEN 1 AND 32 "
    "AND instr(credential_key, char(0)) = 0 "
    "AND credential_key NOT GLOB '*[^a-z0-9_-]*' "
    "AND credential_key GLOB 'opds-*'"
)

#: `?*` rather than `*`, so `http://` on its own is refused along with
#: `file:///etc/passwd`. GLOB's `?` is exactly one character.
_HTTP_SCHEME = "base_url GLOB 'http://?*' OR base_url GLOB 'https://?*'"


def upgrade() -> None:
    op.create_table(
        "opds_servers",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("base_url", sa.String(length=255), nullable=False),
        sa.Column("credential_key", sa.String(length=_KEY_WIDTH), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_opds_servers"),
        sa.UniqueConstraint("credential_key", name="uq_opds_servers_credential_key"),
        sa.CheckConstraint("length(name) BETWEEN 1 AND 100", name="ck_opds_servers_name"),
        sa.CheckConstraint(_SAFE_KEY, name="ck_opds_servers_credential_key"),
        sa.CheckConstraint(_HTTP_SCHEME, name="ck_opds_servers_base_url"),
    )


def downgrade() -> None:
    op.drop_table("opds_servers")
