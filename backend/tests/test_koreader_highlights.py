"""The KOReader import below the route: what a race costs, settled by the
ledger's retry."""

from sqlalchemy import event

import koreader_highlights
from database import SessionLocal
from enums import HighlightSource
from models import Book, DeletedHighlight, Highlight
from schemas import KoreaderHighlightIn

DIGEST = "0123456789abcdef0123456789abcdef"
MARK = KoreaderHighlightIn(
    pos0="/body/p[1]/text().0",
    pos1="/body/p[1]/text().9",
    text="Fear is the mind-killer.",
    highlighted_at="2026-03-01 22:15:09",
)


def test_a_second_import_racing_the_first_updates_rather_than_failing(db, member, make_book):
    """Both read no row, the other commits first, and this commit then meets the
    unique index: rolled back and written again, it finds the row."""
    book = db.get(Book, make_book(member["headers"])["id"])
    member_id = member["user"]["id"]
    key = next(iter(koreader_highlights.keyed(DIGEST, [MARK])))

    def the_other_import_commits_first(session, *_):
        with SessionLocal() as other:
            other.add(
                Highlight(
                    book_id=book.id,
                    user_id=member_id,
                    source=HighlightSource.KOREADER,
                    source_key=key,
                    text="an older reading",
                )
            )
            other.commit()

    event.listen(db, "before_flush", the_other_import_commits_first, once=True)

    counts = koreader_highlights.import_koreader(db, book, member_id, DIGEST, [MARK])

    assert (counts.created, counts.updated) == (0, 1)
    assert db.query(Highlight).one().text == "Fear is the mind-killer."


def test_three_imports_of_one_file_at_once_all_settle(db, member, make_book):
    """Losing twice is a three way race, not a defect: the import keeps writing
    until it finds the rows that beat it."""
    book = db.get(Book, make_book(member["headers"])["id"])
    member_id = member["user"]["id"]
    second = MARK.model_copy(update={"highlighted_at": "2026-03-01 22:16:00"})
    keys = list(koreader_highlights.keyed(DIGEST, [MARK, second]))
    beaten = iter(keys)

    def another_import_commits_one_key(session, *_):
        key = next(beaten, None)
        if key is None:
            return
        with SessionLocal() as other:
            other.add(
                Highlight(
                    book_id=book.id,
                    user_id=member_id,
                    source=HighlightSource.KOREADER,
                    source_key=key,
                    text="an older reading",
                )
            )
            other.commit()

    event.listen(db, "before_flush", another_import_commits_one_key)

    counts = koreader_highlights.import_koreader(db, book, member_id, DIGEST, [MARK, second])

    assert (counts.created, counts.updated) == (0, 2)


def test_an_import_racing_a_hand_delete_leaves_the_mark_deleted(db, member, make_book):
    """The import holds the row, the delete commits first, and the update then
    matches nothing: written again, the import finds the key remembered."""
    book = db.get(Book, make_book(member["headers"])["id"])
    member_id = member["user"]["id"]
    key = next(iter(koreader_highlights.keyed(DIGEST, [MARK])))
    koreader_highlights.import_koreader(db, book, member_id, DIGEST, [MARK])
    row_id = db.query(Highlight).one().id

    def the_delete_commits_first(session, *_):
        with SessionLocal() as other:
            other.add(DeletedHighlight(user_id=member_id, source=HighlightSource.KOREADER, source_key=key))
            other.flush()
            other.query(Highlight).filter(Highlight.id == row_id).delete()
            other.commit()

    event.listen(db, "before_flush", the_delete_commits_first, once=True)

    edited = MARK.model_copy(update={"note": "edited on the device"})
    counts = koreader_highlights.import_koreader(db, book, member_id, DIGEST, [edited])

    assert (counts.updated, counts.left_deleted) == (0, 1)
    assert db.query(Highlight).count() == 0
