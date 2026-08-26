"""Collection names fold outside ASCII, and pairs that already exist are merged.

Revision ID: e7b3d02a5c94
Revises: b7d41f0a2c95
Create Date: 2026-08-26

`uq_collections_name_nocase` was a functional index on `lower(name)`. SQLite's
`lower()` folds the 26 ASCII letters and nothing else, so the promise the index
exists to make, one shelf per name, held for `Fiction` and `fiction` and not for
`Ästhetik` and `ästhetik`. `COLLATE NOCASE` is the same 26 letters in different
words: measured, `'Ästhetik' = 'ästhetik' COLLATE NOCASE` is 0. A Unicode aware
`lower()` needs the ICU extension, which this image does not build.

So the fold moves to Python, into a stored `collections.name_folded`, and the
unique index moves onto that column.

**This migration merges rows in a live library, which nothing else here does.**
A database that already holds `Ästhetik` and `ästhetik` cannot have both under
the new index, and an upgrade has no caller to answer 409 to.
`rename_collection` refuses a merge because a person typing a name has not asked
for two shelves to become one; here there is nobody to ask and no other
resolution, so the pair is merged once, into the lower id, and the move is
logged at WARNING naming both spellings. Lower id wins because that is how
`_first_wins` in `importing.py` and `create_tag` in `routers/books.py` break the
same tie, and two folding rules that disagree about the winner is the defect
`docs/decisions.md` already records.

**The order below is the whole trap, and it is not the obvious one.** A
migration connection reports `PRAGMA foreign_keys` = 0: the
`PRAGMA foreign_keys=ON` listener lives on `database.engine` and Alembic builds
its own engine in `migrations/env.py`. So `books.collection_id`'s
`ON DELETE SET NULL` does **not** fire here. A book missed by the repoint is not
unfiled, it keeps a **dangling** id, and because the survivor is the lower id the
row deleted is the higher, which is the rowid SQLite hands to the next insert:
the book then reads as being in an unrelated collection created later.
`d4a91f3c72e8` records the identical trap for tags. Hence: repoint first, delete
second, and check that nothing dangles, because nothing else in the stack will
complain.

**A failed revision may not roll back cleanly here, and where the checks sit is
what works around that.** Alembic's SQLite implementation sets
`transactional_ddl = False`, so `context.begin_transaction()` in
`migrations/env.py` is a no-op context manager and nothing wraps the revision.
What is left is pysqlite's own behaviour, and it is conditional: pysqlite opens
a transaction for **DML only**. DDL executed while no transaction is open is
durable the moment it runs; DDL executed after any DML joins that transaction
and rolls back with it.

Both cases live in this file, and which one applies depends on the database.
`op.add_column` below is the first statement **only where there is no pair to
merge**; there it is durable on its own, which is the case measured on a
database made to fail this revision on purpose: the `ADD COLUMN` had landed,
the backfill had not, and `alembic_version` still named the previous revision,
a schema no rerun can apply twice. Where a merge did run, the repoint and the
delete have already opened the transaction, so `add_column` joins them and
rolls back with them. The `drop_index`, the batch rebuild and the
`create_index` follow the backfill `UPDATE` in every case, so those three
always roll back.

The rule to carry forward is therefore not "DDL is never transactional" but
"**some** DDL is durable", which is enough: a check placed after any of it can
leave a half-applied database.

So both dangling checks run **before the first DDL statement**. A database that
arrives already carrying a dangling id, which is the only way one can realistically
be here, is refused with the file untouched. The check after the upgrade is the
one the issue asks for and is an invariant rather than a gate: by then nothing
has touched `books.collection_id` or `collections.id` since the check that
passed, so it can only fire on a defect in this file.

The steps around the merge are ordered to keep the SQLite table rebuild away
from anything it could drop. The old index is functional, and reflection loses
those, so it goes before the rebuild rather than through it: measured on this
database, reflecting `collections` warns "Skipped unsupported reflection of
expression-based index uq_collections_name_nocase" and returns without it. The
new unique index is created after the rebuild, so nothing can drop it and so
that a merge which somehow left a duplicate fails here rather than shipping one.

**The downgrade cannot un-merge.** It restores the schema, not the data: two
shelves that were combined stay combined, because the losing rows and the names
on them are gone. Said rather than pretended.
"""

import logging
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "e7b3d02a5c94"
down_revision: str | Sequence[str] | None = "b7d41f0a2c95"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# `endpaper.schema`, the logger `schema.py` already writes "Database schema at X"
# to, so a merge and the upgrade that performed it read as one story. It is
# visible on both paths: at startup the app's own handlers are installed on the
# `endpaper` namespace, and from the `alembic` CLI `alembic.ini` gives the root
# logger a console handler at WARNING, which this reaches by propagation.
logger = logging.getLogger("endpaper.schema")

#: Twice `COLLECTION_NAME_MAX`. Exactly one code point in Unicode grows under
#: `str.lower()`, U+0130, which folds to two, so twice the name's bound is the
#: worst case. Written as a literal rather than imported from `models`: a
#: migration describes the schema as it was on the day it ran, and importing
#: today's constant would make it describe today's.
_KEY_MAX = 160


