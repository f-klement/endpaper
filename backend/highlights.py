"""The highlight ledger: what every source's import does once it has a key.

**A source names its marks; this module writes them.** `models.Highlight` is
unique on `(user_id, source, source_key)`. An adapter turns what its source
sends into marks by key (`koreader_highlights` derives a KOReader key, a
Readwise key is Readwise's own id), and `write` looks each key up, updates what
moved and creates the rest, so running the same import twice writes nothing
the second time. Every lookup by key is here, chunked by one bound.

**A write never deletes and never shares.** `is_shared` is the member's own
choice (`share`) and survives every re-run on the same Book that keeps the
passage within `QUOTE_TEXT_MAX`; a row a write moves to another Book, or
lengthens past that ceiling, is private again. Only Readwise reports a
deletion, so only its adapter calls `remove`.

**A member deletes their own highlight here, by hand** (`delete_own`), and the
key is remembered in `deleted_highlights`, so no later import of that source
still carrying the mark brings it back (`deleted_keys`).

**`write`, `remove` and `share` never commit.** The caller owns the unit of
work, because what commits with the marks is the caller's: nothing for
KOReader, the page's book rows and cursor for Readwise. `settled` re-runs such
a unit when a concurrent writer beat it. `delete_own` is a whole request, and
commits.

Reading a highlight out is the router's, under `highlight_visible_to`.
"""

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from sqlalchemy.orm.exc import StaleDataError

from enums import HighlightSource
from models import QUOTE_TEXT_MAX, Book, DeletedHighlight, Highlight

#: How many keys one lookup names, so a large import stays under every
#: engine's bound on bound parameters.
_LOOKUP_CHUNK = 500

#: How many times a unit of work runs before a collision is not a race. One
#: per concurrent writer of the same keys it can lose to; KOReader sets the
#: bound, since its client sends a member's picked sidecars at once.
_ATTEMPTS = 5


@dataclass(frozen=True)
class Mark:
    """One highlight as its source sent it, in the fields a row stores."""

    text: str
    note: str | None
    page: int | None
    highlighted_at: datetime | None
    chapter: str | None = None
    #: The key this mark was stored under before its source re-keyed it. A
    #: row held under it is found and re-keyed, and a deletion remembered
    #: under it still holds.
    former_key: str | None = None


@dataclass(frozen=True)
class ImportCounts:
    created: int
    updated: int
    unchanged: int
    #: Marks the member deleted here, which the import leaves deleted.
    left_deleted: int


def deleted_keys(db: Session, member_id: int, source: HighlightSource, keys: Sequence[str]) -> set[str]:
    """Which of these keys the member deleted here, so an import of `source`
    leaves them deleted."""
    found: set[str] = set()
    for start in range(0, len(keys), _LOOKUP_CHUNK):
        found.update(
            key
            for (key,) in db.query(DeletedHighlight.source_key).filter(
                DeletedHighlight.user_id == member_id,
                DeletedHighlight.source == source,
                DeletedHighlight.source_key.in_(keys[start : start + _LOOKUP_CHUNK]),
            )
        )
    return found


def holders(db: Session, member_id: int, source: HighlightSource, keys: Sequence[str]) -> dict[str, int]:
    """The Book holding each of these keys of the member's, by key; a key held
    nowhere is absent."""
    found: dict[str, int] = {}
    for start in range(0, len(keys), _LOOKUP_CHUNK):
        found.update(
            (key, book_id)
            for key, book_id in db.query(Highlight.source_key, Highlight.book_id).filter(
                Highlight.user_id == member_id,
                Highlight.source == source,
                Highlight.source_key.in_(keys[start : start + _LOOKUP_CHUNK]),
            )
        )
    return found


def delete_own(db: Session, book: Book, member_id: int, highlight_id: int) -> bool:
    """Delete `member_id`'s own highlight on `book`, remember its key, and
    commit. False when there is no such row.

    **Only the author's row**, shared or not: another member's highlight, even
    one shared with this member, is no row of theirs to delete.

    **Two deletes of one row racing** both find it, and the second commit meets
    the unique index on the remembered key. The first has then deleted the row,
    so the second answers as though it had found none.
    """
    row = (
        db.query(Highlight)
        .filter(
            Highlight.id == highlight_id,
            Highlight.book_id == book.id,
            Highlight.user_id == member_id,
        )
        .one_or_none()
    )
    if row is None:
        return False
    try:
        if not deleted_keys(db, member_id, row.source, [row.source_key]):
            db.add(DeletedHighlight(user_id=member_id, source=row.source, source_key=row.source_key))
        # Flushed before the row goes, so a lost race is the unique index
        # refusing the key, never a delete matching no row.
        db.flush()
        db.query(Highlight).filter(Highlight.id == row.id).delete(synchronize_session=False)
        db.commit()
    except IntegrityError:
        db.rollback()
        return False
    return True


