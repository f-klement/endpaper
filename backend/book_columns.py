"""What each column of `books` is about, for every writer that needs a set of them.

Four writers used to answer this each in their own tuple: the merge's absorb, the
copy route, Google enrichment and the MARC importer. Nothing related any of the
four to `Book`, so a column added to the schema joined none of them and no
diagnostic said so. Completeness held by accident of nullability and by nobody
noticing.

**A partition, not a list of disciplines.** The six sets below are disjoint and
their union is every column of `books`, checked against the mapper at import. What
each writer then does with a set stays at that writer: fill only, overwrite on
request, refuse. Those rules differ per writer and there is no enum over them.

**No default, and that is the whole point.** A partition with a default side
fails open: a column nobody classified is silently granted whatever that side
grants. Four separate tuples failed closed instead, but only by accident, since
a column in nobody's list was written by nobody. So a column classified nowhere
stops every run until somebody classifies it, which is what `folding.TRANSFERS`
already does for a new child of `books`.
"""

from collections import Counter
from collections.abc import Iterable, Sequence
from itertools import chain
from typing import Final

from models import Book

# ── The partition ─────────────────────────────────────────────────────────────

#: The two work facts that name the book, and that a merge never fills from a
#: losing row: neither is in `FILLABLE_FROM_ANOTHER_ROW`.
#:
#: `isbn` is unique (`uq_books_isbn_single_copy`), so absorbing it is not an
#: ordinary gap fill: the row it is taken from has to let go first, in its own
#: flush, which is why `folding.fold` carries it by hand ahead of everything
#: rather than through the loop, and why the MARC importer writes it only on the
#: create path. `title` is the column the shelf recognises a book by, it is not
#: nullable so there is no gap to fill, and an outside catalogue's spelling of it
#: is often not this library's.
WORK_IDENTITY: Final[tuple[str, ...]] = ("isbn", "title")

#: The descriptive facts about the work, which every copy of it shares and which
#: another row or an outside record may fill in where this row has nothing.
#:
#: Every gap filler reaches it: `google_books.merge_into` walks it,
#: `importing._MARC_GAP_FIELDS` narrows it to what a MARC record carries, and
#: `folding._absorb_fields` walks `FILLABLE_FROM_ANOTHER_ROW`, which contains it.
#:
#: **Every name here is also a `schemas.BookMatch` field**, because `merge_into`
#: reads each off the match by name: a column added here that a catalogue cannot
#: assert raises `AttributeError` on the first enrichment. That is loud and it is
#: caught in the suite rather than in production, by
#: `tests/test_google_books.py::TestTheSignatureIsTheBound`, which partitions
#: `BookMatch`'s own fields against the names this loop walks. A work fact no
#: catalogue can assert belongs in `WORK_IDENTITY` or in a cell of its own.
WORK_DETAIL: Final[tuple[str, ...]] = (
    "subtitle", "author", "publisher", "year", "description",
    "page_count", "language", "categories", "google_books_id",
    "series_name", "series_index",
)

#: The one work fact whose value names a file rather than being one.
#:
#: Separate from `WORK_DETAIL` because copying the value is not copying the
#: thing. A cover this app holds is a file named by book id, so a second row
#: pointing at the first one's file makes purging either blank the other:
#: `routers/books.add_copy` calls `covers.duplicate` after the insert rather than
#: carrying the column, and `google_books.merge_into` writes it below its loop
#: under a precedence a member's upload wins.
WORK_COVER: Final[tuple[str, ...]] = ("cover_url",)

#: What this physical object is, where it is and what it cost.
#:
#: Exactly what `schemas.CopyCreate` asks a member for, because these are the
#: facts only somebody holding the object knows. An outside catalogue asserts
#: none of them: a stranger's record says nothing about which shelf this copy
#: sits on. Another row of the same book may fill them, which is why a merge
#: carries them.
COPY_DETAIL: Final[tuple[str, ...]] = (
    "location", "collection_id", "format", "condition", "lending",
    "purchase_price_minor", "purchase_currency", "purchased_at", "purchase_source",
)

