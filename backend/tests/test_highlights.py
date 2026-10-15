"""The KOReader import's write and a member's delete, below the route: what a
race costs."""

import pytest
from sqlalchemy import event, text
from sqlalchemy.exc import IntegrityError

import highlights
from database import SessionLocal
from enums import HighlightSource
from models import HIGHLIGHT_SOURCE_KEY_MAX, Book, DeletedHighlight, Highlight
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
    key = next(iter(highlights.keyed(DIGEST, [MARK])))

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

    counts = highlights.import_koreader(db, book, member_id, DIGEST, [MARK])

    assert (counts.created, counts.updated) == (0, 1)
    assert db.query(Highlight).one().text == "Fear is the mind-killer."


def test_three_imports_of_one_file_at_once_all_settle(db, member, make_book):
    """Losing twice is a three way race, not a defect: the import keeps writing
    until it finds the rows that beat it."""
    book = db.get(Book, make_book(member["headers"])["id"])
    member_id = member["user"]["id"]
    second = MARK.model_copy(update={"highlighted_at": "2026-03-01 22:16:00"})
    keys = list(highlights.keyed(DIGEST, [MARK, second]))
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

    counts = highlights.import_koreader(db, book, member_id, DIGEST, [MARK, second])

    assert (counts.created, counts.updated) == (0, 2)


def test_an_import_racing_a_hand_delete_leaves_the_mark_deleted(db, member, make_book):
    """The import holds the row, the delete commits first, and the update then
    matches nothing: written again, the import finds the key remembered."""
    book = db.get(Book, make_book(member["headers"])["id"])
    member_id = member["user"]["id"]
    key = next(iter(highlights.keyed(DIGEST, [MARK])))
    highlights.import_koreader(db, book, member_id, DIGEST, [MARK])
    row_id = db.query(Highlight).one().id

    def the_delete_commits_first(session, *_):
        with SessionLocal() as other:
            other.add(
                DeletedHighlight(
                    user_id=member_id, source=HighlightSource.KOREADER, source_key=key
                )
            )
            other.flush()
            other.query(Highlight).filter(Highlight.id == row_id).delete()
            other.commit()

    event.listen(db, "before_flush", the_delete_commits_first, once=True)

    edited = MARK.model_copy(update={"note": "edited on the device"})
    counts = highlights.import_koreader(db, book, member_id, DIGEST, [edited])

    assert (counts.updated, counts.left_deleted) == (0, 1)
    assert db.query(Highlight).count() == 0


def test_a_second_delete_racing_the_first_finds_nothing_rather_than_failing(
    db, member, make_book
):
    """Both find the row, the other commits first, and this commit then meets
    the unique index on the remembered key: answered as no such row."""
    book = db.get(Book, make_book(member["headers"])["id"])
    member_id = member["user"]["id"]
    key = next(iter(highlights.keyed(DIGEST, [MARK])))
    highlights.import_koreader(db, book, member_id, DIGEST, [MARK])
    row_id = db.query(Highlight).one().id

    def the_other_delete_commits_first(session, *_):
        with SessionLocal() as other:
            other.add(
                DeletedHighlight(
                    user_id=member_id, source=HighlightSource.KOREADER, source_key=key
                )
            )
            other.query(Highlight).filter(Highlight.id == row_id).delete()
            other.commit()

    event.listen(db, "before_flush", the_other_delete_commits_first, once=True)

    assert highlights.delete_own(db, book, member_id, row_id) is False
    assert db.query(DeletedHighlight).count() == 1


class TestTheRememberedKeyIsBoundedInBytes:
    """`ck_deleted_highlights_bounds` bounds bytes, for a value the character
    arm and the NUL clause both admit: one `x'C0'` and its continuation bytes
    are one character to SQLite's `length()` and as many bytes as were written.
    """

    def _insert(self, db, member_id: int, total: int) -> None:
        raw = b"\xc0" + b"\x80" * (total - 1)
        db.execute(
            text(
                "INSERT INTO deleted_highlights (user_id, source, source_key) "
                f"VALUES (:member, 'koreader', CAST(x'{raw.hex()}' AS TEXT))"
            ),
            {"member": member_id},
        )
        db.commit()

    def test_one_byte_past_the_budget_is_refused(self, db, member):
        with pytest.raises(IntegrityError) as refusal:
            self._insert(db, member["user"]["id"], 4 * HIGHLIGHT_SOURCE_KEY_MAX + 1)

        assert "ck_deleted_highlights_bounds" in str(refusal.value)

    def test_the_budget_itself_is_stored(self, db, member):
        self._insert(db, member["user"]["id"], 4 * HIGHLIGHT_SOURCE_KEY_MAX)

        assert db.query(DeletedHighlight).count() == 1