def _refuse_if_books_dangle(connection: sa.Connection, when: str) -> None:
    """Stop the upgrade if any book points at a collection that is not there.

    A hard failure rather than a repair, and rather than a warning. Nulling the
    column would unfile books this revision exists to keep filed, and carrying
    on would file them under whatever collection later takes the freed rowid,
    which is the worse of the two and the one nobody can see.
    """
    dangling = int(
        connection.execute(
            sa.text(
                "SELECT COUNT(*) FROM books WHERE collection_id IS NOT NULL "
                "AND collection_id NOT IN (SELECT id FROM collections)"
            )
        ).scalar_one()
    )
    if dangling:
        raise RuntimeError(
            f"{dangling} book(s) point at a collection that does not exist "
            f"({when}). Revision e7b3d02a5c94 has been stopped and nothing was "
            "changed. Repair those rows and upgrade again."
        )


def upgrade() -> None:
    connection = op.get_bind()

    # Before any DDL, on purpose: see the module docstring. A dangling id here
    # predates this revision, because `delete_collection`, the ORM and
    # `ON DELETE SET NULL` under `PRAGMA foreign_keys=ON` each prevent the app
    # from writing one, so the row was put there by hand and refusing is the
    # right answer. Refusing at this point costs the library nothing: not a
    # statement has run.
    _refuse_if_books_dangle(connection, "before")

    # The merge, and it is DML only. Everything that changes the schema comes
    # after it, so a failure in here rolls back and leaves the database exactly
    # as it was found.
    #
    # Read into Python and group there. The grouping cannot be done in SQL:
    # SQLite's `lower()` is exactly the function that does not work here, so a
    # `GROUP BY lower(name)` would find none of the pairs this migration exists
    # for and merge nothing, silently.
    rows = connection.execute(sa.text("SELECT id, name FROM collections ORDER BY id")).all()

    grouped: dict[str, list[tuple[int, str]]] = {}
    for row_id, name in rows:
        grouped.setdefault(name.lower(), []).append((row_id, name))

    repoint = sa.text(
        "UPDATE books SET collection_id = :keeper WHERE collection_id IN :losers"
    ).bindparams(sa.bindparam("losers", expanding=True))
    remove = sa.text("DELETE FROM collections WHERE id IN :losers").bindparams(
        sa.bindparam("losers", expanding=True)
    )

    for members in grouped.values():
        if len(members) == 1:
            continue
        (keeper_id, keeper_name), *losers = members
        loser_ids = [row_id for row_id, _name in losers]

        # Repoint first, delete second. The other order is the trap the module
        # docstring describes and it leaves no trace when it fires.
        moved = connection.execute(
            repoint, {"keeper": keeper_id, "losers": loser_ids}
        ).rowcount
        connection.execute(remove, {"losers": loser_ids})

        logger.warning(
            "Merged %d collection(s) into %r (id %d) because the names differ only "
            "in case: %s. %d book(s) moved.",
            len(losers),
            keeper_name,
            keeper_id,
            ", ".join(repr(name) for _row_id, name in losers),
            moved,
        )

    _refuse_if_books_dangle(connection, "after the merge")

    op.add_column(
        "collections",
        sa.Column("name_folded", sa.String(length=_KEY_MAX), nullable=True),
    )

    survivors = [
        {"row_id": members[0][0], "folded": members[0][1].lower()}
        for members in grouped.values()
    ]
    if survivors:
        connection.execute(
            sa.text("UPDATE collections SET name_folded = :folded WHERE id = :row_id"),
            survivors,
        )

    # Before the rebuild below, not after. It is an index on an expression, and
    # batch mode rebuilds a table by reflecting it: a functional index is the
    # kind of thing that reflection loses.
    op.drop_index("uq_collections_name_nocase", table_name="collections")

    # SQLite cannot ALTER a column to NOT NULL, so this rebuilds the table.
    # `render_as_batch=True` in `migrations/env.py` is what makes it do so.
    with op.batch_alter_table("collections") as batch:
        batch.alter_column(
            "name_folded",
            existing_type=sa.String(length=_KEY_MAX),
            nullable=False,
        )

    op.create_index(
        "uq_collections_name_folded", "collections", ["name_folded"], unique=True
    )

    # The assertion the issue asks for, held here as an invariant. The rebuild
    # above copies `collections` row for row, ids included, and nothing since
    # the check that passed has written `books.collection_id`, so this cannot
    # fire unless something in this file is wrong.
    _refuse_if_books_dangle(connection, "after the upgrade")


def downgrade() -> None:
    op.drop_index("uq_collections_name_folded", table_name="collections")

    with op.batch_alter_table("collections") as batch:
        batch.drop_column("name_folded")

    # Safe to recreate: Python's `.lower()` folds every ASCII pair SQLite's does
    # and more, so rows the upgrade left distinct are distinct here too.
    op.create_index(
        "uq_collections_name_nocase",
        "collections",
        [sa.text("lower(name)")],
        unique=True,
    )