def write(
    db: Session,
    member_id: int,
    source: HighlightSource,
    book_id: int,
    marks: Mapping[str, Mark],
) -> ImportCounts:
    """Write these marks onto `book_id` as `member_id`'s, without committing.

    `book_id` is a Book the caller resolved for this member. A key the member
    already holds is updated in place, **moved to this Book if it was on
    another**: the source placed the mark, and where it places it now is where
    it belongs.

    **A moved row is private again**, as on every path that changes a
    highlight's Book (`folding._carry_highlights` is the other). Sharing was
    the author's choice about the audience of one Book; another Book has
    another audience, which they never chose.

    **So is a row whose passage the write carries past `QUOTE_TEXT_MAX`**,
    the ceiling a share is refused above: the source lengthening it is not the
    author choosing to show the longer passage to the shelf.

    **A key the member deleted here is left out**, and so is one whose former
    key they deleted: either names the mark they deleted.
    """
    keys = [
        *marks,
        *(mark.former_key for mark in marks.values() if mark.former_key is not None),
    ]
    # Inline rather than a helper answering rows: a function handing back
    # highlights is a read for a viewer to the guard in `tests/test_models.py`,
    # and this one is the writer's own lookup.
    held: dict[str, Highlight] = {}
    for start in range(0, len(keys), _LOOKUP_CHUNK):
        held.update(
            (row.source_key, row)
            for row in db.query(Highlight).filter(
                Highlight.user_id == member_id,
                Highlight.source == source,
                Highlight.source_key.in_(keys[start : start + _LOOKUP_CHUNK]),
            )
        )
    # Read after the rows, never before. A hand delete commits the row's
    # removal and its remembered key together, and the two reads are two
    # snapshots: read first, the key would miss a delete landing between
    # them, which also hid the row, and the mark would be created again.
    # Read after, that delete is seen here; one landing later meets an update
    # matching no row, which `settled` retries, or no write at all.
    gone = deleted_keys(db, member_id, source, keys)

    created = updated = unchanged = left_deleted = 0
    for key, mark in marks.items():
        if key in gone or mark.former_key in gone:
            left_deleted += 1
            continue
        fields: dict[str, object] = {
            "book_id": book_id,
            "text": mark.text,
            "note": mark.note,
            "chapter": mark.chapter,
            "page": mark.page,
            "highlighted_at": mark.highlighted_at,
        }
        row = held.get(key)
        if row is None and mark.former_key is not None and mark.former_key in held:
            row = held[mark.former_key]
            row.source_key = key
        if row is None:
            db.add(Highlight(user_id=member_id, source=source, source_key=key, **fields))
            created += 1
            continue
        private = row.book_id != book_id or len(mark.text) > QUOTE_TEXT_MAX
        if private:
            fields["is_shared"] = False
        if any(getattr(row, name) != value for name, value in fields.items()):
            if private:
                # Written whatever the read said. The flush sets only what
                # differs from the row as loaded, so a row read private and
                # shared by its author since would keep that share, on the new
                # Book or past the ceiling. This statement also takes the row,
                # so a share arriving after it waits. Only on a row being
                # written anyway: a move changes its Book and a lengthening its
                # text, and an unchanged long passage cannot have been shared.
                db.execute(
                    update(Highlight)
                    .where(Highlight.id == row.id)
                    .values(is_shared=False)
                    .execution_options(synchronize_session=False)
                )
            for name, value in fields.items():
                setattr(row, name, value)
            updated += 1
        else:
            unchanged += 1
    return ImportCounts(created=created, updated=updated, unchanged=unchanged, left_deleted=left_deleted)


def remove(db: Session, member_id: int, source: HighlightSource, keys: Sequence[str]) -> int:
    """Remove the member's rows of `source` under these keys, without
    committing, and answer how many went.

    **The key is not remembered**: the source deleted the mark, so a later
    import that carries it again is the source restoring it.
    """
    removed = 0
    for start in range(0, len(keys), _LOOKUP_CHUNK):
        removed += (
            db.query(Highlight)
            .filter(
                Highlight.user_id == member_id,
                Highlight.source == source,
                Highlight.source_key.in_(keys[start : start + _LOOKUP_CHUNK]),
            )
            .delete(synchronize_session=False)
        )
    return removed


def share(db: Session, member_id: int, highlight_id: int, book_id: int, shared: bool) -> str | None:
    """Share the member's highlight with `book_id`'s readers, or withdraw it,
    without committing. Answers the passage as written, None when the
    highlight is no longer on `book_id`.

    **Written only where it still is on that Book.** An import moving it since
    the caller read it made it private for the new Book's audience, and a write
    by its id alone would publish it there, to readers its author never chose.

    **The passage comes back from the write itself**, so a caller judging it
    judges what this statement shared rather than what it read earlier: an
    import may have rewritten it in between.
    """
    return db.execute(
        update(Highlight)
        .where(
            Highlight.id == highlight_id,
            Highlight.book_id == book_id,
            Highlight.user_id == member_id,
        )
        .values(is_shared=shared)
        .returning(Highlight.text)
        .execution_options(synchronize_session=False)
    ).scalar_one_or_none()


def settled[T](db: Session, unit: Callable[[], T]) -> T:
    """Run `unit`, a caller's write and its commit, until it is not beaten.

    **A second import of the same marks racing this one** inserts the same keys
    first, and this commit then meets the unique index. That is answered by
    rolling back and running the unit again, which now finds those rows and
    updates them: the race costs a retry, never a 500. Each retry finds at
    least the rows that beat it, so a few imports at once settle within
    `_ATTEMPTS`; past that the collision is not a race, and raises.

    **A hand delete racing it** removes a row the unit is updating, so the
    update matches no row. That is a retry as well, and the retry finds the
    key remembered and leaves the mark out.

    **The rollback discards everything since the last commit**, so whatever
    the unit must commit has to be assigned inside it, not before.
    """
    for _ in range(_ATTEMPTS - 1):
        try:
            return unit()
        except IntegrityError, StaleDataError:
            db.rollback()
    return unit()
