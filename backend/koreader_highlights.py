"""A KOReader sidecar's highlights as the ledger's marks: how each is keyed.

**KOReader gives an annotation no id**, so the key is derived here from the
file and when the mark was made (`koreader_source_key`), and `highlights`
writes what it is handed. **An import never deletes**: KOReader keeps no
tombstones, so a highlight absent from a later sidecar may have been deleted
on the device or may live on another one, and nothing here can tell which.

Reading progress from the same device is `kosync.py`'s, a separate door.
"""

import hashlib
from collections import Counter
from collections.abc import Sequence
from datetime import datetime

from sqlalchemy.orm import Session

import highlights
from enums import HighlightSource
from models import Book
from schemas import KoreaderHighlightIn
from schemas.highlight import KOREADER_DATETIME_FORMAT


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
    The other way round is `_alone_in_its_second`: a mark left alone in its
    second finds the row it had under the time and position form.

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


def _wall_clock(value: str | None) -> datetime | None:
    """KOReader's local time text as a naive datetime: the digits, no zone.

    Naive on purpose: KOReader records no zone, and `models.Highlight` says
    why none is invented.
    """
    if value is None:
        return None
    return datetime.strptime(value, KOREADER_DATETIME_FORMAT)  # noqa: DTZ007


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


def import_koreader(
    db: Session,
    book: Book,
    member_id: int,
    partial_md5: str,
    marks: Sequence[KoreaderHighlightIn],
) -> highlights.ImportCounts:
    """Write one sidecar's highlights onto `book` as `member_id`'s, and commit.

    `book` is one the caller resolved through `book_for_read`: the sidecar
    names the file, and the Book holding that file now is where its marks
    belong. What a write moves, keeps and leaves out is `highlights.write`;
    a racing import or hand delete is `highlights.settled`.
    """
    wanted = {
        key: highlights.Mark(
            text=mark.text,
            note=mark.note,
            chapter=mark.chapter,
            page=mark.page,
            highlighted_at=_wall_clock(mark.highlighted_at),
            former_key=_alone_in_its_second(partial_md5, key, mark),
        )
        for key, mark in keyed(partial_md5, marks).items()
    }

    def unit() -> highlights.ImportCounts:
        written = highlights.write(db, member_id, HighlightSource.KOREADER, book.id, wanted)
        db.commit()
        return written

    return highlights.settled(db, unit)