#: What this row claims about the library's relation to the object, asserted by
#: the act that created the row and never filled from a losing row by a merge:
#: neither is in `FILLABLE_FROM_ANOTHER_ROW`. A **copy** does inherit
#: `copy_group` from the book it copies, which is what puts the two rows in one
#: group; a merge is the direction that is refused.
#:
#: `copy_group` is minted by `POST /api/books/{id}/copies` and by nothing else;
#: absorbing a losing row's group would make the survivor a copy of that row's
#: siblings, which its owner never agreed to. `ownership` is asserted by whoever
#: added the row, OWNED for a copy somebody is holding and UNKNOWN for a record
#: another institution exported, and `POST /api/books/bulk` with `SET_OWNERSHIP`
#: is where it is confirmed afterwards.
COPY_STANDING: Final[tuple[str, ...]] = ("copy_group", "ownership")

#: Facts about the row rather than about the book, written by the database or by
#: the act of filing, and never filled from a losing row by a merge: none is in
#: `FILLABLE_FROM_ANOTHER_ROW`. A **copy** inherits `is_private` at the insert,
#: deliberately; a merge is the direction that is refused.
#:
#: `id` and `added_at` are the database's. `added_by_user_id` attributes the row
#: to whoever created it, so absorbing one would reattribute it. `deleted_at` is
#: the trash marker `Shelf` reads. `is_private` is the privacy rule's own column,
#: and a copy inherits it because a copy of a private book that came back public
#: would disclose the book.
ROW_KEEPING: Final[tuple[str, ...]] = (
    "id", "added_at", "added_by_user_id", "deleted_at", "is_private",
)

PARTITION: Final[tuple[tuple[str, ...], ...]] = (
    WORK_IDENTITY,
    WORK_DETAIL,
    WORK_COVER,
    COPY_DETAIL,
    COPY_STANDING,
    ROW_KEEPING,
)

# ── The doors ─────────────────────────────────────────────────────────────────

#: Every fact about the work that lives in a column of its own, which is what a
#: new copy takes from the book it copies.
#:
#: `WORK_COVER` is absent: see there.
WORK_FACTS: Final[tuple[str, ...]] = WORK_IDENTITY + WORK_DETAIL

#: Every column a merge may take off a losing row of the same book.
#:
#: Each of the three cells is here for its own reason and the exclusions are the
#: statement: the identifying facts cannot be gap filled, and what the row claims
#: about the library is not the loser's to hand over.
FILLABLE_FROM_ANOTHER_ROW: Final[tuple[str, ...]] = WORK_DETAIL + WORK_COVER + COPY_DETAIL

# ── The refusal ───────────────────────────────────────────────────────────────


def _misfiled(cells: Iterable[Sequence[str]], columns: Iterable[str]) -> set[str]:
    """Every name not classified exactly once against `columns`.

    Three failures, one answer, so one message: a column in no cell is written
    by no writer and says nothing; a name left in a cell by a column that was
    dropped is a claim about a write nobody can perform; and a column in two
    cells is granted whatever the wrong cell grants while the union still
    matches the table, which is the half a symmetric difference alone cannot
    see. All three are answered by editing the cells above.

    Takes its two sides rather than reading them, for `folding._undeclared`'s
    reason: a test can drive it against cells and a table it builds.
    """
    counted = Counter(chain.from_iterable(cells))
    held = set(columns)
    return {
        name
        for name in set(counted) | held
        if counted[name] != 1 or name not in held
    }


#: Refused at import, not at the first write.
#:
#: A check at the first write fires in production, on somebody's library, and for
#: most of these columns it never fires at all: a writer that skips a column it
#: has never heard of raises nothing and stores nothing. This one fires on the
#: machine of whoever added the column and stops every test run until they
#: classify it. `Book.__table__` is built from code, so nothing in a database can
#: make it fire at runtime and not in the suite.
_MISFILED = _misfiled(PARTITION, Book.__table__.c.keys())
if _MISFILED:
    raise RuntimeError(
        "The column partition and `books` disagree, so a column is written by "
        "nobody with no diagnostic, or named by a rule that no longer has a "
        "column, or granted by two cells at once: "
        f"{sorted(_MISFILED)}. Every column of `books` belongs to exactly one "
        "cell above, `id`, `added_at`, `deleted_at` and `is_private` included, "
        "even where the cell is one naming what it refuses. Every writer of "
        "several columns takes its set from here, so a column classified "
        "nowhere is silently unmergeable, uncopyable and unenrichable."
    )
