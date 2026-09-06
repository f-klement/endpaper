"""A catalogue credential, sealed at rest, in a table of its own.

Revision ID: f3a20d68c4b1
Revises: a1e7c93b60df
Create Date: 2026-09-06

A login at one catalogue's server, held on an institution's behalf. **Not a
settings row**, and the reason is not tidiness: every secret `settings` holds is
this deployment's own, that table is written in plaintext, and `backup.py`
copies it wholesale, so a credential of this kind put there would sit unmasked
in every archive an admin can download. Here the column holds ciphertext, the
key is never in the database, and the archive therefore carries something
useless without a key it does not contain.

**Two columns, and the username is inside the second one.** It is half of a
login at somebody else's server, so storing it beside the ciphertext would leave
the readable half in every archive to protect the other. What a screen shows is
a mask, which costs one decryption on a page an admin opens by hand.

**`source` is the target row's identity, not the `CatalogueSource` enum**, though
every row is one today. Keying on the closed enum would let the storage shape
decide which rows may carry a credential, which is exactly the tangle #180
reversed an earlier decision to undo: where a secret is stored had been quietly
deciding who may add a source. A row from the curated registry, or a typed host,
gets a credential here with no second migration.

**No foreign key into `catalogue_targets`, deliberately.** `backup.restore`
deletes and reinserts whole tables through Core, so a constraint here would let
one credential for a source a later release dropped fail an entire restore, over
a row nobody can see. A credential whose target is gone has to be an orphan a
screen can show and delete. The write path validates the source against the
roster instead, which is where the question can be answered rather than
enforced.

**The CHECK is what stands between a hand-edited archive and a plaintext
password being sent to a catalogue.** `b8e2f4c7a913` records the general form of
this: an archive decides a column's value, so a column whose values are closed
gets a constraint. Here the shape is the closed thing.

**A shape check and not a parser, and the docstring says only what the SQL
does.** `GLOB 'v1.*.*.*'` requires the `v1.` prefix and at least three
separators; it does not count the parts, because `*` matches a dot as happily as
anything else. What it buys is that a plaintext password written into this
column by a hand-edited archive is rejected at the insert rather than sent to a
catalogue. `credentials.unseal` is the parser, and it refuses anything that is
not exactly four parts.

The length floor is arithmetic rather than taste, and there are two floors.
A 12 byte nonce is 16 base64url characters and a 16 byte GCM tag is 22; `v1`,
the eight character generation tag and the three separators are 13 more. So the
shortest envelope `credentials.seal` can produce is **51** characters, over an
empty secret. The shortest any route can store is **55**, because a credential
needs a username and a password of at least one character each. The constraint
is written against the first, which is the weaker claim and the one that stays
true if a caller ever seals something shorter. 40 is below both and far above
any password somebody might paste in by hand.

**Why a constraint here does not contradict the missing foreign key above is
`models.CatalogueCredential`'s to say**, and `docs/decisions.md` carries it at
length. It is not repeated here: a migration is frozen, and nobody opens one
when they are tempted to add the foreign key.

## What the downgrade loses, stated rather than hidden

Every stored credential. There is no second copy: the plaintext was never
written anywhere, which is the whole point. A deployment that downgrades types
them in again, exactly as one that lost its key does.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "f3a20d68c4b1"
down_revision: str | Sequence[str] | None = "a1e7c93b60df"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

#: Matches `catalogue_targets.source`, because it names the same thing.
_SOURCE_WIDTH = 32

#: What a source may contain, and the reason it is narrower than the type.
#:
#: **This column travels**, which no other primary key here does: the settings
#: screen is sent the sources of any login it cannot open, so that a person can
#: remove one, and a client puts that value in a URL path. With no foreign key
#: and a restore inserting through Core, an archive decides it, and an archive
#: is a file somebody was handed. A source of `../../books/5?` steered an
#: admin's own authenticated DELETE at `/api/books/5`.
#:
#: The same rule lives in `credentials.is_safe_source`, which is what gives a
#: restore a 400 rather than the 500 a bare `IntegrityError` produces;
#: `tests/test_credentials.py::TestTheSourceRuleAndItsConstraintAgree` walks
#: both over one battery so they cannot drift.
#: **The NUL clause is the one that is not obvious.** SQLite's `length` and
#: `GLOB` are both C string operations and stop at the first NUL byte, so
#: without it this reads `bne\0../../books/5?` as `bne` and admits it, while
#: Python's `fullmatch` refuses it. Two spellings of one rule agreeing on every
#: printable input and parting on a control character is exactly the drift the
#: differential test exists to catch, and the battery that missed it carried no
#: control character at all. `length(CAST(source AS BLOB))` looks like the
#: tidier repair and is worse: measured, it stops rejecting a leading NUL.
_SAFE_SOURCE = (
    "length(source) BETWEEN 1 AND 32 AND instr(source, char(0)) = 0 AND source NOT GLOB '*[^a-z0-9_-]*'"
)

#: Shorter than any envelope this build can write, longer than any plaintext
#: worth defending against. A 12 byte nonce and a 16 byte tag are 38 base64url
#: characters between them before a single byte of secret, and `v1`, the
#: generation tag and the three separators add 13 more, for 51.
_MIN_ENVELOPE = 40


def upgrade() -> None:
    op.create_table(
        "catalogue_credentials",
        sa.Column("source", sa.String(length=_SOURCE_WIDTH), nullable=False),
        sa.Column("envelope", sa.Text(), nullable=False),
        sa.PrimaryKeyConstraint("source", name="pk_catalogue_credentials"),
        sa.CheckConstraint(
            f"envelope GLOB 'v1.*.*.*' AND length(envelope) >= {_MIN_ENVELOPE}",
            name="ck_catalogue_credentials_envelope",
        ),
        sa.CheckConstraint(
            _SAFE_SOURCE,
            name="ck_catalogue_credentials_source",
        ),
    )


def downgrade() -> None:
    op.drop_table("catalogue_credentials")
