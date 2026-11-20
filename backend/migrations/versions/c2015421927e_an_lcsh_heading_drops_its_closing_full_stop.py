"""An LCSH heading drops its closing full stop

Revision ID: c2015421927e
Revises: ae3dd7d65835
Create Date: 2026-11-20

An LCSH row's `number` is the heading string itself (`models.Classification`
says why), and `classifications.add_headings` deduplicates on the exact
`(book_id, scheme, number)`. A MARC upload used to store `650 $a` with only the
ISBD separators trimmed, so a DLC record left `Psychology, Industrial.` with
its closing full stop. The app now stores `Subfields.heading_label`'s form,
which drops it. Left alone, every such row gains a twin without the stop the
next time the same book is read, from the same file, from its own MARC export
or from a catalogue, and a heading filter on one form misses the books holding
the other.

So every `lcsh` number is rewritten into that form, and where a book then holds
two rows for one heading they become one: the lowest id survives, which is what
was stored first, and it takes a caption or a kind it lacked from the rows that
go, the rule `folding._absorb_heading` applies to a merge. Nothing references a
`classifications` row by id, so deleting the others loses only what was
absorbed. `sort_key` follows the number, because `lcsh` is a built in scheme
filed under the generic rule, which files a value as its own text, and both
the seed and `backup.restore` keep a built in row as seeded.

**The transform is copied here rather than imported**, for the reason
`f1c30ab27d84` gives: a revision describes the data as it was on the day it
ran. `tests/test_schema.py::TestAnLcshHeadingDropsItsClosingFullStop` holds
the copy to `Subfields.heading_label` today.

A number the transform would empty is left as it is: an empty heading is no
heading, and deleting a row for it is a decision this revision does not make.

**Every Book whose rows changed or merged gets one new `oai_datestamp`**, the
moment of this upgrade, and every other Book keeps its own. `oai.py` publishes
each heading's caption or number, and these writes are text SQL on the bare
connection, which neither door in `harvest.py` sees: without the stamp a
selective harvest would keep the stop form and the deleted twin until something
else touched the Book. The stamp is naive UTC to the second, as
`models.datestamp_now` writes it, computed here in Python for the freezing
reason above and never by `CURRENT_TIMESTAMP`, which is local time on a
Postgres session. A private Book's stamp moves too, which no harvester sees.

**Restoring an archive taken before this revision brings the stop forms
back**, and that is accepted. `backup.restore` recomputes only `sort_key`, so
such a library is where this revision found it, and the next MARC read of a
Book adds the twin. That is a duplicate row, not a refusal or a leak, and the
remedy, a second frozen copy of this merge inside the restore, costs more than
it saves.

Only DML, so no batch rebuild, and SQLite runs DML inside the transaction.
The downgrade does nothing: which rows carried a stop is not recorded, and a
heading without it is what a MARC upload writes either way.
"""

import re
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any, Final

import sqlalchemy as sa
from alembic import op

revision: str = "c2015421927e"
down_revision: str | Sequence[str] | None = "ae3dd7d65835"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

#: `marc_fields._TRAILING_PUNCTUATION` as it stood on the day this ran.
_TRAILING_PUNCTUATION: Final = re.compile(r"[\s.,;:/=]+$")

_BOOKS: Final = sa.table("books", sa.column("id", sa.Integer()), sa.column("oai_datestamp", sa.DateTime()))


def heading_label(number: str) -> str:
    """`number` in `Subfields.heading_label`'s form, as that read on this day."""
    return _TRAILING_PUNCTUATION.sub("", number.strip())


def _groups(rows: Sequence[Any]) -> dict[tuple[int, str], list[Any]]:
    """Every row whose number the transform changes or collides with, by the
    book and the heading it becomes, each group in id order."""
    groups: dict[tuple[int, str], list[Any]] = {}
    for row in rows:
        label = heading_label(row.number)
        if label:
            groups.setdefault((row.book_id, label), []).append(row)
    return {key: group for key, group in groups.items() if len(group) > 1 or group[0].number != key[1]}


def _survivor(group: list[Any], label: str) -> dict[str, Any]:
    """The first row, with the heading's form and what the others filled in."""
    first = group[0]
    caption = next((row.label for row in group if row.label is not None), None)
    kind = next((row.kind for row in group if row.kind is not None), None)
    return {"row_id": first.id, "number": label, "label": caption, "kind": kind}


def upgrade() -> None:
    connection = op.get_bind()
    rows = connection.execute(
        sa.text(
            "SELECT id, book_id, number, label, kind FROM classifications WHERE scheme = 'lcsh' ORDER BY id"
        )
    ).all()
    groups = _groups(rows)
    if not groups:
        return
    # The others go first: an update before them would meet the row it is
    # becoming in `uq_classifications_book_scheme_number`.
    others = [{"row_id": row.id} for group in groups.values() for row in group[1:]]
    if others:
        connection.execute(sa.text("DELETE FROM classifications WHERE id = :row_id"), others)
    connection.execute(
        sa.text(
            "UPDATE classifications SET number = :number, sort_key = :number, label = :label, kind = :kind "
            "WHERE id = :row_id"
        ),
        [_survivor(group, label) for (_, label), group in groups.items()],
    )
    _restamp(connection, {book_id for book_id, _ in groups})


def _restamp(connection: sa.Connection, book_ids: set[int]) -> None:
    """Move the datestamp of every Book in `book_ids`. The module docstring
    says why, and why the moment is computed here."""
    upgraded = datetime.now(UTC).replace(tzinfo=None, microsecond=0)
    connection.execute(
        _BOOKS.update().where(_BOOKS.c.id == sa.bindparam("book_id")).values(oai_datestamp=upgraded),
        [{"book_id": book_id} for book_id in sorted(book_ids)],
    )


def downgrade() -> None:
    """Nothing to undo. See the module docstring."""
