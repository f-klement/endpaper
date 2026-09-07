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

## What this migration actually does

It widens `ck_catalogue_credentials_envelope` by one version. That is all of it.

**No row is decrypted here and no row is removed.** An earlier draft deleted
every envelope the new scheme could not open, which meant a household upgrading
lost every catalogue login it had stored. Owner's decision, 2026-09-07: that is
not an acceptable upgrade, and the reasoning that produced it took the wrong
half of a split.

**The split.** A roster catalogue's address is `targets.SEEDED[...].base_url`, a
module constant with no writer, so an envelope bound to the source alone cannot
be opened beside an address somebody else chose: nobody can choose one. A
household OPDS server's address is a row, which is the case that made the
binding necessary, and `backup.restore` already drops those credentials. So the
envelopes that exist in the field are exactly the ones that can be carried
forward safely, and the ones that could not be were never released.

**Re-sealing happens on the read path instead, not here.** `credentials.unseal`
opens a `v1` envelope at its own version and the caller re-seals it, so the old
scheme empties itself as logins are used and the key is already proven by the
open that just succeeded. A migration cannot prove that: a key may sit in an
environment variable, a keychain or a file, and a machine upgrading without one
would have lost the logins anyway. Re-sealing here would also have taken the
address **the row already names**, which is the laundering this design refuses.

**What ends the old scheme's acceptance is a guard rather than a date.** It is
safe only while a roster address is a module constant, so
`test_credentials.py` fails when the ticket that makes a catalogue row editable
lands. `credentials._UNBOUND_VERSION` carries the condition.

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
    # **This deletes nothing, and that is the point of it.** An earlier draft
    # removed every envelope written before the origin binding, which meant a
    # household upgrading lost every catalogue login it had stored. Owner's
    # decision, 2026-09-07: that is not an acceptable upgrade.
    #
    # Nothing has to be removed here because nothing has to be converted here.
    # `credentials.unseal` opens a `v1` envelope at its own version and the read
    # path re-seals it, so the old scheme empties itself as the logins are used,
    # with the key already proven by the open that just succeeded. A migration
    # cannot prove that: the key may be in an environment variable, a keychain
    # or a file, and a machine upgrading without it would have lost them anyway.
    #
    # So the whole upgrade is widening the constraint to admit both versions.
    _swap(_ENVELOPE_AFTER)


def downgrade() -> None:
    # **The downgrade still deletes, and it is not symmetric with the upgrade
    # above.** Going back narrows the constraint to `v1` only, and the copy a
    # batch rebuild performs is an INSERT that enforces it, so a `v2` row left
    # here fails the whole downgrade rather than being reported.
    #
    # The asymmetry is the direction of the loss. Upgrading must not cost a
    # household its logins, because it is the ordinary thing to do. Downgrading
    # to a build that cannot open a `v2` envelope costs the ones re-sealed since
    # the upgrade whatever this does, so deleting them is naming that rather
    # than leaving rows no build can read.
    op.execute(sa.text("DELETE FROM catalogue_credentials WHERE envelope GLOB 'v2.*'"))
    _swap(_ENVELOPE_BEFORE)
