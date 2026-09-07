"""A stored login is sealed against its origin as well as its source.

Revision ID: d9c1f47b2a06
Revises: c8b3e5017d4a
Create Date: 2026-09-07

`credentials.seal` passed the source alone as associated data, so an envelope
opened at whatever address the row beside it named. That was harmless while
every caller passed `targets.SEEDED[...].base_url`, a module constant with no
writer. `opds_servers.base_url` is a row, and `backup.restore` re-inserts
through Core, so an archive could keep a legitimate `opds-` key and change only
the address beside it: the next sync sent a household's sealed login to a host
the archive named. The attacker needed a copy of the archive and not the key,
which is the loss sealing was bought to prevent.

The envelope now carries the origin, so it is unopenable at an address it was
not sealed for **whichever writer moved the row**, rather than only through the
one route that was measured.

## What this migration actually does, and what it deliberately does not

It widens `ck_catalogue_credentials_envelope` by one version and deletes every
envelope the new scheme cannot open.

**No row is decrypted here, and that was the alternative.** Re-sealing an
existing envelope at migration time would need the key, which is a deployment
fact this file cannot depend on: a key may sit in an environment variable, a
keychain or a file, and a machine that has none upgrades exactly as one that
has. A migration whose behaviour depends on that is one that silently does
different things on two deployments. Worse, it would re-seal from **the address
the row already names**, so a deployment whose `opds_servers` row had already
been moved by a hostile archive would have this migration launder the move into
a valid binding. Re-sealing on first successful use was the third option and it
is the one that closes nothing: it needs the old scheme kept openable, which is
the hole.

## What an upgrading deployment sees, stated because it is a product decision

**Every login stored before this is invalidated and has to be typed again.**
The rows are removed here rather than left to be reported, and leaving them was
the first choice: a row that survives can say "this cannot be read, enter it
again" beside the name, where a row that is gone says nothing at all.

**What decided it was measuring what a person would actually be shown.** There
is no screen for a household's OPDS servers: `credential_unreadable` is
rendered in one place, the catalogue logins section, which lists roster sources
only. A household's invalidated login would therefore surface as a bare
`opds-<16 hex>` in the encryption key section with no name and no way to tell
which machine it was for. And the two sentences an admin reads for an
unreadable login both begin at the key, because for four of the five causes
that is where the remedy is; for this one the key is intact and the phrase
opens nothing. So a row left behind would be reported wrongly, and for a
household's server it would be reported anonymously.

Removed, every screen already renders the result correctly: the source has no
login, and entering one is the same action it would have been. The loss is
stated in the changelog and here, which is where a deployment goes to find out
what an upgrade did.

**`credentials.UnboundCredential` stays, because this is not the only way a
`v1` envelope arrives.** Restoring an archive taken before this upgrade brings
them back, and that path has to be legible: the refusal names the cause and is
separate from a rotated key and from a damaged row on purpose, since those
three have three different remedies and only this one is "type it again" with
nothing else to check.

## Why `v1` is still admitted by the constraint

An archive taken before this upgrade carries `v1` rows, and `backup.restore`
inserts them through Core. Refusing them at the insert would fail an entire
restore over logins whose only remedy is to be typed again, which is the failure
`models.CatalogueCredential`'s missing foreign key exists to avoid. So the shape
check admits both and `credentials.unseal` opens one. The two sets have names:
`credentials.KNOWN_VERSIONS` and `credentials.VERSION`.

## What the downgrade loses

Every login stored since this ran. The old constraint admits `v1` alone, and a
batch rebuild copies the rows through it, so a `v2` row would fail the copy and
take the whole downgrade with it. They are deleted first, deliberately and in
the open: there is no second copy, because the plaintext was never written
anywhere, which is the point of the table.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "d9c1f47b2a06"
down_revision: str | Sequence[str] | None = "c8b3e5017d4a"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

#: Shorter than any envelope this build can write, longer than any plaintext
#: worth defending against. Unchanged by the bump: `v2` is the same width as
#: `v1`. `f3a20d68c4b1` carries the arithmetic.
_MIN_ENVELOPE = 40

#: The shape check, spelled out rather than imported: a migration is frozen and
#: must not move when `credentials.KNOWN_VERSIONS` does. It is not a parser.
#: `credentials.unseal` is, and it refuses anything that is not exactly four
#: parts of a version it can open.
_ENVELOPE_BEFORE = f"envelope GLOB 'v1.*.*.*' AND length(envelope) >= {_MIN_ENVELOPE}"
_ENVELOPE_AFTER = (
    "(envelope GLOB 'v1.*.*.*' OR envelope GLOB 'v2.*.*.*') "
    f"AND length(envelope) >= {_MIN_ENVELOPE}"
)

_CONSTRAINT = "ck_catalogue_credentials_envelope"


def _swap(wanted: str) -> None:
    with op.batch_alter_table("catalogue_credentials") as batch:
        batch.drop_constraint(_CONSTRAINT, type_="check")
        batch.create_check_constraint(_CONSTRAINT, wanted)


def upgrade() -> None:
    # Before the rebuild, for the reason the downgrade gives: the copy a batch
    # rebuild performs is an INSERT and enforces whatever constraint is being
    # created. Here it would pass either way, and doing it in the same order
    # both directions is one rule rather than two.
    op.execute(sa.text("DELETE FROM catalogue_credentials WHERE envelope NOT GLOB 'v2.*'"))
    _swap(_ENVELOPE_AFTER)


def downgrade() -> None:
    # Before the rebuild, not after: the copy the batch performs is an INSERT
    # and enforces the narrowed constraint, so a `v2` row left here fails the
    # whole downgrade rather than being reported.
    op.execute(sa.text("DELETE FROM catalogue_credentials WHERE envelope GLOB 'v2.*'"))
    _swap(_ENVELOPE_BEFORE)
