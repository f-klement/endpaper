"""Writing a member's highlights from a source, so that every import re-runs.

**The identity of a highlight is its source's, and this module is where a
KOReader one is derived.** `models.Highlight` is unique on `(user_id, source,
source_key)`; an import looks each key up, updates what moved and creates the
rest, so running the same sidecar twice writes nothing the second time.

**An import never deletes and never shares.** KOReader keeps no tombstones,
so a highlight absent from a later sidecar may have been deleted on the device
or may live on another one, and nothing here can tell which. `is_shared` is the
member's own choice and survives every re-run on the same Book; a row an
import moves to another Book is private again (`import_koreader`).

Reading a highlight out is the router's, under `highlight_visible_to`.
"""

import hashlib
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from enums import HighlightSource
from models import Book, Highlight
from schemas import KoreaderHighlightIn
from schemas.highlight import KOREADER_DATETIME_FORMAT

#: How many keys one lookup names, so a large sidecar stays under every
#: engine's bound on bound parameters.
_LOOKUP_CHUNK = 500

#: How many times an import writes before a collision is not a race. One per
#: concurrent import of the same file it can lose to, and the client sends at
#: most a member's picked sidecars at once.
_ATTEMPTS = 5


def koreader_source_key(
    partial_md5: str,
    created: str | None,
    pos0: str,
    pos1: str,
    *,
    shared_time: bool = False,
) -> str:
    """A KOReader highlight's stable key, from the file and when it was made.

    **The creation time first**, because it is the one field KOReader never
    rewrites: `datetime` is set when the mark is made and stays when its ends
    are adjusted, which moves `pos0` and `pos1`. So an adjusted mark keeps its
    key and re-imports as an update rather than a second row.

    **The positions only where the time cannot do it**: a mark with no
    `datetime` (very old KOReader), and two marks of one request made in the
    same second (`shared_time`), which the time alone would fold into one.
    Such a mark is keyed on where it is, so adjusting it does make a new row,
    and so does a second mark appearing in the same second as an imported one.
    The other way round is handled in `_write`: a mark left alone in its second
    finds the row it had under the time and position form.

    **The file's fingerprint is in every key**, because a time or a position
    means something only inside one file. Hashed, because positions can be
    thousands of characters and the key is an index column: SHA-256 over the
    parts joined by NUL, which none of them can contain, after a tag naming
    which form this is so two forms can never produce one key.

    **Stable only for the same bytes.** A re-converted book has a new
    fingerprint, so its highlights arrive as new rows.
    """
    if created is not None and not shared_time:
        parts: tuple[str, ...] = ("time", partial_md5, created)
    elif created is not None:
        parts = ("time+position", partial_md5, created, pos0, pos1)
    else:
        parts = ("position", partial_md5, pos0, pos1)
    return hashlib.sha256("\x00".join(parts).encode()).hexdigest()


def keyed(
    partial_md5: str, marks: Sequence[KoreaderHighlightIn]
) -> dict[str, KoreaderHighlightIn]:
    """One request's marks by key; two marks with one key are one, the later
    winning, which is KOReader's own rule for a match.

    **The same second is counted over the request, not the sidecar**, so the
    client keeps every mark of one second in one request: split across two,
    each would be keyed on the time alone and the pair would share a row.
    """
    times = Counter(mark.highlighted_at for mark in marks if mark.highlighted_at)
    return {
        koreader_source_key(
            partial_md5,
            mark.highlighted_at,
            mark.pos0,
            mark.pos1,
            shared_time=times[mark.highlighted_at or ""] > 1,
        ): mark
        for mark in marks
    }


@dataclass(frozen=True)
class ImportCounts:
    created: int
    updated: int
    unchanged: int


def _wall_clock(value: str | None) -> datetime | None:
    """KOReader's local time text as a naive datetime: the digits, no zone.

    Naive on purpose: KOReader records no zone, and `models.Highlight` says
    why none is invented.
    """
    if value is None:
        return None
    return datetime.strptime(value, KOREADER_DATETIME_FORMAT)  # noqa: DTZ007


def import_koreader(
    db: Session,
    book: Book,
    member_id: int,
    partial_md5: str,
    marks: Sequence[KoreaderHighlightIn],
) -> ImportCounts:
    """Write one sidecar's highlights onto `book` as `member_id`'s, and commit.

    `book` is one the caller resolved through `book_for_read`. A key the member
    already holds is updated in place, **moved to this Book if it was on
    another**: the sidecar names the file, and the Book holding that file now
    is where its marks belong.

    **A moved row is private again**, as on every path that changes a
    highlight's Book (`folding._carry_highlights` is the other). Sharing was
    the author's choice about the audience of one Book; another Book has
    another audience, which they never chose.

    **A second import of the same marks racing this one** inserts the same keys
    first, and this commit then meets the unique index. That is answered by
    rolling back and writing again, which now finds those rows and updates
    them: the race costs a retry, never a 500. Each retry finds at least the
    rows that beat it, so a few imports of one file at once settle within
    `_ATTEMPTS`; past that the collision is not a race, and raises.
    """
    wanted = keyed(partial_md5, marks)
    for _ in range(_ATTEMPTS - 1):
        try:
            return _write(db, book, member_id, partial_md5, wanted)
        except IntegrityError:
            db.rollback()
    return _write(db, book, member_id, partial_md5, wanted)


def _alone_in_its_second(
    partial_md5: str, key: str, mark: KoreaderHighlightIn
) -> str | None:
    """The key this mark had while another mark shared its second, if it is
    keyed on its time alone now; so deleting one of a pair on the device does
    not make the other a new row."""
    if mark.highlighted_at is None or key != koreader_source_key(
        partial_md5, mark.highlighted_at, mark.pos0, mark.pos1
    ):
        return None
    return koreader_source_key(
        partial_md5, mark.highlighted_at, mark.pos0, mark.pos1, shared_time=True
    )


def _write(
    db: Session,
    book: Book,
    member_id: int,
    partial_md5: str,
    wanted: dict[str, KoreaderHighlightIn],
) -> ImportCounts:
    earlier = {
        key: former
        for key, mark in wanted.items()
        if (former := _alone_in_its_second(partial_md5, key, mark)) is not None
    }
    keys = [*wanted, *earlier.values()]
    held: dict[str, Highlight] = {}
    for start in range(0, len(keys), _LOOKUP_CHUNK):
        chunk = keys[start : start + _LOOKUP_CHUNK]
        held.update(
            (row.source_key, row)
            for row in db.query(Highlight).filter(
                Highlight.user_id == member_id,
                Highlight.source == HighlightSource.KOREADER,
                Highlight.source_key.in_(chunk),
            )
        )

    created = updated = unchanged = 0
    for key, mark in wanted.items():
        fields: dict[str, object] = {
            "book_id": book.id,
            "text": mark.text,
            "note": mark.note,
            "chapter": mark.chapter,
            "page": mark.page,
            "highlighted_at": _wall_clock(mark.highlighted_at),
        }
        row = held.get(key)
        if row is None and key in earlier and earlier[key] in held:
            row = held[earlier[key]]
            row.source_key = key
        if row is None:
            db.add(
                Highlight(
                    user_id=member_id,
                    source=HighlightSource.KOREADER,
                    source_key=key,
                    **fields,
                )
            )
            created += 1
            continue
        if row.book_id != book.id:
            fields["is_shared"] = False
        if any(getattr(row, name) != value for name, value in fields.items()):
            for name, value in fields.items():
                setattr(row, name, value)
            updated += 1
        else:
            unchanged += 1
    db.commit()
    return ImportCounts(created=created, updated=updated, unchanged=unchanged)
